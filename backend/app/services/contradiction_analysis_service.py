from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.contradictions import (
    ContradictionClassifierProvider,
    create_contradiction_classifier,
)
from app.core.config import Settings
from app.db.models import (
    ClaimVerification,
    ContradictionEvidence,
    ContradictionFinding,
    DisclosureChange,
    FilingComparison,
    FilingSection,
    FinancialClaim,
)
from app.repositories.comparison_repository import ComparisonRepository
from app.repositories.contradiction_repository import ContradictionRepository
from app.repositories.financial_repository import FinancialRepository

RULE_VERSION = "phase5-v1"
RULE_NUMERIC_DIRECTION_MISMATCH = "RULE_NUMERIC_DIRECTION_MISMATCH"
RULE_NUMERIC_REPORTED_CHANGE_MISMATCH = "RULE_NUMERIC_REPORTED_CHANGE_MISMATCH"
RULE_QUALIFIER_SIGNIFICANT_LOW_CHANGE = "RULE_QUALIFIER_SIGNIFICANT_LOW_CHANGE"
RULE_SLIGHT_LARGE_MOVEMENT = "RULE_SLIGHT_LARGE_MOVEMENT"
RULE_STRONG_LIQUIDITY_MIXED_EVIDENCE = "RULE_STRONG_LIQUIDITY_MIXED_EVIDENCE"
RULE_TEMPORAL_EXPECTATION_CONFLICT = "RULE_TEMPORAL_EXPECTATION_CONFLICT"
RULE_CROSS_SECTION_POLARITY_CONFLICT = "RULE_CROSS_SECTION_POLARITY_CONFLICT"

STRENGTH_QUALIFIERS = {
    "significant",
    "significantly",
    "substantial",
    "substantially",
    "material",
    "materially",
    "strong",
    "strongly",
    "exceptional",
    "exceptionally",
    "meaningful",
    "meaningfully",
}
WEAK_QUALIFIERS = {
    "slight",
    "slightly",
    "modest",
    "modestly",
    "minor",
    "marginal",
    "limited",
    "small",
}
UNCERTAINTY_QUALIFIERS = {
    "may",
    "might",
    "could",
    "subject to",
    "uncertain",
    "potential",
    "possible",
}
CERTAINTY_QUALIFIERS = {"will", "expect", "confident", "certain", "assured"}
POSITIVE_TERMS = {"strong", "improve", "improved", "growth", "higher", "recover", "sufficient"}
NEGATIVE_TERMS = {"slowdown", "decline", "declined", "weak", "weakened", "deteriorated", "depend"}
SHARED_TOPIC_TERMS = {
    "demand",
    "orders",
    "liquidity",
    "financing",
    "revenue",
    "customer",
    "enterprise",
    "concentration",
}


@dataclass(frozen=True)
class MagnitudePolicy:
    metric_name: str
    unit: str
    small: Decimal
    large: Decimal


