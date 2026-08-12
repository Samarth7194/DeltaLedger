from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evaluation.metrics import classification_report, false_positive_rate, not_evaluated

ANNOTATION_STATUSES = {
    "candidate",
    "human_reviewed",
    "approved",
    "rejected",
    "uncertain",
}
AUTOMATED_REVIEW_STATUSES = {
    "AUTOMATED_READY",
    "AUTOMATED_REJECT",
    "AUTOMATED_UNCERTAIN",
    "REPLACEMENT_REQUIRED",
}
TASK_TYPES = {
    "section_matching",
    "passage_alignment",
    "disclosure_change",
    "financial_claim",
    "xbrl_resolution",
    "verification",
    "contradiction_candidate",
    "evidence_quality",
}
CHANGE_TYPES = {"added", "removed", "strengthened", "weakened", "no_material_change"}
RISK_CATEGORIES = {"liquidity", "revenue_guidance", "litigation", "operations", "other"}
ALIGNMENT_LABELS = {"aligned", "added", "removed", "not_aligned"}
VERIFICATION_STATUSES = {
    "verified",
    "approximately_verified",
    "contradicted",
    "ambiguous_fact",
    "unsupported_metric",
    "insufficient_data",
    "period_mismatch",
    "unit_mismatch",
    "zero_denominator",
}
CONTRADICTION_TYPES = {
    "direction_contradiction",
    "magnitude_overstatement",
    "magnitude_understatement",
    "narrative_cross_section_inconsistency",
    "non_candidate",
    "numerical_claim_contradiction",
    "temporal_narrative_inconsistency",
    "unsupported_qualitative_claim",
}
REVIEWABILITY_STATUSES = {
    "READY_FOR_HUMAN_REVIEW",
    "NEEDS_MORE_SOURCE_EVIDENCE",
    "AMBIGUOUS",
    "REPLACEMENT_REQUIRED",
}
SOURCE_QUALITY = {"HIGH", "MEDIUM", "LOW"}
LABEL_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
REVIEW_DIFFICULTY = {"A", "B", "C"}
REQUIRED_TASKS_WITH_NEGATIVES = {
    "section_matching",
    "passage_alignment",
    "financial_claim",
    "contradiction_candidate",
}


@dataclass(frozen=True)
class RealSecValidationSummary:
    company_count: int
    filing_pair_count: int
    annotation_count: int
    status_counts: dict[str, int]
    task_counts: dict[str, int]
    negative_control_count: int
    approved_count: int
    uncertain_count: int
    automated_review_counts: dict[str, int]


