from decimal import Decimal

from app.services.financial_number_parser import parse_all_financial_numbers, parse_financial_number


def test_parse_scaled_monetary_values_without_float_rounding() -> None:
    parsed = parse_financial_number("revenue was $1.25 billion")

    assert parsed is not None
    assert parsed.value == Decimal("1250000000.00")
    assert parsed.unit == "USD"


def test_parse_parenthetical_negative_and_plain_absolute() -> None:
    negative = parse_financial_number("net loss was $(42.5 million)")
    absolute = parse_financial_number("customers totaled 1,250")

    assert negative is not None
    assert negative.value == Decimal("-42500000.0")
    assert negative.unit == "USD"
    assert absolute is not None
    assert absolute.value == Decimal("1250")
    assert absolute.unit == "absolute"


def test_parse_percent_basis_points_and_percentage_points() -> None:
    values = parse_all_financial_numbers(
        "Gross margin increased 12.5% and then expanded by 125 bps, or 1.25 percentage points."
    )

    assert [(item.value, item.unit) for item in values] == [
        (Decimal("12.5"), "percent"),
        (Decimal("1.25"), "percentage_points"),
        (Decimal("1.25"), "percentage_points"),
    ]