class ContradictionAnalysisService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        classifier: ContradictionClassifierProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.repo = ContradictionRepository(session)
        self.financial_repo = FinancialRepository(session)
        self.comparisons = ComparisonRepository(session)
        self.classifier = classifier or create_contradiction_classifier(
            settings.contradiction_classifier_provider
        )
        self.numerical = NumericalContradictionDetector(settings)
        self.magnitude = MagnitudeContradictionDetector(settings)
        self.temporal = TemporalNarrativeInconsistencyDetector(settings)
        self.cross_section = CrossSectionNarrativeConsistencyService(session, settings)

    async def analyze_comparison(self, comparison_id: uuid.UUID) -> dict[str, int]:
        lock_acquired = await self.repo.try_acquire_analysis_lock(comparison_id)
        if not lock_acquired:
            return {"status": 0, "created": 0, "updated": 0, "candidates": 0}
        try:
            comparison = await self.comparisons.get_comparison(comparison_id)
            if comparison is None:
                raise ValueError(f"Comparison not found: {comparison_id}")
            created = 0
            updated = 0
            candidates = await self._generate_candidates(comparison)
            for candidate in candidates:
                finding, evidence = candidate
                stored, was_created = await self.repo.upsert_finding(finding, evidence)
                finding.id = stored.id
                if was_created:
                    created += 1
                else:
                    updated += 1
            await self.session.commit()
            return {
                "status": 1,
                "created": created,
                "updated": updated,
                "candidates": len(candidates),
            }
        except Exception:
            await self.session.rollback()
            raise
        finally:
            await self.repo.release_analysis_lock(comparison_id)

    async def _generate_candidates(
        self,
        comparison: FilingComparison,
    ) -> list[tuple[ContradictionFinding, list[ContradictionEvidence]]]:
        candidates: list[tuple[ContradictionFinding, list[ContradictionEvidence]]] = []
        pairs = await self.repo.list_claim_verification_pairs(comparison.id)
        for claim, verification in pairs:
            numerical = self.numerical.detect(comparison.company_id, claim, verification)
            if numerical is not None:
                candidates.append(numerical)
                continue
            magnitude = self.magnitude.detect(comparison.company_id, claim, verification)
            if magnitude is not None:
                candidates.append(magnitude)

        changes = await self.comparisons.list_changes(comparison.id, limit=500)
        for change in changes:
            temporal = self.temporal.detect(comparison.company_id, change)
            if temporal is not None:
                candidates.append(temporal)

        candidates.extend(await self.cross_section.detect(comparison))
        return candidates


class NumericalContradictionDetector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def detect(
        self,
        company_id: uuid.UUID,
        claim: FinancialClaim,
        verification: ClaimVerification,
    ) -> tuple[ContradictionFinding, list[ContradictionEvidence]] | None:
        if verification.verification_status != "contradicted":
            return None
        calculated_change = _calculated_change(verification)
        measured_direction = _direction_from_change(calculated_change)
        rule_ids = [RULE_NUMERIC_REPORTED_CHANGE_MISMATCH]
        contradiction_type = "numerical_claim_contradiction"
        if claim.direction and measured_direction and claim.direction != measured_direction:
            rule_ids.insert(0, RULE_NUMERIC_DIRECTION_MISMATCH)
            contradiction_type = "direction_contradiction"
        status = _numerical_status(claim, verification)
        severity, severity_components = _severity(
            contradiction_type=contradiction_type,
            verification=verification,
            calculated_change=calculated_change,
            evidence_complete=status != "insufficient_evidence",
        )
        confidence, confidence_components = _confidence(
            claim=claim,
            verification=verification,
            rule_confidence=Decimal("0.98"),
            semantic_confidence=None,
        )
        finding = ContradictionFinding(
            company_id=company_id,
            comparison_id=claim.comparison_id,
            financial_claim_id=claim.id,
            claim_verification_id=verification.id,
            disclosure_change_id=claim.disclosure_change_id,
            contradiction_type=contradiction_type,
            status=status,
            risk_category=None,
            severity=severity,
            confidence=confidence,
            narrative_claim=claim.claim_text,
            narrative_direction=claim.direction,
            measured_direction=measured_direction,
            reported_value=claim.reported_change or claim.reported_value,
            calculated_value=verification.current_value,
            calculated_change=calculated_change,
            difference=verification.reported_vs_calculated_difference,
            qualifier=_first_qualifier(claim.claim_text),
            finding_title="Potential numerical inconsistency requires review",
            finding_summary=(
                "A narrative financial claim does not match the deterministic "
                "calculation from selected XBRL facts."
            ),
            finding_explanation=(
                "Phase 4 verification marked this claim as contradicted. The finding "
                "is a review candidate backed by reproducible arithmetic, selected "
                "facts, and the original narrative claim."
            ),
            limitations=(
                []
                if status != "insufficient_evidence"
                else _missing_numerical_evidence(claim, verification)
            ),
            deterministic_evidence=_verification_payload(verification),
            supporting_evidence={"claim": _claim_payload(claim)},
            severity_components=severity_components,
            confidence_components=confidence_components,
            detection_method="deterministic",
            rule_ids=rule_ids,
            original_model_output=None,
            original_system_finding={},
            finding_fingerprint=_fingerprint(
                company_id,
                claim.comparison_id,
                contradiction_type,
                [claim.id, verification.id],
                RULE_VERSION,
            ),
            review_status="pending",
        )
        finding.original_system_finding = _system_snapshot(finding)
        return finding, _numerical_evidence(finding, claim, verification)


