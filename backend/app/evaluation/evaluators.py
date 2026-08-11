from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ai.semantic_change import (
    ChangeClassificationRequest,
    DeterministicFakeChangeClassifier,
)
from app.evaluation.datasets import DatasetManifest, load_dataset_examples
from app.evaluation.metrics import (
    classification_report,
    expected_calibration_error,
    false_positive_rate,
    metric,
    no_data,
    not_evaluated,
    ranking_metrics,
)
from app.services.comparison_utils import content_hash, deterministic_signals
from app.services.financial_number_parser import parse_financial_number


@dataclass(frozen=True)
class SuiteResult:
    suite: str
    dataset_name: str
    dataset_version: str
    example_count: int
    metrics: dict[str, object]
    status: str = "completed"
    errors: list[dict[str, object]] | None = None


async def evaluate_manifest(manifest: DatasetManifest) -> SuiteResult:
    examples = load_dataset_examples(manifest)
    if manifest.task == "retrieval":
        metrics = _evaluate_retrieval(examples)
    elif manifest.task == "phase3_disclosure_change":
        metrics = await _evaluate_phase3(examples)
    elif manifest.task == "phase4_financial_verification":
        metrics = _evaluate_phase4(examples)
    elif manifest.task == "phase4_number_normalization":
        metrics = _evaluate_number_normalization(examples)
    elif manifest.task == "phase5_contradiction":
        metrics = _evaluate_phase5(examples)
    elif manifest.task == "evidence_quality":
        metrics = _evaluate_evidence(examples)
    else:
        metrics = {"suite": not_evaluated(f"No evaluator registered for {manifest.task}.")}
    return SuiteResult(
        suite=manifest.task,
        dataset_name=manifest.dataset_name,
        dataset_version=manifest.dataset_version,
        example_count=len(examples),
        metrics=metrics,
        errors=[],
    )


def _evaluate_retrieval(examples: list[dict[str, Any]]) -> dict[str, object]:
    systems = sorted({system for example in examples for system in example.get("rankings", {})})
    return {
        "systems": {
            system: ranking_metrics(examples, system_name=system, ks=(1, 5, 10))
            for system in systems
        },
        "ablation_systems": systems,
    }


async def _evaluate_phase3(examples: list[dict[str, Any]]) -> dict[str, object]:
    classifier = DeterministicFakeChangeClassifier()
    expected_change = []
    predicted_change = []
    expected_risk = []
    predicted_risk = []
    confidence_rows = []
    for example in examples:
        previous = example.get("previous_text")
        current = example.get("current_text")
        result = await classifier.classify(
            ChangeClassificationRequest(
                previous_text=previous,
                current_text=current,
                deterministic_signals=deterministic_signals(previous, current),
                section_metadata={},
                allowed_labels=[
                    "added",
                    "removed",
                    "strengthened",
                    "weakened",
                    "no_material_change",
                ],
            )
        )
        expected_change.append(str(example["expected_change_type"]))
        predicted_change.append(result.change_type)
        expected_risk.append(str(example["expected_risk_category"]))
        predicted_risk.append(result.risk_category)
        confidence_rows.append(
            {
                "confidence": result.confidence,
                "correct": result.change_type == example["expected_change_type"],
            }
        )
    return {
        "change_detection": classification_report(expected_change, predicted_change),
        "risk_category": classification_report(expected_risk, predicted_risk),
        "section_matching": not_evaluated(
            "Phase 3 fixture has no section-match labels.",
            n=len(examples),
        ),
        "passage_alignment": not_evaluated(
            "Phase 3 fixture has no passage-alignment labels.",
            n=len(examples),
        ),
        "materiality": not_evaluated(
            "Phase 3 fixture has no trusted numeric materiality labels.",
            n=len(examples),
        ),
        "calibration": {
            "ece": expected_calibration_error(confidence_rows),
        },
    }


