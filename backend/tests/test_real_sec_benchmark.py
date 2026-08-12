from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.evaluation.datasets import load_dataset_examples, load_manifest
from app.evaluation.evaluators import evaluate_manifest
from app.evaluation.real_sec import (
    evaluate_real_sec_examples,
    load_real_sec_payload,
    pending_annotation_queue,
    update_annotation_status,
    validate_real_sec_payload,
)

REAL_SEC_PATH = Path("evaluation/datasets/real_sec_v1/examples.json")
REAL_SEC_MANIFEST = Path("evaluation/datasets/real_sec_v1/manifest.json")


def test_real_sec_benchmark_schema_validates() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)

    summary = validate_real_sec_payload(payload)

    assert summary.company_count == 20
    assert summary.filing_pair_count == 32
    assert summary.annotation_count == 80
    assert summary.status_counts == {
        "approved": 10,
        "candidate": 64,
        "rejected": 4,
        "uncertain": 2,
    }
    assert summary.approved_count == 10
    assert summary.uncertain_count == 2
    assert summary.automated_review_counts == {
        "AUTOMATED_READY": 35,
        "AUTOMATED_UNCERTAIN": 29,
    }
    assert summary.negative_control_count >= 30
    assert set(summary.task_counts.values()) == {10}


def test_real_sec_benchmark_contains_hardened_source_review_metadata() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)

    for example in payload["examples"]:
        review = example["source_review"]
        assert example["annotation_status"] in {"approved", "candidate", "rejected", "uncertain"}
        assert review["reviewability_status"] in {
            "READY_FOR_HUMAN_REVIEW",
            "NEEDS_MORE_SOURCE_EVIDENCE",
            "AMBIGUOUS",
            "REPLACEMENT_REQUIRED",
        }
        assert review["source_quality"] in {"HIGH", "MEDIUM", "LOW"}
        assert review["label_confidence"] in {"HIGH", "MEDIUM", "LOW"}
        assert review["review_difficulty"] in {"A", "B", "C"}
        assert review["filings"]["current"]["source_url"].startswith("https://www.sec.gov/")
        assert review["source_evidence"]
        if example["annotation_status"] == "approved":
            assert example["annotator"] == "Samarth Shinde"
            assert example["review"]["reviewed_by"] == "Samarth Shinde"
            assert review["reviewability_status"] == "READY_FOR_HUMAN_REVIEW"
            assert review["replacement_required_reason"] is None
        if example["id"].startswith("real-sec-v1-r1-"):
            automated_review = example["automated_review"]
            assert example["annotation_status"] == "candidate"
            assert automated_review["reviewer_type"] == "automated"
            assert automated_review["status"] in {
                "AUTOMATED_READY",
                "AUTOMATED_UNCERTAIN",
            }
            assert automated_review["notes"].endswith("This is not human approval.")


def test_real_sec_benchmark_records_phase10c_label_corrections() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)
    by_id = {example["id"]: example for example in payload["examples"]}

    vz = by_id["real-sec-v1-xbrl-001"]
    assert vz["expected"]["expected_concept"] == "Revenues"
    assert vz["expected"]["expected_selection_status"] == "selected"
    assert vz["source_review"]["xbrl_candidate_scores"][0]["combined_score"] == "0.9900"

    contradiction = by_id["real-sec-v1-ct-002"]
    assert contradiction["expected"]["contradiction_type"] == "non_candidate"
    assert contradiction["expected"]["replacement_required"] is True
    assert contradiction["source_review"]["reviewability_status"] == "REPLACEMENT_REQUIRED"


def test_real_sec_benchmark_rejects_company_split_leakage() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)
    leaked = copy.deepcopy(payload)
    leaked["companies"].append(
        {
            "ticker": "AAPL",
            "cik": "0000320193",
            "legal_name": "Apple Inc.",
            "industry": "technology",
            "split": "test",
        }
    )

    with pytest.raises(ValueError, match="multiple splits"):
        validate_real_sec_payload(leaked)


def test_real_sec_benchmark_requires_negative_controls() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)
    missing_negatives = copy.deepcopy(payload)
    for example in missing_negatives["examples"]:
        example["negative_control"] = False

    with pytest.raises(ValueError, match="negative controls"):
        validate_real_sec_payload(missing_negatives)