class MagnitudeContradictionDetector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def detect(
        self,
        company_id: uuid.UUID,
        claim: FinancialClaim,
        verification: ClaimVerification,
    ) -> tuple[ContradictionFinding, list[ContradictionEvidence]] | None:
        if verification.verification_status not in {"verified", "approximately_verified"}:
            return None
        qualifier = _first_qualifier(claim.claim_text)
        if qualifier is None:
            return None
        calculated_change = _calculated_change(verification)
        if calculated_change is None:
            return None
        policy = _policy_for(self.settings, claim.canonical_metric_name, verification)
        abs_change = abs(calculated_change)
        if qualifier in STRENGTH_QUALIFIERS and abs_change <= policy.small:
            contradiction_type = "magnitude_overstatement"
            rule_id = RULE_QUALIFIER_SIGNIFICANT_LOW_CHANGE
            summary = "Qualitative magnitude may be overstated by available structured evidence."
        elif qualifier in WEAK_QUALIFIERS and abs_change >= policy.large:
            contradiction_type = "magnitude_understatement"
            rule_id = RULE_SLIGHT_LARGE_MOVEMENT
            summary = "Qualitative magnitude may understate the measured numerical movement."
        elif (
            qualifier in {"strong", "strongly", "exceptional", "exceptionally"}
            and claim.canonical_metric_name == "cash_and_cash_equivalents"
        ):
            contradiction_type = "unsupported_qualitative_claim"
            rule_id = RULE_STRONG_LIQUIDITY_MIXED_EVIDENCE
            summary = "Qualitative strength is not clearly supported by available evidence."
        else:
            return None
        severity, severity_components = _severity(
            contradiction_type=contradiction_type,
            verification=verification,
            calculated_change=calculated_change,
            evidence_complete=True,
        )
        confidence, confidence_components = _confidence(
            claim=claim,
            verification=verification,
            rule_confidence=Decimal("0.72"),
            semantic_confidence=None,
        )
        finding = ContradictionFinding(
            company_id=company_id,
            comparison_id=claim.comparison_id,
            financial_claim_id=claim.id,
            claim_verification_id=verification.id,
            disclosure_change_id=claim.disclosure_change_id,
            contradiction_type=contradiction_type,
            status="candidate",
            risk_category=None,
            severity=severity,
            confidence=confidence,
            narrative_claim=claim.claim_text,
            narrative_direction=claim.direction,
            measured_direction=_direction_from_change(calculated_change),
            reported_value=claim.reported_change or claim.reported_value,
            calculated_value=verification.current_value,
            calculated_change=calculated_change,
            difference=verification.reported_vs_calculated_difference,
            qualifier=qualifier,
            finding_title="Potential magnitude wording issue requires review",
            finding_summary=summary,
            finding_explanation=(
                "The direction is supported by Phase 4 verification, but the wording "
                "uses a qualitative magnitude term that should be reviewed against "
                "the configured metric-specific policy."
            ),
            limitations=[
                "Magnitude thresholds are system heuristics for review routing, "
                "not legal materiality conclusions."
            ],
            deterministic_evidence=_verification_payload(verification),
            supporting_evidence={
                "claim": _claim_payload(claim),
                "policy": {
                    "version": self.settings.contradiction_policy_version,
                    "metric": policy.metric_name,
                    "unit": policy.unit,
                    "small": str(policy.small),
                    "large": str(policy.large),
                },
            },
            severity_components=severity_components,
            confidence_components=confidence_components,
            detection_method="rule_based",
            rule_ids=[rule_id],
            original_model_output=None,
            original_system_finding={},
            finding_fingerprint=_fingerprint(
                company_id,
                claim.comparison_id,
                contradiction_type,
                [claim.id, verification.id, qualifier],
                self.settings.contradiction_policy_version,
            ),
            review_status="pending",
        )
        finding.original_system_finding = _system_snapshot(finding)
        return finding, _numerical_evidence(finding, claim, verification)


