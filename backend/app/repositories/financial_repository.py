from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ClaimFactCandidate,
    ClaimVerification,
    DerivedFinancialMetric,
    Filing,
    FilingSection,
    FinancialClaim,
    FinancialMetricConcept,
    FinancialMetricDefinition,
    PassageUnit,
    XbrlFact,
)


class FinancialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def try_acquire_verification_lock(self, entity_id: uuid.UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(func.pg_try_advisory_lock(advisory_lock_key(entity_id)))
            )
        )

    async def release_verification_lock(self, entity_id: uuid.UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(func.pg_advisory_unlock(advisory_lock_key(entity_id)))
            )
        )

    async def list_metric_definitions(
        self, *, active_only: bool = True
    ) -> list[FinancialMetricDefinition]:
        stmt = select(FinancialMetricDefinition).order_by(FinancialMetricDefinition.canonical_name)
        if active_only:
            stmt = stmt.where(FinancialMetricDefinition.is_active.is_(True))
        return list((await self.session.scalars(stmt)).all())

    async def get_metric_by_name(self, canonical_name: str) -> FinancialMetricDefinition | None:
        stmt = select(FinancialMetricDefinition).where(
            FinancialMetricDefinition.canonical_name == canonical_name
        )
        return await self.session.scalar(stmt)

    async def list_metric_concepts(
        self, metric_definition_id: uuid.UUID
    ) -> list[FinancialMetricConcept]:
        stmt = (
            select(FinancialMetricConcept)
            .where(
                FinancialMetricConcept.metric_definition_id == metric_definition_id,
                FinancialMetricConcept.is_active.is_(True),
            )
            .order_by(FinancialMetricConcept.priority)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_filing(self, filing_id: uuid.UUID) -> Filing | None:
        return await self.session.get(Filing, filing_id)

    async def get_section(self, section_id: uuid.UUID) -> FilingSection | None:
        return await self.session.get(FilingSection, section_id)

    async def get_passage(self, passage_id: uuid.UUID) -> PassageUnit | None:
        return await self.session.get(PassageUnit, passage_id)

    async def get_claim(self, claim_id: uuid.UUID) -> FinancialClaim | None:
        return await self.session.get(FinancialClaim, claim_id)

    async def find_existing_claim(
        self,
        *,
        filing_id: uuid.UUID,
        source_passage_id: uuid.UUID | None,
        claim_text: str,
        canonical_metric_name: str | None,
    ) -> FinancialClaim | None:
        stmt = select(FinancialClaim).where(
            FinancialClaim.filing_id == filing_id,
            FinancialClaim.claim_text == claim_text,
            FinancialClaim.canonical_metric_name == canonical_metric_name,
        )
        if source_passage_id is None:
            stmt = stmt.where(FinancialClaim.source_passage_id.is_(None))
        else:
            stmt = stmt.where(FinancialClaim.source_passage_id == source_passage_id)
        return await self.session.scalar(stmt)

    async def upsert_claim(self, claim: FinancialClaim) -> tuple[FinancialClaim, bool]:
        existing = await self.find_existing_claim(
            filing_id=claim.filing_id,
            source_passage_id=claim.source_passage_id,
            claim_text=claim.claim_text,
            canonical_metric_name=claim.canonical_metric_name,
        )
        if existing is not None:
            return existing, False
        self.session.add(claim)
        await self.session.flush()
        return claim, True

    async def list_claims(
        self,
        *,
        filing_id: uuid.UUID | None = None,
        comparison_id: uuid.UUID | None = None,
        canonical_metric: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FinancialClaim]:
        stmt = select(FinancialClaim).order_by(FinancialClaim.created_at, FinancialClaim.id)
        if filing_id is not None:
            stmt = stmt.where(FinancialClaim.filing_id == filing_id)
        if comparison_id is not None:
            stmt = stmt.where(FinancialClaim.comparison_id == comparison_id)
        if canonical_metric is not None:
            stmt = stmt.where(FinancialClaim.canonical_metric_name == canonical_metric)
        stmt = stmt.offset(offset).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def search_xbrl_facts(
        self,
        *,
        company_id: uuid.UUID,
        concepts: list[str],
    ) -> list[XbrlFact]:
        if not concepts:
            return []
        stmt = select(XbrlFact).where(
            XbrlFact.company_id == company_id,
            XbrlFact.concept.in_(concepts),
            XbrlFact.value_numeric.is_not(None),
        )
        return list((await self.session.scalars(stmt)).all())

    async def replace_fact_candidates(
        self,
        claim_id: uuid.UUID,
        role: str,
        candidates: Iterable[ClaimFactCandidate],
    ) -> list[ClaimFactCandidate]:
        await self.session.execute(
            delete(ClaimFactCandidate).where(
                ClaimFactCandidate.financial_claim_id == claim_id,
                ClaimFactCandidate.candidate_role == role,
            )
        )
        stored = list(candidates)
        self.session.add_all(stored)
        await self.session.flush()
        return stored

    async def list_fact_candidates(self, claim_id: uuid.UUID) -> list[ClaimFactCandidate]:
        stmt = (
            select(ClaimFactCandidate)
            .where(ClaimFactCandidate.financial_claim_id == claim_id)
            .order_by(
                ClaimFactCandidate.candidate_role,
                ClaimFactCandidate.combined_score.desc(),
                ClaimFactCandidate.id,
            )
        )
        return list((await self.session.scalars(stmt)).all())

    async def select_fact_candidate(
        self,
        *,
        claim_id: uuid.UUID,
        candidate_id: uuid.UUID,
        reviewer_id: str | None = None,
        comment: str | None = None,
    ) -> ClaimFactCandidate | None:
        candidate = await self.session.get(ClaimFactCandidate, candidate_id)
        if candidate is None or candidate.financial_claim_id != claim_id:
            return None
        role_candidates = await self.session.scalars(
            select(ClaimFactCandidate).where(
                ClaimFactCandidate.financial_claim_id == claim_id,
                ClaimFactCandidate.candidate_role == candidate.candidate_role,
            )
        )
        note = f"Reviewer selected candidate. reviewer_id={reviewer_id or 'unknown'}"
        if comment:
            note = f"{note}; comment={comment}"
        for item in role_candidates:
            if item.id == candidate_id:
                item.selection_status = "selected"
                item.rejection_reason = note
            else:
                item.selection_status = "rejected"
                item.rejection_reason = "Rejected by reviewer fact-mapping selection."
        await self.session.flush()
        return candidate

    async def upsert_verification(
        self, verification: ClaimVerification
    ) -> ClaimVerification:
        stmt = select(ClaimVerification).where(
            ClaimVerification.financial_claim_id == verification.financial_claim_id,
            ClaimVerification.verification_version == verification.verification_version,
        )
        existing = await self.session.scalar(stmt)
        if existing is None:
            self.session.add(verification)
            await self.session.flush()
            return verification
        for key in (
            "current_xbrl_fact_id",
            "comparison_xbrl_fact_id",
            "verification_status",
            "current_value",
            "comparison_value",
            "absolute_change",
            "percentage_change",
            "percentage_point_change",
            "reported_change",
            "reported_vs_calculated_difference",
            "calculation_type",
            "formula",
            "calculation_inputs",
            "calculation_output",
            "tolerance_used",
            "verification_reason",
            "confidence",
        ):
            setattr(existing, key, getattr(verification, key))
        await self.session.flush()
        return existing

    async def get_verification(self, claim_id: uuid.UUID) -> ClaimVerification | None:
        stmt = (
            select(ClaimVerification)
            .where(ClaimVerification.financial_claim_id == claim_id)
            .order_by(ClaimVerification.created_at.desc())
        )
        return await self.session.scalar(stmt)

    async def list_verifications(
        self,
        *,
        comparison_id: uuid.UUID | None = None,
        verification_status: str | None = None,
        min_confidence=None,
    ) -> list[ClaimVerification]:
        stmt = select(ClaimVerification).join(FinancialClaim)
        if comparison_id is not None:
            stmt = stmt.where(FinancialClaim.comparison_id == comparison_id)
        if verification_status is not None:
            stmt = stmt.where(ClaimVerification.verification_status == verification_status)
        if min_confidence is not None:
            stmt = stmt.where(ClaimVerification.confidence >= min_confidence)
        stmt = stmt.order_by(ClaimVerification.created_at, ClaimVerification.id)
        return list((await self.session.scalars(stmt)).all())

    async def upsert_derived_metric(
        self, metric: DerivedFinancialMetric
    ) -> DerivedFinancialMetric:
        stmt = select(DerivedFinancialMetric).where(
            DerivedFinancialMetric.filing_id == metric.filing_id,
            DerivedFinancialMetric.metric_definition_id == metric.metric_definition_id,
            DerivedFinancialMetric.period_start == metric.period_start,
            DerivedFinancialMetric.period_end == metric.period_end,
            DerivedFinancialMetric.calculation_version == metric.calculation_version,
        )
        existing = await self.session.scalar(stmt)
        if existing is not None:
            for key in (
                "calculation_status",
                "formula",
                "input_fact_ids",
                "calculation_inputs_snapshot",
                "calculated_value",
                "unit",
                "period_type",
                "assumptions",
            ):
                setattr(existing, key, getattr(metric, key))
            await self.session.flush()
            return existing
        self.session.add(metric)
        await self.session.flush()
        return metric

    async def apply_claim_review(
        self,
        claim: FinancialClaim,
        *,
        review_status: str,
        comment: str | None = None,
        reviewer_id: str | None = None,
        canonical_metric_name: str | None = None,
        reported_value=None,
        reported_unit: str | None = None,
        comparison_basis: str | None = None,
    ) -> FinancialClaim:
        edits: dict[str, object] = dict(claim.reviewer_edits or {})
        for key, value in (
            ("canonical_metric_name", canonical_metric_name),
            ("reported_value", reported_value),
            ("reported_unit", reported_unit),
            ("comparison_basis", comparison_basis),
        ):
            if value is not None:
                edits[key] = str(getattr(claim, key))
                setattr(claim, key, value)
        if canonical_metric_name is not None:
            metric = await self.get_metric_by_name(canonical_metric_name)
            claim.metric_definition_id = metric.id if metric else None
        claim.review_status = review_status
        claim.review_comment = comment
        claim.reviewed_by = reviewer_id
        claim.reviewed_at = datetime.now(UTC)
        claim.reviewer_edits = edits
        await self.session.flush()
        return claim


def advisory_lock_key(entity_id: uuid.UUID) -> int:
    return entity_id.int % (2**62 - 1) + (2**61)
