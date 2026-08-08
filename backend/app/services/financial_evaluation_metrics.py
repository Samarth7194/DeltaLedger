from __future__ import annotations

from collections import Counter
from decimal import Decimal


def exact_match_accuracy(expected: list[str], actual: list[str]) -> Decimal:
    if len(expected) != len(actual):
        raise ValueError("Expected and actual labels must have the same length.")
    if not expected:
        return Decimal("0")
    matches = sum(1 for left, right in zip(expected, actual, strict=True) if left == right)
    return (Decimal(matches) / Decimal(len(expected))).quantize(Decimal("0.0001"))


def phase4_label_metrics(rows: list[dict[str, str]]) -> dict[str, object]:
    expected = [row["expected_status"] for row in rows]
    actual = [row["actual_status"] for row in rows]
    counts = Counter(actual)
    return {
        "example_count": len(rows),
        "exact_match_accuracy": str(exact_match_accuracy(expected, actual)),
        "status_counts": dict(sorted(counts.items())),
    }