class TemporalNarrativeInconsistencyDetector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def detect(
        self,
        company_id: uuid.UUID,
        change: DisclosureChange,
    ) -> tuple[ContradictionFinding, list[ContradictionEvidence]] | None:
        previous = change.previous_text or ""
        current = change.current_text or ""
        if not _temporal_conflict(previous, current):
            return None
        confidence = _quantize(Decimal(str(min(0.85, max(0.45, change.confidence)))))
        finding = ContradictionFinding(
            company_id=company_id,
            comparison_id=change.comparison_id,
            disclosure_change_id=change.id,
            contradiction_type="temporal_narrative_inconsistency",
            status="candidate",
            risk_category=change.risk_category,
            severity="medium" if change.materiality_score >= 0.65 else "low",
            confidence=confidence,
            narrative_claim=current,
            narrative_direction=None,
            measured_direction=None,
            reported_value=None,
            calculated_value=None,
            calculated_change=None,
            difference=None,
            qualifier=_first_qualifier(current),
            finding_title="Current disclosure differs from prior-period expectation",
            finding_summary=(
                "Current disclosure differs materially from the prior-period expectation."
            ),
            finding_explanation=(
                "This is a temporal review candidate. Changing expectations can be valid; "
                "the finding only highlights that the current disclosure appears to conflict "
                "with a prior stated expectation."
            ),
            limitations=["A change in expectations is not itself misconduct."],
            deterministic_evidence={"change_id": str(change.id), "change_type": change.change_type},
            supporting_evidence=change.supporting_evidence,
            severity_components={
                "materiality_score": change.materiality_score,
                "risk_category": change.risk_category,
            },
            confidence_components={
                "semantic_change_confidence": change.confidence,
                "rule_confidence": "0.80",
            },
            detection_method="rule_based",
            rule_ids=[RULE_TEMPORAL_EXPECTATION_CONFLICT],
            original_model_output=None,
            original_system_finding={},
            finding_fingerprint=_fingerprint(
                company_id,
                change.comparison_id,
                "temporal_narrative_inconsistency",
                [change.id],
                RULE_VERSION,
            ),
            review_status="pending",
        )
        finding.original_system_finding = _system_snapshot(finding)
        return finding, [
            ContradictionEvidence(
                contradiction_finding_id=finding.id,
                evidence_type="disclosure_change",
                disclosure_change_id=change.id,
                source_text=current,
                source_hash=_hash(current),
                evidence_role="primary",
                metadata_={"previous_text": previous, "change_type": change.change_type},
            )
        ]


class CrossSectionNarrativeConsistencyService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def detect(
        self,
        comparison: FilingComparison,
    ) -> list[tuple[ContradictionFinding, list[ContradictionEvidence]]]:
        sections = list(
            (
                await self.session.scalars(
                    select(FilingSection)
                    .where(FilingSection.filing_id == comparison.current_filing_id)
                    .order_by(FilingSection.section_order)
                )
            ).all()
        )
        mda = [section for section in sections if section.section_type == "mda"]
        comparison_sections = [
            section
            for section in sections
            if section.section_type in {"risk_factors", "legal_proceedings", "notes"}
        ]
        candidates = []
        for left in mda[:2]:
            for right in comparison_sections[:4]:
                pair = _section_conflict(left.raw_text, right.raw_text)
                if pair is None:
                    continue
                left_sentence, right_sentence = pair
                finding = _cross_section_finding(
                    comparison,
                    left,
                    right,
                    left_sentence,
                    right_sentence,
                )
                evidence = [
                    ContradictionEvidence(
                        contradiction_finding_id=finding.id,
                        evidence_type="narrative_passage",
                        filing_id=comparison.current_filing_id,
                        section_id=left.id,
                        source_text=left_sentence,
                        source_hash=_hash(left_sentence),
                        source_anchor=left.source_anchor,
                        evidence_role="primary",
                        metadata_={"section_type": left.section_type},
                    ),
                    ContradictionEvidence(
                        contradiction_finding_id=finding.id,
                        evidence_type="current_passage",
                        filing_id=comparison.current_filing_id,
                        section_id=right.id,
                        source_text=right_sentence,
                        source_hash=_hash(right_sentence),
                        source_anchor=right.source_anchor,
                        evidence_role="conflicting",
                        metadata_={"section_type": right.section_type},
                    ),
                ]
                candidates.append((finding, evidence))
        return candidates


