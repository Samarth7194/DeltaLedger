from __future__ import annotations

from app.evaluation.metrics import (
    classification_report,
    expected_calibration_error,
    false_positive_rate,
    ranking_metrics,
)


def test_classification_metrics_are_manually_checkable() -> None:
    report = classification_report(
        ["added", "removed", "removed", "weakened"],
        ["added", "added", "removed", "weakened"],
        labels=["added", "removed", "weakened"],
    )

    assert report["accuracy"]["value"] == 0.75
    assert report["per_label"]["added"]["precision"] == 0.5
    assert report["per_label"]["removed"]["recall"] == 0.5
    assert report["macro_f1"]["value"] == 0.7778


def test_false_positive_rate_requires_negative_controls() -> None:
    assert false_positive_rate([True], [True])["status"] == "not_evaluated"
    assert false_positive_rate([False, False, True], [True, False, True])["value"] == 0.5


def test_ranking_metrics_cover_recall_mrr_and_ndcg() -> None:
    report = ranking_metrics(
        [
            {
                "relevant_documents": {"a": 3, "c": 1},
                "rankings": {"hybrid": ["a", "b", "c"]},
            }
        ],
        system_name="hybrid",
        ks=(1, 5, 10),
    )

    assert report["recall@1"]["value"] == 0.5
    assert report["recall@5"]["value"] == 1.0
    assert report["mrr"]["value"] == 1.0
    assert report["ndcg@5"]["value"] > 0.9


def test_expected_calibration_error_buckets_predictions() -> None:
    report = expected_calibration_error(
        [
            {"confidence": 0.9, "correct": True},
            {"confidence": 0.9, "correct": False},
        ],
        bucket_count=2,
    )

    assert report["value"] == 0.4
    assert report["n"] == 2
