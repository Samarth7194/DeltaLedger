from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def test_phase5_evaluation_fixture_has_required_reviewed_distribution() -> None:
    fixture_path = Path("tests/fixtures/contradictions/phase5_examples.json")
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    examples = payload["examples"]
    counts = Counter(example["expected_type"] for example in examples)

    assert len(examples) == 80
    assert counts == payload["distribution"]
    assert {example["review_status"] for example in examples} == {"approved"}
