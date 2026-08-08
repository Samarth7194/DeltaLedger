from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ParsedFinancialNumber:
    original_text: str
    value: Decimal
    unit: str


NUMBER_RE = re.compile(
    r"(?P<currency>\$|USD\s*)?"
    r"(?P<negative>\()?"
    r"(?P<sign>-)?"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)"
    r"\)?\s*"
    r"(?P<scale>billion|million|bn|b(?!ps)|m)?"
    r"\s*(?P<unit>bps|basis points?|percentage points?|%|percent|USD/share|per share)?",
    re.I,
)

SCALE = {
    None: Decimal("1"),
    "m": Decimal("1000000"),
    "million": Decimal("1000000"),
    "b": Decimal("1000000000"),
    "bn": Decimal("1000000000"),
    "billion": Decimal("1000000000"),
}


def parse_financial_number(text: str) -> ParsedFinancialNumber | None:
    match = NUMBER_RE.search(text)
    if match is None:
        return None
    number = Decimal(match.group("number").replace(",", ""))
    scale = SCALE[(match.group("scale") or "").lower() or None]
    raw_unit = (match.group("unit") or "").lower()
    if "basis" in raw_unit or raw_unit == "bps":
        value = number / Decimal("100")
        unit = "percentage_points"
    elif "percentage point" in raw_unit:
        value = number
        unit = "percentage_points"
    elif raw_unit in {"%", "percent"}:
        value = number
        unit = "percent"
    elif "share" in raw_unit:
        value = number * scale
        unit = "USD/share"
    elif match.group("currency"):
        value = number * scale
        unit = "USD"
    else:
        value = number * scale
        unit = "absolute"
    if match.group("negative") or match.group("sign"):
        value = -value
    return ParsedFinancialNumber(
        original_text=match.group(0).strip(),
        value=value,
        unit=unit,
    )


def parse_all_financial_numbers(text: str) -> list[ParsedFinancialNumber]:
    parsed = []
    for match in NUMBER_RE.finditer(text):
        value = parse_financial_number(match.group(0))
        if value is not None:
            parsed.append(value)
    return parsed


def decimal_to_json(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None