def _cross_section_finding(
    comparison: FilingComparison,
    left: FilingSection,
    right: FilingSection,
    left_sentence: str,
    right_sentence: str,
) -> ContradictionFinding:
    confidence = Decimal("0.7000")
    finding = ContradictionFinding(
        company_id=comparison.company_id,
        comparison_id=comparison.id,
        contradiction_type="narrative_cross_section_inconsistency",
        status="candidate",
        risk_category="operations",
        severity="medium",
        confidence=confidence,
        narrative_claim=left_sentence,
        narrative_direction=None,
        measured_direction=None,
        reported_value=None,
        calculated_value=None,
        calculated_change=None,
        difference=None,
        qualifier=_first_qualifier(left_sentence),
        finding_title="Potential cross-section narrative inconsistency",
        finding_summary=(
            "Related statements across filing sections may point in different directions."
        ),
        finding_explanation=(
            "A bounded cross-section comparison found semantically related passages "
            "with opposing polarity signals. This requires analyst review and does "
            "not decide which statement is correct."
        ),
        limitations=["Rule-based polarity is a screening signal, not a final conclusion."],
        deterministic_evidence={
            "left_section_type": left.section_type,
            "right_section_type": right.section_type,
        },
        supporting_evidence={
            "left": left_sentence,
            "right": right_sentence,
            "pipeline": [
                "bounded_candidate_retrieval",
                "topic_overlap",
                "polarity_extraction",
                "deterministic_conflict_signal",
            ],
        },
        severity_components={"cross_section_conflict": True, "evidence_sources": 2},
        confidence_components={"semantic_relatedness": "0.70", "rule_confidence": "0.70"},
        detection_method="rule_based",
        rule_ids=[RULE_CROSS_SECTION_POLARITY_CONFLICT],
        original_model_output=None,
        original_system_finding={},
        finding_fingerprint=_fingerprint(
            comparison.company_id,
            comparison.id,
            "narrative_cross_section_inconsistency",
            [left.id, right.id, _hash(left_sentence), _hash(right_sentence)],
            RULE_VERSION,
        ),
        review_status="pending",
    )
    finding.original_system_finding = _system_snapshot(finding)
    return finding


def _calculated_change(verification: ClaimVerification) -> Decimal | None:
    return (
        verification.percentage_point_change
        or verification.percentage_change
        or verification.absolute_change
    )


