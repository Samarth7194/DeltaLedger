from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    ClaimFactCandidate,
    Filing,
    FinancialClaim,
    FinancialMetricConcept,
    XbrlFact,
)
from app.repositories.financial_repository import FinancialRepository
from app.services.financial_periods import classify_fact_period


@dataclass(frozen=True)
class FactResolutionResult:
    status: str
    selected_fact: XbrlFact | None
    candidates: list[ClaimFactCandidate]
    confidence: Decimal
    reason: str


class XbrlFactResolutionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.repo = FinancialRepository(session)
        self.settings = settings

    async def resolve_fact(
        self,
        *,
        claim: FinancialClaim,
        metric_concepts: list[FinancialMetricConcept],
        target_filing: Filing,
        role: str,
        expected_period_type: str | None = None,
    ) -> FactResolutionResult:
        if not metric_concepts:
            return FactResolutionResult(
                "unsupported_metric",
                None,
                [],
                Decimal("0"),
                "No concepts.",
            )
        facts = await self.repo.search_xbrl_facts(
            company_id=target_filing.company_id,
            concepts=[concept.concept for concept in metric_concepts],
        )
        candidate_rows = [
            self._score_candidate(claim, target_filing, role, concept, fact, expected_period_type)
            for concept in metric_concepts
            for fact in facts
            if fact.concept == concept.concept
        ]
        candidate_rows.sort(key=lambda row: row.combined_score, reverse=True)
        selected = self._select(candidate_rows)
        stored = await self.repo.replace_fact_candidates(claim.id, role, candidate_rows)
        if selected is None:
            if stored and stored[0].unit_match_score == 0:
                return FactResolutionResult(
                    "unit_mismatch",
                    None,
                    stored,
                    Decimal("0"),
                    "Top candidate has incompatible unit.",
                )
            if stored and stored[0].period_match_score == 0:
                return FactResolutionResult(
                    "period_mismatch",
                    None,
                    stored,
                    Decimal("0"),
                    "Top candidate has incompatible period type.",
                )
            reason = "No candidate exceeded score and ambiguity thresholds."
            status = "insufficient_data" if not stored else "ambiguous_fact"
            return FactResolutionResult(status, None, stored, Decimal("0"), reason)
        selected_fact = next(fact for fact in facts if fact.id == selected.xbrl_fact_id)
        return FactResolutionResult(
            "selected",
            selected_fact,
            stored,
            selected.combined_score,
            "Selected highest scoring accession/period/unit/concept candidate.",
        )

    def _score_candidate(
        self,
        claim: FinancialClaim,
        target_filing: Filing,
        role: str,
        concept: FinancialMetricConcept,
        fact: XbrlFact,
        expected_period_type: str | None,
    ) -> ClaimFactCandidate:
        period_type = classify_fact_period(
            start_date=fact.start_date,
            end_date=fact.end_date,
            instant_date=fact.instant_date,
            fiscal_period=fact.fiscal_period,
        )
        concept_score = Decimal("1") - (Decimal(concept.priority - 1) * Decimal("0.04"))
        accession_score = (
            Decimal("1")
            if fact.accession_number == target_filing.accession_number
            else Decimal("0.20")
        )
        period_score = _period_score(fact, target_filing, expected_period_type, period_type)
        unit_score = (
            Decimal("1") if units_compatible(concept.unit_category, fact.unit) else Decimal("0")
        )
        frame_score = Decimal("1") if fact.frame else Decimal("0.80")
        combined = (
            concept_score * Decimal("0.25")
            + period_score * Decimal("0.30")
            + unit_score * Decimal("0.20")
            + accession_score * Decimal("0.20")
            + frame_score * Decimal("0.05")
        ).quantize(Decimal("0.0001"))
        return ClaimFactCandidate(
            financial_claim_id=claim.id,
            xbrl_fact_id=fact.id,
            candidate_role=role,
            concept_priority=concept.priority,
            concept_match_score=concept_score.quantize(Decimal("0.0001")),
            period_match_score=period_score.quantize(Decimal("0.0001")),
            unit_match_score=unit_score.quantize(Decimal("0.0001")),
            accession_match_score=accession_score.quantize(Decimal("0.0001")),
            frame_match_score=frame_score.quantize(Decimal("0.0001")),
            combined_score=combined,
            selection_status="candidate",
            rejection_reason=None,
        )

    def _select(self, candidates: list[ClaimFactCandidate]) -> ClaimFactCandidate | None:
        if not candidates:
            return None
        top = candidates[0]
        min_score = Decimal(str(self.settings.xbrl_fact_min_score))
        margin = Decimal(str(self.settings.xbrl_fact_ambiguity_margin))
        if top.unit_match_score == 0 or top.period_match_score == 0:
            return None
        if top.combined_score < min_score:
            return None
        if len(candidates) > 1:
            second = candidates[1]
            if top.combined_score - second.combined_score < margin:
                if top.xbrl_fact_id != second.xbrl_fact_id:
                    top.selection_status = "ambiguous"
                    second.selection_status = "ambiguous"
                    return None
        top.selection_status = "selected"
        for candidate in candidates[1:]:
            candidate.selection_status = "rejected"
            candidate.rejection_reason = "Lower combined score."
        return top


def units_compatible(unit_category: str | None, unit: str | None) -> bool:
    normalized = (unit or "").lower()
    if unit_category == "monetary":
        return normalized in {"usd", "iso4217:usd", "us dollars"}
    if unit_category == "percentage":
        return normalized in {"percent", "%", "pure"}
    if unit_category == "per_share":
        return normalized in {"usd/shares", "usd/share", "usdpershare", "iso4217:usd/shares"}
    if unit_category == "count":
        return normalized in {"shares", "pure"}
    return True


def _period_score(
    fact: XbrlFact,
    filing: Filing,
    expected_period_type: str | None,
    actual_period_type: str,
) -> Decimal:
    if expected_period_type and actual_period_type != expected_period_type:
        return Decimal("0")
    target_date = filing.report_period or filing.filing_date
    if fact.instant_date == target_date or fact.end_date == target_date:
        return Decimal("1")
    if fact.fiscal_year and target_date.year == fact.fiscal_year:
        return Decimal("0.60")
    return Decimal("0.25")
