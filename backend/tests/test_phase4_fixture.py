from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def test_phase4_financial_claim_fixture_has_required_coverage() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "financial_claims" / "phase4_examples.json"
    examples = json.loads(fixture_path.read_text(encoding="utf-8"))
    categories = Counter(example["category"] for example in examples)
    metrics = {example.get("metric") for example in examples}

    assert len(examples) == 60
    assert categories == {
        "absolute_value": 15,
        "percentage_change": 15,
        "percentage_point_change": 10,
        "period_resolution": 10,
        "ambiguous_or_error": 10,
    }
    assert {
        "revenue",
        "gross_profit",
        "gross_margin",
        "operating_income",
        "net_income",
        "cash_and_cash_equivalents",
        "long_term_debt",
        "basic_eps",
        "diluted_eps",
    } <= metrics