def _direction_from_change(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value > 0:
        return "increase"
    if value < 0:
        return "decrease"
    return "unchanged"


def _first_qualifier(text: str) -> str | None:
    lower = text.lower()
    qualifiers = (
        STRENGTH_QUALIFIERS
        | WEAK_QUALIFIERS
        | UNCERTAINTY_QUALIFIERS
        | CERTAINTY_QUALIFIERS
    )
    for qualifier in sorted(qualifiers, key=len, reverse=True):
        if re.search(rf"\b{re.escape(qualifier)}\b", lower):
            return qualifier
    return None


def _policy_for(
    settings: Settings,
    metric_name: str | None,
    verification: ClaimVerification,
) -> MagnitudePolicy:
    if verification.percentage_point_change is not None or metric_name == "gross_margin":
        return MagnitudePolicy(
            metric_name=metric_name or "default_percentage_point_metric",
            unit="percentage_points",
            small=Decimal(str(settings.contradiction_small_percentage_point_threshold)),
            large=Decimal(str(settings.contradiction_large_percentage_point_threshold)),
        )
    return MagnitudePolicy(
        metric_name=metric_name or "default_percent_metric",
        unit="percent",
        small=Decimal(str(settings.contradiction_small_percent_threshold)),
        large=Decimal(str(settings.contradiction_large_percent_threshold)),
    )


def _numerical_status(claim: FinancialClaim, verification: ClaimVerification) -> str:
    if _missing_numerical_evidence(claim, verification):
        return "insufficient_evidence"
    return "candidate"


def _missing_numerical_evidence(
    claim: FinancialClaim,
    verification: ClaimVerification,
) -> list[str]:
    missing = []
    if claim.source_passage_id is None:
        missing.append("Missing source narrative passage.")
    if verification.current_xbrl_fact_id is None:
        missing.append("Missing selected current XBRL fact.")
    if (
        verification.calculation_type
        in {"percentage_change", "percentage_point_change", "directional_change"}
        and verification.comparison_xbrl_fact_id is None
    ):
        missing.append("Missing selected comparison XBRL fact.")
    if not verification.formula or verification.formula == "not_applicable":
        missing.append("Missing reproducible calculation formula.")
    return missing


def _severity(
    *,
    contradiction_type: str,
    verification: ClaimVerification | None,
    calculated_change: Decimal | None,
    evidence_complete: bool,
) -> tuple[str, dict[str, Any]]:
    magnitude = abs(calculated_change or Decimal("0"))
    deterministic = verification is not None and verification.verification_status == "contradicted"
    if not evidence_complete:
        severity = "low"
    elif (
        contradiction_type == "numerical_claim_contradiction"
        and deterministic
        and magnitude >= 10
    ):
        severity = "high"
    elif contradiction_type == "direction_contradiction" and deterministic:
        severity = "high"
    elif (
        contradiction_type in {"magnitude_overstatement", "magnitude_understatement"}
        and magnitude >= 5
    ):
        severity = "medium"
    else:
        severity = "low"
    return severity, {
        "contradiction_type": contradiction_type,
        "deterministic_evidence": deterministic,
        "measured_magnitude": str(magnitude),
        "evidence_complete": evidence_complete,
        "critical_requires_explicit_policy": True,
    }


def _confidence(
    *,
    claim: FinancialClaim,
    verification: ClaimVerification,
    rule_confidence: Decimal,
    semantic_confidence: Decimal | None,
) -> tuple[Decimal, dict[str, Any]]:
    values = [
        Decimal(str(claim.extraction_confidence)),
        Decimal(str(verification.confidence)),
        rule_confidence,
    ]
    if semantic_confidence is not None:
        values.append(semantic_confidence)
    confidence = _quantize(sum(values) / Decimal(len(values)))
    return confidence, {
        "narrative_source_confidence": str(claim.extraction_confidence),
        "verification_confidence": str(verification.confidence),
        "rule_confidence": str(rule_confidence),
        "semantic_matching_confidence": str(semantic_confidence) if semantic_confidence else None,
    }


def _verification_payload(verification: ClaimVerification) -> dict[str, Any]:
    return {
        "verification_id": str(verification.id),
        "verification_status": verification.verification_status,
        "current_xbrl_fact_id": _str_or_none(verification.current_xbrl_fact_id),
        "comparison_xbrl_fact_id": _str_or_none(verification.comparison_xbrl_fact_id),
        "formula": verification.formula,
        "calculation_inputs": verification.calculation_inputs,
        "calculation_output": verification.calculation_output,
        "confidence": str(verification.confidence),
    }


def _claim_payload(claim: FinancialClaim) -> dict[str, Any]:
    return {
        "claim_id": str(claim.id),
        "claim_text": claim.claim_text,
        "canonical_metric_name": claim.canonical_metric_name,
        "claim_type": claim.claim_type,
        "direction": claim.direction,
        "reported_change": (
            str(claim.reported_change) if claim.reported_change is not None else None
        ),
        "reported_value": str(claim.reported_value) if claim.reported_value is not None else None,
    }


def _numerical_evidence(
    finding: ContradictionFinding,
    claim: FinancialClaim,
    verification: ClaimVerification,
) -> list[ContradictionEvidence]:
    evidence = [
        ContradictionEvidence(
            contradiction_finding_id=finding.id,
            evidence_type="financial_claim",
            filing_id=claim.filing_id,
            section_id=claim.source_section_id,
            passage_id=claim.source_passage_id,
            financial_claim_id=claim.id,
            source_text=claim.claim_text,
            source_hash=_hash(claim.claim_text),
            evidence_role="primary",
            metadata_={"claim_type": claim.claim_type},
        ),
        ContradictionEvidence(
            contradiction_finding_id=finding.id,
            evidence_type="claim_verification",
            financial_claim_id=claim.id,
            claim_verification_id=verification.id,
            source_text=verification.verification_reason,
            source_hash=_hash(verification.verification_reason),
            evidence_role="supporting",
            metadata_=_verification_payload(verification),
        ),
    ]
    if verification.current_xbrl_fact_id is not None:
        evidence.append(
            ContradictionEvidence(
                contradiction_finding_id=finding.id,
                evidence_type="xbrl_fact",
                xbrl_fact_id=verification.current_xbrl_fact_id,
                evidence_role="supporting",
                metadata_={"role": "current"},
            )
        )
    if verification.comparison_xbrl_fact_id is not None:
        evidence.append(
            ContradictionEvidence(
                contradiction_finding_id=finding.id,
                evidence_type="xbrl_fact",
                xbrl_fact_id=verification.comparison_xbrl_fact_id,
                evidence_role="comparison",
                metadata_={"role": "comparison"},
            )
        )
    return evidence


def _temporal_conflict(previous: str, current: str) -> bool:
    previous_lower = previous.lower()
    current_lower = current.lower()
    financing_flip = (
        "do not expect" in previous_lower
        and "financing" in previous_lower
        and "expect" in current_lower
        and "financing" in current_lower
    )
    certainty_flip = (
        any(term in previous_lower for term in CERTAINTY_QUALIFIERS)
        and any(term in current_lower for term in NEGATIVE_TERMS)
    )
    return financing_flip or certainty_flip


def _section_conflict(left_text: str, right_text: str) -> tuple[str, str] | None:
    for left in _sentences(left_text)[:20]:
        left_topics = _topics(left)
        if not left_topics or not _has_positive_polarity(left):
            continue
        for right in _sentences(right_text)[:20]:
            if not left_topics & _topics(right):
                continue
            if _has_negative_polarity(right):
                return left, right
    return None


def _sentences(text: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
        if item.strip()
    ]


def _topics(text: str) -> set[str]:
    lower = text.lower()
    return {term for term in SHARED_TOPIC_TERMS if term in lower}


def _has_positive_polarity(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in POSITIVE_TERMS)


def _has_negative_polarity(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in NEGATIVE_TERMS)


def _fingerprint(
    company_id: uuid.UUID,
    comparison_id: uuid.UUID | None,
    contradiction_type: str,
    evidence_ids: list[object],
    rule_version: str,
) -> str:
    payload = {
        "company_id": str(company_id),
        "comparison_id": str(comparison_id) if comparison_id else None,
        "contradiction_type": contradiction_type,
        "evidence": [str(item) for item in evidence_ids],
        "rule_version": rule_version,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _quantize(value: Decimal) -> Decimal:
    return min(max(value, Decimal("0.0000")), Decimal("0.9900")).quantize(Decimal("0.0001"))


def _str_or_none(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _system_snapshot(finding: ContradictionFinding) -> dict[str, Any]:
    return {
        "contradiction_type": finding.contradiction_type,
        "status": finding.status,
        "severity": finding.severity,
        "confidence": str(finding.confidence),
        "finding_title": finding.finding_title,
        "finding_summary": finding.finding_summary,
        "finding_explanation": finding.finding_explanation,
        "rule_ids": finding.rule_ids,
    }