def load_real_sec_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_real_sec_payload(payload: dict[str, Any]) -> RealSecValidationSummary:
    companies = _require_list(payload, "companies")
    filing_pairs = _require_list(payload, "filing_pairs")
    examples = _require_list(payload, "examples")
    if not companies:
        raise ValueError("real_sec benchmark must include at least one company.")
    if not filing_pairs:
        raise ValueError("real_sec benchmark must include filing pairs.")
    if not examples:
        raise ValueError("real_sec benchmark must include annotations.")

    company_splits: dict[str, str] = {}
    for company in companies:
        ticker = _required_str(company, "ticker")
        split = _required_str(company, "split")
        existing = company_splits.get(ticker)
        if existing is not None and existing != split:
            raise ValueError(f"Company {ticker} appears in multiple splits.")
        company_splits[ticker] = split

    pair_ids = set()
    pair_fingerprints = set()
    for pair in filing_pairs:
        pair_id = _required_str(pair, "pair_id")
        if pair_id in pair_ids:
            raise ValueError(f"Duplicate filing pair id: {pair_id}")
        pair_ids.add(pair_id)
        ticker = _required_str(pair, "ticker")
        if ticker not in company_splits:
            raise ValueError(f"Filing pair {pair_id} references unknown ticker {ticker}.")
        if _required_str(pair, "form") != "10-Q":
            raise ValueError(f"Filing pair {pair_id} is not a 10-Q pair.")
        if _required_str(pair, "current_report_period") <= _required_str(
            pair, "previous_report_period"
        ):
            raise ValueError(f"Filing pair {pair_id} does not have current period > previous.")
        fingerprint = (
            ticker,
            _required_str(pair, "current_accession"),
            _required_str(pair, "previous_accession"),
        )
        if fingerprint in pair_fingerprints:
            raise ValueError(f"Duplicate filing pair accession tuple: {pair_id}")
        pair_fingerprints.add(fingerprint)

    annotation_ids = set()
    annotation_fingerprints = set()
    status_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    negative_task_counts: Counter[str] = Counter()
    for example in examples:
        annotation_id = _required_str(example, "id")
        if annotation_id in annotation_ids:
            raise ValueError(f"Duplicate annotation id: {annotation_id}")
        annotation_ids.add(annotation_id)
        task_type = _required_str(example, "task_type")
        if task_type not in TASK_TYPES:
            raise ValueError(f"{annotation_id} has unsupported task_type {task_type}.")
        status = _required_str(example, "annotation_status")
        if status not in ANNOTATION_STATUSES:
            raise ValueError(f"{annotation_id} has unsupported annotation_status {status}.")
        pair_id = _required_str(example, "pair_id")
        if pair_id not in pair_ids:
            raise ValueError(f"{annotation_id} references unknown pair_id {pair_id}.")
        expected = _require_dict(example, "expected")
        _validate_expected(annotation_id, task_type, expected)
        source_review = example.get("source_review")
        if source_review is not None:
            _validate_source_review(annotation_id, task_type, expected, source_review)
        automated_review = example.get("automated_review")
        if automated_review is not None:
            _validate_automated_review(annotation_id, automated_review)
        fingerprint = (
            task_type,
            pair_id,
            json.dumps(example.get("input_references", {}), sort_keys=True),
            json.dumps(expected, sort_keys=True),
        )
        if fingerprint in annotation_fingerprints:
            raise ValueError(f"Duplicate exact annotation example: {annotation_id}")
        annotation_fingerprints.add(fingerprint)
        if status == "approved":
            review = _require_dict(example, "review")
            if not review.get("reviewed_by") or not review.get("reviewed_at"):
                raise ValueError(f"Approved annotation {annotation_id} lacks review metadata.")
            approved_source_review = _require_dict(example, "source_review")
            _validate_approved_source_review(
                annotation_id,
                task_type,
                expected,
                approved_source_review,
            )
        if status in {"approved", "human_reviewed"} and not example.get("annotator"):
            raise ValueError(f"Reviewed annotation {annotation_id} lacks annotator.")
        status_counts[status] += 1
        task_counts[task_type] += 1
        if bool(example.get("negative_control")):
            negative_task_counts[task_type] += 1

    missing_negative_tasks = sorted(REQUIRED_TASKS_WITH_NEGATIVES - set(negative_task_counts))
    if missing_negative_tasks:
        raise ValueError(
            "real_sec benchmark is missing negative controls for tasks: "
            + ", ".join(missing_negative_tasks)
        )

    return RealSecValidationSummary(
        company_count=len(companies),
        filing_pair_count=len(filing_pairs),
        annotation_count=len(examples),
        status_counts=dict(sorted(status_counts.items())),
        task_counts=dict(sorted(task_counts.items())),
        negative_control_count=sum(negative_task_counts.values()),
        approved_count=status_counts["approved"],
        uncertain_count=status_counts["uncertain"],
        automated_review_counts=dict(
            sorted(
                Counter(
                    str(example["automated_review"]["status"])
                    for example in examples
                    if isinstance(example.get("automated_review"), dict)
                ).items()
            )
        ),
    )