def _evaluate_phase4(examples: list[dict[str, Any]]) -> dict[str, object]:
    status_examples = [example for example in examples if "expected_status" in example]
    period_examples = [
        example
        for example in examples
        if "expected_period" in example or "expected_basis" in example
    ]
    return {
        "claim_extraction": {
            "canonical_metric_accuracy": not_evaluated(
                "Current Phase 4 fixture has gold labels but no persisted extractor predictions.",
                n=len(examples),
            ),
            "claim_type_accuracy": not_evaluated(
                "Current Phase 4 fixture does not include predicted claim types.",
                n=len(examples),
            ),
        },
        "xbrl_resolution": {
            "concept_selection_accuracy": not_evaluated(
                "Current Phase 4 fixture does not include predicted fact selections.",
                n=len(examples),
            ),
            "period_resolution_accuracy": not_evaluated(
                "Current Phase 4 fixture has period labels but no predicted periods.",
                n=len(period_examples),
            ),
            "unit_selection_accuracy": not_evaluated(
                "Current Phase 4 fixture has no predicted unit-selection output.",
                n=len(examples),
            ),
        },
        "verification_status": not_evaluated(
            "Current Phase 4 fixture has expected statuses but no offline verifier predictions.",
            n=len(status_examples),
        ),
        "unsafe_period_match_rate": not_evaluated(
            "Unsafe period matching requires verifier predictions.",
            n=len(period_examples),
        ),
        "unsafe_unit_acceptance_rate": not_evaluated(
            "Unsafe unit acceptance requires verifier predictions.",
            n=len(examples),
        ),
        "deterministic_calculation": {
            "reproducible_calculation_rate": not_evaluated(
                "Fixture does not include selected input facts and expected calculations.",
                n=len(examples),
            )
        },
    }


def _evaluate_number_normalization(examples: list[dict[str, Any]]) -> dict[str, object]:
    expected_values = []
    actual_values = []
    expected_units = []
    actual_units = []
    failures = []
    for example in examples:
        parsed = parse_financial_number(str(example["text"]))
        expected_values.append(str(Decimal(str(example["expected_value"]))))
        expected_units.append(str(example["expected_unit"]))
        if parsed is None:
            actual_values.append("<missing>")
            actual_units.append("<missing>")
            failures.append({"id": example["id"], "error": "number_not_parsed"})
        else:
            actual_values.append(str(parsed.value))
            actual_units.append(parsed.unit)
    return {
        "normalized_value_accuracy": classification_report(expected_values, actual_values),
        "unit_accuracy": classification_report(expected_units, actual_units),
        "failures": failures,
    }


def _evaluate_phase5(examples: list[dict[str, Any]]) -> dict[str, object]:
    expected_type = [str(example["expected_type"]) for example in examples]
    predicted_type = [_predict_contradiction_type(example) for example in examples]
    expected_candidate = [True for _example in examples]
    predicted_candidate = [item is not None for item in predicted_type]
    normalized_predicted = [item or "non_candidate" for item in predicted_type]
    return {
        "contradiction_type": classification_report(expected_type, normalized_predicted),
        "candidate_detection": classification_report(
            [str(item) for item in expected_candidate],
            [str(item) for item in predicted_candidate],
        ),
        "false_positive_rate": false_positive_rate(expected_candidate, predicted_candidate),
        "false_positives_by_type": {},
        "numerical_subset": _numerical_subset_metrics(examples, predicted_type),
    }


def _evaluate_evidence(examples: list[dict[str, Any]]) -> dict[str, object]:
    eligible = [example for example in examples if example.get("eligible", True)]
    completeness = []
    citation_resolution = []
    source_hash = []
    calculation = []
    primary = []
    backed = []
    unsupported = []
    errors = []
    for example in eligible:
        evidence = dict(example.get("evidence", {}))
        has_primary = bool(evidence.get("primary_source_text"))
        hash_ok = _hash_matches(evidence.get("primary_source_text"), evidence.get("source_hash"))
        calc_ok = _calculation_ok(evidence.get("calculation"))
        complete = has_primary and bool(evidence.get("citation")) and hash_ok
        if example.get("requires_calculation"):
            complete = complete and calc_ok
        expected_supported = bool(example.get("expected_supported"))
        primary.append(has_primary)
        source_hash.append(hash_ok)
        citation_resolution.append(bool(evidence.get("citation")))
        calculation.append(calc_ok if example.get("requires_calculation") else True)
        completeness.append(complete)
        backed.append(complete if expected_supported else False)
        unsupported.append(expected_supported and not complete)
        if expected_supported and not complete:
            errors.append({"id": example["id"], "error": "unsupported_finding"})
    return {
        "evidence_completeness_rate": _bool_rate(completeness),
        "citation_resolution_rate": _bool_rate(citation_resolution),
        "source_hash_validity_rate": _bool_rate(source_hash),
        "calculation_evidence_rate": _bool_rate(calculation),
        "finding_with_primary_evidence_rate": _bool_rate(primary),
        "evidence_backed_finding_rate": _bool_rate(backed),
        "unsupported_finding_rate": _bool_rate(unsupported),
        "errors": errors,
    }


