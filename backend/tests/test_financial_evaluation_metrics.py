from decimal import Decimal

import pytest

from app.services.financial_evaluation_metrics import exact_match_accuracy, phase4_label_metrics


def test_exact_match_accuracy() -> None:
    assert exact_match_accuracy(["verified", "contradicted"], ["verified", "verified"]) == (
        Decimal("0.5000")
    )


def test_exact_match_accuracy_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        exact_match_accuracy(["verified"], [])


def test_phase4_label_metrics_counts_statuses() -> None:
    metrics = phase4_label_metrics(
        [
            {"expected_status": "verified", "actual_status": "verified"},
            {"expected_status": "contradicted", "actual_status": "contradicted"},
            {"expected_status": "verified", "actual_status": "contradicted"},
        ]
    )

    assert metrics == {
        "example_count": 3,
        "exact_match_accuracy": "0.6667",
        "status_counts": {"contradicted": 2, "verified": 1},
    }