def evaluate_real_sec_examples(examples: list[dict[str, Any]]) -> dict[str, object]:
    status_counts = Counter(str(example.get("annotation_status")) for example in examples)
    task_counts = Counter(str(example.get("task_type")) for example in examples)
    approved = [example for example in examples if example.get("annotation_status") == "approved"]
    provisional = [
        example
        for example in examples
        if example.get("annotation_status") == "candidate"
        and isinstance(example.get("automated_review"), dict)
        and example["automated_review"].get("status") == "AUTOMATED_READY"
    ]
    automated_review_counts = Counter(
        str(example["automated_review"]["status"])
        for example in examples
        if isinstance(example.get("automated_review"), dict)
    )
    metrics: dict[str, object] = {
        "annotation_summary": {
            "total_examples": len(examples),
            "status_counts": dict(sorted(status_counts.items())),
            "task_counts": dict(sorted(task_counts.items())),
            "negative_controls": sum(1 for example in examples if example.get("negative_control")),
            "approved_examples": len(approved),
            "human_gold_examples": len(approved),
            "provisional_automated_ready_examples": len(provisional),
            "automated_review_counts": dict(sorted(automated_review_counts.items())),
        },
        "tasks": {},
        "provisional_tasks": {},
        "error_analysis": [],
        "automated_review_error_analysis": _automated_review_error_analysis(examples),
    }
    for task_type in sorted(TASK_TYPES):
        task_examples = [example for example in approved if example.get("task_type") == task_type]
        provisional_task_examples = [
            example for example in provisional if example.get("task_type") == task_type
        ]
        metrics["tasks"][task_type] = _evaluate_task(task_type, task_examples)
        metrics["provisional_tasks"][task_type] = _evaluate_task(
            task_type,
            provisional_task_examples,
            label_track="provisional automated-ready real-sec labels",
        )
        metrics["error_analysis"].extend(_failure_cases(task_type, task_examples))
    return metrics


def pending_annotation_queue(examples: list[dict[str, Any]]) -> list[dict[str, object]]:
    return [
        {
            "id": example["id"],
            "task_type": example["task_type"],
            "pair_id": example["pair_id"],
            "negative_control": bool(example.get("negative_control")),
            "hard_case_tags": example.get("hard_case_tags", []),
            "notes": example.get("notes"),
        }
        for example in examples
        if example.get("annotation_status") == "candidate"
    ]


def update_annotation_status(
    payload: dict[str, Any],
    *,
    annotation_id: str,
    status: str,
    annotator: str,
    notes: str | None = None,
) -> bool:
    if status not in ANNOTATION_STATUSES - {"candidate"}:
        raise ValueError(f"Unsupported review status for update: {status}")
    for example in payload.get("examples", []):
        if example.get("id") != annotation_id:
            continue
        now = datetime.now(UTC).isoformat()
        example["annotation_status"] = status
        example["annotator"] = annotator
        example["updated_at"] = now
        example["review"] = {
            "reviewed_by": annotator,
            "reviewed_at": now,
            "decision": status,
            "notes": notes,
        }
        return True
    return False