def human_review_metrics(rows: list[dict[str, Any]]) -> dict[str, object]:
    if not rows:
        return {"review_outcomes": no_data("No human review outcome dataset is available.")}
    statuses = [str(row["status"]) for row in rows]
    counts = {status: statuses.count(status) for status in sorted(set(statuses))}
    return {"review_outcomes": counts, "review_count": metric(len(rows), n=len(rows))}


def workflow_operational_metrics(rows: list[dict[str, Any]]) -> dict[str, object]:
    if not rows:
        return {
            "workflow_reliability": no_data(
                "No workflow event benchmark dataset is available."
            )
        }
    completed = sum(1 for row in rows if row.get("status") == "completed")
    return {"successful_run_rate": metric(completed / len(rows), n=len(rows))}


def _predict_contradiction_type(example: dict[str, Any]) -> str | None:
    evidence = dict(example.get("structured_evidence", {}))
    narrative = str(example.get("narrative", "")).lower()
    if {"reported_change", "calculated_change"} <= set(evidence) or {
        "reported_value",
        "calculated_value",
    } <= set(evidence):
        return "numerical_claim_contradiction"
    if "available_evidence" in evidence:
        return "unsupported_qualitative_claim"
    if "sections" in evidence:
        return "narrative_cross_section_inconsistency"
    if "periods" in evidence:
        return "temporal_narrative_inconsistency"
    try:
        change = abs(Decimal(str(evidence.get("calculated_change", "0")).replace("pp", "")))
    except InvalidOperation:
        change = Decimal("0")
    if any(
        term in narrative
        for term in ("significant", "substantial", "material", "strong", "meaningful")
    ):
        return "magnitude_overstatement" if change < Decimal("1") else None
    if any(term in narrative for term in ("slight", "modest", "marginal", "limited", "small")):
        return "magnitude_understatement" if change >= Decimal("15") else None
    return None


def _numerical_subset_metrics(
    examples: list[dict[str, Any]],
    predicted_type: list[str | None],
) -> dict[str, object]:
    indexes = [
        index
        for index, example in enumerate(examples)
        if example["expected_type"] == "numerical_claim_contradiction"
    ]
    if not indexes:
        return {"status": "not_evaluated", "reason": "No numerical examples."}
    expected = ["numerical_claim_contradiction" for _ in indexes]
    predicted = [predicted_type[index] or "non_candidate" for index in indexes]
    return {
        "numerical_contradiction_precision_recall": classification_report(
            expected,
            predicted,
        ),
        "direction_mismatch_accuracy": not_evaluated(
            "Fixture does not separate direction-mismatch labels from value-mismatch labels.",
            n=len(indexes),
        ),
        "reported_vs_calculated_mismatch_accuracy": metric(
            sum(1 for value in predicted if value == "numerical_claim_contradiction")
            / len(indexes),
            n=len(indexes),
        ),
    }


def _hash_matches(text: object, expected_hash: object) -> bool:
    if not isinstance(text, str) or not isinstance(expected_hash, str):
        return False
    return content_hash(text) == expected_hash


def _calculation_ok(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    try:
        left = Decimal(str(payload["left"]))
        right = Decimal(str(payload["right"]))
        operator = payload["operator"]
        expected = Decimal(str(payload["expected"]))
    except (KeyError, InvalidOperation):
        return False
    if operator == "-":
        actual = left - right
    elif operator == "+":
        actual = left + right
    elif operator == "/":
        if right == 0:
            return False
        actual = left / right
    else:
        return False
    return actual == expected


def _bool_rate(values: list[bool]) -> dict[str, object]:
    if not values:
        return no_data("No eligible examples.")
    return metric(sum(1 for value in values if value) / len(values), n=len(values))