def test_real_sec_annotation_status_update_requires_review_metadata() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)
    for example in payload["examples"]:
        example["annotation_status"] = "candidate"
        example["annotator"] = None
        example.pop("review", None)
    updated = update_annotation_status(
        payload,
        annotation_id="real-sec-v1-ct-001",
        status="approved",
        annotator="reviewer@example.com",
        notes="Reviewed source text and accepted as a negative control.",
    )

    summary = validate_real_sec_payload(payload)

    assert updated is True
    assert summary.approved_count == 1
    reviewed = next(
        example for example in payload["examples"] if example["id"] == "real-sec-v1-ct-001"
    )
    assert reviewed["review"]["reviewed_by"] == "reviewer@example.com"


def test_real_sec_approval_rejects_replacement_required_annotations() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)
    example = next(
        item for item in payload["examples"] if item["id"] == "real-sec-v1-ct-002"
    )
    example["annotation_status"] = "approved"
    example["annotator"] = "reviewer@example.com"
    example["review"] = {
        "reviewed_by": "reviewer@example.com",
        "reviewed_at": "2026-08-12T00:00:00Z",
    }

    with pytest.raises(ValueError, match="cannot be approved"):
        validate_real_sec_payload(payload)


def test_real_sec_approved_xbrl_labels_require_structured_facts() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)
    example = next(
        item for item in payload["examples"] if item["id"] == "real-sec-v1-xbrl-001"
    )
    example["annotation_status"] = "approved"
    example["annotator"] = "reviewer@example.com"
    example["review"] = {
        "reviewed_by": "reviewer@example.com",
        "reviewed_at": "2026-08-12T00:00:00Z",
    }
    example["source_review"]["structured_facts"] = []

    with pytest.raises(ValueError, match="structured_facts"):
        validate_real_sec_payload(payload)


def test_real_sec_benchmark_rejects_invalid_annotation_status() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)
    invalid = copy.deepcopy(payload)
    invalid["examples"][0]["annotation_status"] = "gold"

    with pytest.raises(ValueError, match="unsupported annotation_status"):
        validate_real_sec_payload(invalid)


def test_real_sec_pending_queue_lists_candidate_examples() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)

    queue = pending_annotation_queue(payload["examples"])

    assert len(queue) == 64
    assert {item["task_type"] for item in queue} == {
        "contradiction_candidate",
        "disclosure_change",
        "evidence_quality",
        "financial_claim",
        "passage_alignment",
        "section_matching",
        "verification",
        "xbrl_resolution",
    }


@pytest.mark.asyncio
async def test_real_sec_evaluator_integrates_with_phase8_runner() -> None:
    manifest = load_manifest(REAL_SEC_MANIFEST)
    examples = load_dataset_examples(manifest)

    result = await evaluate_manifest(manifest)

    assert len(examples) == 80
    assert result.suite == "real_sec_benchmark"
    assert result.metrics["annotation_summary"]["approved_examples"] == 10
    assert result.metrics["annotation_summary"]["human_gold_examples"] == 10
    assert result.metrics["annotation_summary"]["provisional_automated_ready_examples"] == 35
    assert result.metrics["tasks"]["contradiction_candidate"]["status"] == "not_evaluated"
    assert (
        result.metrics["provisional_tasks"]["disclosure_change"]["reason"]
        == "No provisional automated-ready real-sec labels for disclosure_change."
    )
    assert len(result.metrics["automated_review_error_analysis"]) == 29
    root_causes = {
        row["root_cause"] for row in result.metrics["automated_review_error_analysis"]
    }
    assert {"EVIDENCE", "VERIFICATION", "XBRL_CONCEPT"} <= root_causes


def test_real_sec_error_analysis_reports_failures_for_approved_predictions() -> None:
    payload = load_real_sec_payload(REAL_SEC_PATH)
    example = copy.deepcopy(payload["examples"][0])
    example["annotation_status"] = "approved"
    example["annotator"] = "reviewer@example.com"
    example["review"] = {
        "reviewed_by": "reviewer@example.com",
        "reviewed_at": "2026-08-11T00:00:00Z",
    }
    example["system_prediction"] = {"should_match": False, "confidence": 0.41}

    metrics = evaluate_real_sec_examples([example])

    assert metrics["tasks"]["section_matching"]["accuracy"]["value"] == 0.0
    assert metrics["error_analysis"][0]["failure_category"] == "wrong_section"