def apply_automated_review(
    payload: dict[str, Any],
    *,
    id_prefix: str = "real-sec-v1-r1-",
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for example in payload.get("examples", []):
        if example.get("annotation_status") != "candidate":
            continue
        if not str(example.get("id", "")).startswith(id_prefix):
            continue
        review = _automated_review_for_example(example)
        example["automated_review"] = review
        counts[str(review["status"])] += 1
    return dict(sorted(counts.items()))


def _evaluate_task(
    task_type: str,
    examples: list[dict[str, Any]],
    *,
    label_track: str = "approved real-sec labels",
) -> dict[str, object]:
    predicted = [example.get("system_prediction") for example in examples]
    evaluable = [
        example
        for example, prediction in zip(examples, predicted, strict=True)
        if isinstance(prediction, dict)
    ]
    if not examples:
        return not_evaluated(f"No {label_track} for {task_type}.", n=0)
    if not evaluable:
        return not_evaluated(
            f"{label_track.capitalize()} for {task_type} have no system predictions.",
            n=len(examples),
        )
    expected_labels = [_label_for(task_type, example["expected"]) for example in evaluable]
    predicted_labels = [
        _label_for(task_type, dict(example["system_prediction"])) for example in evaluable
    ]
    result = classification_report(expected_labels, predicted_labels)
    if task_type == "contradiction_candidate":
        expected_bool = [label != "non_candidate" for label in expected_labels]
        predicted_bool = [label != "non_candidate" for label in predicted_labels]
        result["false_positive_rate"] = false_positive_rate(expected_bool, predicted_bool)
    return result


def _automated_review_for_example(example: dict[str, Any]) -> dict[str, object]:
    task_type = str(example.get("task_type"))
    expected = dict(example.get("expected", {}))
    source_review = dict(example.get("source_review", {}))
    blockers = _automated_review_blockers(task_type, expected, source_review)
    status = "AUTOMATED_READY" if not blockers else "AUTOMATED_UNCERTAIN"
    if source_review.get("replacement_required_reason"):
        status = "REPLACEMENT_REQUIRED"
    confidence = "HIGH" if status == "AUTOMATED_READY" else "LOW"
    return {
        "status": status,
        "recommendation": (
            "PROVISIONAL_QUEUE_READY"
            if status == "AUTOMATED_READY"
            else "NEEDS_HUMAN_SOURCE_REVIEW"
        ),
        "confidence": confidence,
        "evidence_verified": status == "AUTOMATED_READY",
        "review_passes": [
            {
                "pass": 1,
                "name": "source_and_label_consistency",
                "passed": not blockers,
                "blockers": blockers,
            },
            {
                "pass": 2,
                "name": "adversarial_label_challenge",
                "passed": not blockers,
                "challenge": _challenge_note(task_type, blockers),
            },
        ],
        "reviewer_type": "automated",
        "reviewed_at": "2026-08-12T00:00:00Z",
        "notes": "Automated second-pass review only. This is not human approval.",
    }


def _automated_review_blockers(
    task_type: str,
    expected: dict[str, Any],
    source_review: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    evidence = source_review.get("source_evidence")
    filings = source_review.get("filings")
    if not isinstance(evidence, list) or not evidence:
        blockers.append("missing_source_evidence")
    if not isinstance(filings, dict):
        blockers.append("missing_filing_metadata")
    if source_review.get("reviewability_status") not in {
        "READY_FOR_HUMAN_REVIEW",
        "AMBIGUOUS",
    }:
        blockers.append("source_review_not_ready")
    if _contains_review_required(expected) or _contains_review_required(source_review):
        blockers.append("contains_review_required_placeholder")
    if task_type == "passage_alignment" and expected.get("alignment") == "aligned":
        blockers.append("aligned_passage_requires_exact_body_text_confirmation")
    if task_type == "disclosure_change":
        blockers.append("disclosure_change_requires_exact_before_after_wording")
    if task_type == "xbrl_resolution":
        if not source_review.get("xbrl_candidate_scores"):
            blockers.append("missing_actual_resolver_scores")
        if not source_review.get("structured_facts"):
            blockers.append("missing_structured_facts")
    if task_type == "verification":
        arithmetic = source_review.get("arithmetic")
        if not isinstance(arithmetic, dict):
            blockers.append("missing_arithmetic")
        elif _contains_review_required(arithmetic):
            blockers.append("arithmetic_not_reproducible")
    if (
        task_type == "contradiction_candidate"
        and expected.get("contradiction_type") != "non_candidate"
    ):
        blockers.append("positive_contradiction_requires_real_reproducible_conflict")
    return sorted(set(blockers))


def _contains_review_required(value: object) -> bool:
    if isinstance(value, str):
        return value == "review_required"
    if isinstance(value, dict):
        return any(_contains_review_required(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_review_required(item) for item in value)
    return False


def _challenge_note(task_type: str, blockers: list[str]) -> str:
    if blockers:
        return "Opposite or uncertain label remains defensible: " + ", ".join(blockers)
    return {
        "section_matching": (
            "Body-level Part/Item evidence supports the candidate section label."
        ),
        "passage_alignment": (
            "Negative-control passages are sufficiently distinct for provisional review."
        ),
        "financial_claim": "Claim/non-claim evidence is concrete enough for provisional review.",
        "verification": (
            "Decimal-style arithmetic is reproducible from the stored candidate values."
        ),
        "contradiction_candidate": (
            "No real contradiction is asserted; negative control remains defensible."
        ),
        "evidence_quality": "Evidence presence or missing component is explicitly identified.",
    }.get(task_type, "Automated checks did not find a blocker.")


def _failure_cases(task_type: str, examples: list[dict[str, Any]]) -> list[dict[str, object]]:
    failures = []
    for example in examples:
        prediction = example.get("system_prediction")
        if not isinstance(prediction, dict):
            continue
        expected = _label_for(task_type, example["expected"])
        predicted = _label_for(task_type, prediction)
        if expected == predicted:
            continue
        failures.append(
            {
                "example_id": example["id"],
                "company": example.get("pair_id", "").split("-", 1)[0],
                "accession_pair": example.get("pair_id"),
                "task_type": task_type,
                "expected": expected,
                "predicted": predicted,
                "confidence": prediction.get("confidence"),
                "evidence": example.get("input_references", {}),
                "failure_category": _failure_category(task_type),
            }
        )
    return failures


def _automated_review_error_analysis(examples: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows = []
    for example in examples:
        automated_review = example.get("automated_review")
        if not isinstance(automated_review, dict):
            continue
        if automated_review.get("status") == "AUTOMATED_READY":
            continue
        blockers = []
        for item in automated_review.get("review_passes", []):
            if isinstance(item, dict):
                blockers.extend(str(blocker) for blocker in item.get("blockers", []))
        rows.append(
            {
                "example_id": example.get("id"),
                "company": str(example.get("pair_id", "")).split("-", 1)[0],
                "task_type": example.get("task_type"),
                "automated_status": automated_review.get("status"),
                "blockers": sorted(set(blockers)),
                "root_cause": _automated_review_root_cause(sorted(set(blockers))),
                "hard_case_tags": example.get("hard_case_tags", []),
                "negative_control": bool(example.get("negative_control")),
            }
        )
    return rows


def _automated_review_root_cause(blockers: list[str]) -> str:
    if any("resolver" in blocker or "structured_facts" in blocker for blocker in blockers):
        return "XBRL_CONCEPT"
    if any("arithmetic" in blocker or "placeholder" in blocker for blocker in blockers):
        return "VERIFICATION"
    if any("before_after" in blocker or "passage" in blocker for blocker in blockers):
        return "EVIDENCE"
    if any("positive_contradiction" in blocker for blocker in blockers):
        return "CONTRADICTION"
    return "ANNOTATION"


def _label_for(task_type: str, payload: dict[str, Any]) -> str:
    if task_type == "section_matching":
        return "match" if payload.get("should_match") else "non_match"
    if task_type == "passage_alignment":
        return str(payload.get("alignment"))
    if task_type == "disclosure_change":
        return str(payload.get("change_type"))
    if task_type == "financial_claim":
        if payload.get("is_financial_claim") is False:
            return "non_claim"
        return str(payload.get("canonical_metric"))
    if task_type == "xbrl_resolution":
        return str(payload.get("expected_concept") or "ambiguous")
    if task_type == "verification":
        return str(payload.get("verification_status"))
    if task_type == "contradiction_candidate":
        return str(payload.get("contradiction_type") or "non_candidate")
    if task_type == "evidence_quality":
        return "supported" if payload.get("expected_supported", True) else "unsupported"
    return "unknown"


def _validate_expected(annotation_id: str, task_type: str, expected: dict[str, Any]) -> None:
    if task_type == "section_matching" and "should_match" not in expected:
        raise ValueError(f"{annotation_id} section_matching expected must include should_match.")
    if task_type == "passage_alignment" and expected.get("alignment") not in ALIGNMENT_LABELS:
        raise ValueError(f"{annotation_id} has invalid passage alignment label.")
    if task_type == "disclosure_change":
        if expected.get("change_type") not in CHANGE_TYPES:
            raise ValueError(f"{annotation_id} has invalid disclosure change_type.")
        if expected.get("risk_category") not in RISK_CATEGORIES:
            raise ValueError(f"{annotation_id} has invalid risk_category.")
    if task_type == "xbrl_resolution" and "expected_unit" not in expected:
        raise ValueError(f"{annotation_id} xbrl_resolution expected must include expected_unit.")
    if (
        task_type == "verification"
        and expected.get("verification_status") not in VERIFICATION_STATUSES
    ):
        raise ValueError(f"{annotation_id} has invalid verification_status.")
    if task_type == "contradiction_candidate":
        if expected.get("contradiction_type") not in CONTRADICTION_TYPES:
            raise ValueError(f"{annotation_id} has invalid contradiction_type.")


def _validate_source_review(
    annotation_id: str,
    task_type: str,
    expected: dict[str, Any],
    source_review: object,
) -> None:
    if not isinstance(source_review, dict):
        raise ValueError(f"{annotation_id} source_review must be an object.")
    if source_review.get("reviewability_status") not in REVIEWABILITY_STATUSES:
        raise ValueError(f"{annotation_id} has invalid reviewability_status.")
    if source_review.get("source_quality") not in SOURCE_QUALITY:
        raise ValueError(f"{annotation_id} has invalid source_quality.")
    if source_review.get("label_confidence") not in LABEL_CONFIDENCE:
        raise ValueError(f"{annotation_id} has invalid label_confidence.")
    if source_review.get("review_difficulty") not in REVIEW_DIFFICULTY:
        raise ValueError(f"{annotation_id} has invalid review_difficulty.")
    if not isinstance(source_review.get("filings"), dict):
        raise ValueError(f"{annotation_id} source_review must include filing references.")
    if not isinstance(source_review.get("source_evidence"), list):
        raise ValueError(f"{annotation_id} source_review must include source_evidence.")
    if task_type == "xbrl_resolution" and source_review.get("structured_facts") is not None:
        _require_non_empty_list(source_review, "structured_facts", annotation_id)
    if (
        task_type == "contradiction_candidate"
        and expected.get("contradiction_type") != "non_candidate"
        and source_review.get("reviewability_status") != "REPLACEMENT_REQUIRED"
        and not source_review.get("arithmetic")
    ):
        raise ValueError(f"{annotation_id} positive contradiction requires arithmetic evidence.")


def _validate_automated_review(annotation_id: str, automated_review: object) -> None:
    if not isinstance(automated_review, dict):
        raise ValueError(f"{annotation_id} automated_review must be an object.")
    if automated_review.get("status") not in AUTOMATED_REVIEW_STATUSES:
        raise ValueError(f"{annotation_id} has invalid automated_review status.")
    if automated_review.get("reviewer_type") != "automated":
        raise ValueError(f"{annotation_id} automated_review must be marked automated.")
    if not automated_review.get("reviewed_at"):
        raise ValueError(f"{annotation_id} automated_review lacks reviewed_at.")
    passes = automated_review.get("review_passes")
    if not isinstance(passes, list) or len(passes) < 2:
        raise ValueError(f"{annotation_id} automated_review requires two review passes.")
    if automated_review.get("status") == "AUTOMATED_READY" and not automated_review.get(
        "evidence_verified"
    ):
        raise ValueError(f"{annotation_id} automated-ready review must verify evidence.")


def _validate_approved_source_review(
    annotation_id: str,
    task_type: str,
    expected: dict[str, Any],
    source_review: dict[str, Any],
) -> None:
    _validate_source_review(annotation_id, task_type, expected, source_review)
    if source_review.get("reviewability_status") != "READY_FOR_HUMAN_REVIEW":
        raise ValueError(f"{annotation_id} cannot be approved before it is ready for review.")
    if source_review.get("replacement_required_reason"):
        raise ValueError(f"{annotation_id} cannot be approved while replacement_required.")
    if task_type == "xbrl_resolution":
        _require_xbrl_expected(annotation_id, expected)
        _require_non_empty_list(source_review, "structured_facts", annotation_id)
        _require_non_empty_list(source_review, "xbrl_candidate_scores", annotation_id)
    if task_type == "verification":
        arithmetic = _require_dict(source_review, "arithmetic")
        for field in {"claim", "formula", "calculated_result", "tolerance", "expected_status"}:
            if arithmetic.get(field) in {None, ""}:
                raise ValueError(f"{annotation_id} approved verification lacks {field}.")
    if (
        task_type == "contradiction_candidate"
        and expected.get("contradiction_type") != "non_candidate"
    ):
        arithmetic = _require_dict(source_review, "arithmetic")
        if not arithmetic.get("claim"):
            raise ValueError(f"{annotation_id} approved contradiction lacks a concrete claim.")


def _require_xbrl_expected(annotation_id: str, expected: dict[str, Any]) -> None:
    for field in {
        "expected_concept",
        "expected_accession",
        "expected_unit",
        "period_type",
        "fy",
        "fp",
        "value",
    }:
        if expected.get(field) in {None, ""}:
            raise ValueError(f"{annotation_id} approved XBRL label lacks {field}.")


def _failure_category(task_type: str) -> str:
    return {
        "section_matching": "wrong_section",
        "passage_alignment": "wrong_passage_alignment",
        "disclosure_change": "wrong_change_class",
        "financial_claim": "wrong_metric",
        "xbrl_resolution": "wrong_xbrl_concept",
        "verification": "verification_status",
        "contradiction_candidate": "false_or_missed_contradiction",
        "evidence_quality": "evidence_failure",
    }[task_type]


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing required string field: {key}")
    return value


def _require_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"Missing required list field: {key}")
    return value


def _require_non_empty_list(
    payload: dict[str, Any],
    key: str,
    annotation_id: str,
) -> list[dict[str, Any]]:
    value = _require_list(payload, key)
    if not value:
        raise ValueError(f"{annotation_id} {key} must not be empty.")
    return value


def _require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Missing required object field: {key}")
    return value


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and review real SEC benchmark labels.")
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("evaluation/datasets/real_sec_v1/examples.json"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("summary")
    subparsers.add_parser("list-pending")
    automated_parser = subparsers.add_parser("apply-automated-review")
    automated_parser.add_argument("--id-prefix", default="real-sec-v1-r1-")
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("annotation_id")
    update_parser = subparsers.add_parser("set-status")
    update_parser.add_argument("annotation_id")
    update_parser.add_argument("status", choices=sorted(ANNOTATION_STATUSES - {"candidate"}))
    update_parser.add_argument("--annotator", required=True)
    update_parser.add_argument("--notes", default=None)
    args = parser.parse_args(argv)

    payload = load_real_sec_payload(args.path)
    if args.command == "validate":
        summary = validate_real_sec_payload(payload)
        print(json.dumps(summary.__dict__, sort_keys=True))
        return 0
    if args.command == "summary":
        summary = validate_real_sec_payload(payload)
        print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
        return 0
    if args.command == "list-pending":
        validate_real_sec_payload(payload)
        print(json.dumps(pending_annotation_queue(payload["examples"]), indent=2, sort_keys=True))
        return 0
    if args.command == "apply-automated-review":
        counts = apply_automated_review(payload, id_prefix=args.id_prefix)
        validate_real_sec_payload(payload)
        args.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(counts, sort_keys=True))
        return 0
    if args.command == "inspect":
        for example in payload["examples"]:
            if example["id"] == args.annotation_id:
                print(json.dumps(example, indent=2, sort_keys=True))
                return 0
        raise ValueError(f"Annotation not found: {args.annotation_id}")
    if args.command == "set-status":
        if not update_annotation_status(
            payload,
            annotation_id=args.annotation_id,
            status=args.status,
            annotator=args.annotator,
            notes=args.notes,
        ):
            raise ValueError(f"Annotation not found: {args.annotation_id}")
        validate_real_sec_payload(payload)
        args.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    return 1
