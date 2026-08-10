from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.ai.contradictions import (
    ContradictionClassifierInput,
    DeterministicFakeContradictionClassifier,
)
from app.core.config import Settings
from app.db.models import ClaimVerification, FinancialClaim
from app.services.contradiction_analysis_service import (
    MagnitudeContradictionDetector,
    NumericalContradictionDetector,
)


def test_numerical_detector_flags_direction_contradiction_with_complete_evidence() -> None:
    claim = _claim(
        claim_text="Revenue decreased 12% compared with the same period last year.",
        direction="decrease",
        reported_change=Decimal("-12.0"),
    )
    verification = _verification(
        financial_claim_id=claim.id,
        verification_status="contradicted",
        percentage_change=Decimal("12.0000"),
        difference=Decimal("24.0000"),
    )

    result = NumericalContradictionDetector(Settings()).detect(uuid.uuid4(), claim, verification)

    assert result is not None
    finding, evidence = result
    assert finding.contradiction_type == "direction_contradiction"
    assert finding.status == "candidate"
    assert finding.severity == "high"
    assert finding.measured_direction == "increase"
    assert "RULE_NUMERIC_DIRECTION_MISMATCH" in finding.rule_ids
    assert any(item.evidence_role == "primary" for item in evidence)


def test_magnitude_detector_flags_significant_wording_for_small_margin_change() -> None:
    claim = _claim(
        claim_text="Gross margin improved significantly compared with the prior quarter.",
        canonical_metric_name="gross_margin",
        direction="increase",
    )
    verification = _verification(
        financial_claim_id=claim.id,
        verification_status="verified",
        percentage_point_change=Decimal("0.3000"),
    )

    result = MagnitudeContradictionDetector(Settings()).detect(uuid.uuid4(), claim, verification)

    assert result is not None
    finding, _ = result
    assert finding.contradiction_type == "magnitude_overstatement"
    assert finding.qualifier == "significantly"
    assert finding.detection_method == "rule_based"
    assert finding.supporting_evidence["policy"]["unit"] == "percentage_points"


def test_magnitude_detector_flags_slight_wording_for_large_decline() -> None:
    claim = _claim(
        claim_text="Revenue declined slightly compared with the same period last year.",
        direction="decrease",
    )
    verification = _verification(
        financial_claim_id=claim.id,
        verification_status="approximately_verified",
        percentage_change=Decimal("-24.0000"),
    )

    result = MagnitudeContradictionDetector(Settings()).detect(uuid.uuid4(), claim, verification)

    assert result is not None
    finding, _ = result
    assert finding.contradiction_type == "magnitude_understatement"
    assert finding.severity == "medium"
    assert "RULE_SLIGHT_LARGE_MOVEMENT" in finding.rule_ids


@pytest.mark.asyncio
async def test_fake_contradiction_classifier_is_schema_strict_and_low_confidence() -> None:
    output = await DeterministicFakeContradictionClassifier().classify(
        ContradictionClassifierInput(
            narrative_claim="Demand remained strong.",
            deterministic_signals={
                "is_candidate": True,
                "contradiction_type": "narrative_cross_section_inconsistency",
            },
            allowed_labels=["narrative_cross_section_inconsistency"],
        )
    )

    assert output.is_candidate is True
    assert output.contradiction_type == "narrative_cross_section_inconsistency"
    assert output.severity == "low"
    assert output.confidence == 0.50


def _claim(
    *,
    claim_text: str,
    direction: str | None,
    canonical_metric_name: str = "revenue",
    reported_change: Decimal | None = None,
) -> FinancialClaim:
    return FinancialClaim(
        id=uuid.uuid4(),
        filing_id=uuid.uuid4(),
        comparison_id=uuid.uuid4(),
        disclosure_change_id=None,
        source_section_id=uuid.uuid4(),
        source_passage_id=uuid.uuid4(),
        claim_text=claim_text,
        canonical_metric_name=canonical_metric_name,
        metric_definition_id=uuid.uuid4(),
        claim_type="percentage_change",
        direction=direction,
        reported_value=None,
        reported_unit=None,
        reported_change=reported_change,
        reported_change_unit="percent" if reported_change is not None else None,
        comparison_basis="same_period_prior_year",
        comparison_text="compared with the same period last year",
        qualifiers={},
        extraction_confidence=Decimal("0.9500"),
        extraction_method="deterministic",
        original_model_output={},
        review_status="pending",
        reviewer_edits={},
    )


def _verification(
    *,
    financial_claim_id: uuid.UUID,
    verification_status: str,
    percentage_change: Decimal | None = None,
    percentage_point_change: Decimal | None = None,
    difference: Decimal | None = None,
) -> ClaimVerification:
    return ClaimVerification(
        id=uuid.uuid4(),
        financial_claim_id=financial_claim_id,
        current_xbrl_fact_id=uuid.uuid4(),
        comparison_xbrl_fact_id=uuid.uuid4(),
        verification_status=verification_status,
        current_value=Decimal("112000000.000000"),
        comparison_value=Decimal("100000000.000000"),
        absolute_change=Decimal("12000000.000000"),
        percentage_change=percentage_change,
        percentage_point_change=percentage_point_change,
        reported_change=None,
        reported_vs_calculated_difference=difference,
        calculation_type="percentage_change",
        formula="((current_value - comparison_value) / comparison_value) * 100",
        calculation_inputs={},
        calculation_output={},
        tolerance_used=Decimal("0.250000"),
        verification_reason="Fixture verification.",
        confidence=Decimal("0.9900"),
        verification_version="phase4-v1",
    )
