from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ClaimVerification,
    ContradictionEvidence,
    ContradictionFinding,
    FinancialClaim,
)


class ContradictionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def try_acquire_analysis_lock(self, comparison_id: uuid.UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(func.pg_try_advisory_lock(advisory_lock_key(comparison_id)))
            )
        )

    async def release_analysis_lock(self, comparison_id: uuid.UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(func.pg_advisory_unlock(advisory_lock_key(comparison_id)))
            )
        )

    async def list_claim_verification_pairs(
        self,
        comparison_id: uuid.UUID,
    ) -> list[tuple[FinancialClaim, ClaimVerification]]:
        stmt = (
            select(FinancialClaim, ClaimVerification)
            .join(ClaimVerification, ClaimVerification.financial_claim_id == FinancialClaim.id)
            .where(FinancialClaim.comparison_id == comparison_id)
            .order_by(FinancialClaim.created_at, FinancialClaim.id)
        )
        rows = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in rows]

    async def upsert_finding(
        self,
        finding: ContradictionFinding,
        evidence: Iterable[ContradictionEvidence],
    ) -> tuple[ContradictionFinding, bool]:
        existing = await self.session.scalar(
            select(ContradictionFinding).where(
                ContradictionFinding.finding_fingerprint == finding.finding_fingerprint
            )
        )
        created = existing is None
        if existing is None:
            self.session.add(finding)
            await self.session.flush()
            existing = finding
        else:
            for key in _SYSTEM_FINDING_FIELDS:
                setattr(existing, key, getattr(finding, key))
            await self.session.flush()
            await self.session.execute(
                delete(ContradictionEvidence).where(
                    ContradictionEvidence.contradiction_finding_id == existing.id
                )
            )
        stored_evidence = list(evidence)
        for item in stored_evidence:
            item.contradiction_finding_id = existing.id
        self.session.add_all(stored_evidence)
        await self.session.flush()
        return existing, created

    async def get_finding(self, finding_id: uuid.UUID) -> ContradictionFinding | None:
        return await self.session.get(ContradictionFinding, finding_id)

    async def list_findings(
        self,
        *,
        comparison_id: uuid.UUID | None = None,
        contradiction_type: str | None = None,
        severity: str | None = None,
        risk_category: str | None = None,
        min_confidence: Decimal | None = None,
        review_status: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContradictionFinding]:
        stmt = select(ContradictionFinding)
        if comparison_id is not None:
            stmt = stmt.where(ContradictionFinding.comparison_id == comparison_id)
        if contradiction_type is not None:
            stmt = stmt.where(ContradictionFinding.contradiction_type == contradiction_type)
        if severity is not None:
            stmt = stmt.where(ContradictionFinding.severity == severity)
        if risk_category is not None:
            stmt = stmt.where(ContradictionFinding.risk_category == risk_category)
        if min_confidence is not None:
            stmt = stmt.where(ContradictionFinding.confidence >= min_confidence)
        if review_status is not None:
            stmt = stmt.where(ContradictionFinding.review_status == review_status)
        if status is not None:
            stmt = stmt.where(ContradictionFinding.status == status)
        stmt = (
            stmt.order_by(
                ContradictionFinding.confidence.desc(),
                ContradictionFinding.created_at,
                ContradictionFinding.id,
            )
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_evidence(self, finding_id: uuid.UUID) -> list[ContradictionEvidence]:
        stmt = (
            select(ContradictionEvidence)
            .where(ContradictionEvidence.contradiction_finding_id == finding_id)
            .order_by(ContradictionEvidence.evidence_role, ContradictionEvidence.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

    async def summarize_findings(self, comparison_id: uuid.UUID) -> dict[str, Any]:
        findings = await self.list_findings(comparison_id=comparison_id, limit=1000)
        by_type: dict[str, int] = {}
        by_review_status: dict[str, int] = {}
        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for finding in findings:
            by_type[finding.contradiction_type] = by_type.get(finding.contradiction_type, 0) + 1
            by_review_status[finding.review_status] = (
                by_review_status.get(finding.review_status, 0) + 1
            )
            by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        return {
            "total_candidates": len(findings),
            "critical": by_severity["critical"],
            "high": by_severity["high"],
            "medium": by_severity["medium"],
            "low": by_severity["low"],
            "by_type": by_type,
            "by_review_status": by_review_status,
        }

    async def apply_review(
        self,
        finding: ContradictionFinding,
        *,
        review_status: str,
        comment: str | None = None,
        reviewer_id: str | None = None,
        contradiction_type: str | None = None,
        severity: str | None = None,
        risk_category: str | None = None,
        summary: str | None = None,
        explanation: str | None = None,
    ) -> ContradictionFinding:
        edits: dict[str, object] = dict(finding.reviewer_edits or {})
        for key, value in (
            ("contradiction_type", contradiction_type),
            ("severity", severity),
            ("risk_category", risk_category),
            ("finding_summary", summary),
            ("finding_explanation", explanation),
        ):
            if value is not None:
                edits[key] = getattr(finding, key)
                setattr(finding, key, value)
        finding.review_status = review_status
        finding.review_comment = comment
        finding.reviewed_by = reviewer_id
        finding.reviewed_at = datetime.now(UTC)
        finding.reviewer_edits = edits
        await self.session.flush()
        return finding


def advisory_lock_key(comparison_id: uuid.UUID) -> int:
    return comparison_id.int % (2**62 - 1) + (2**60)


_SYSTEM_FINDING_FIELDS = (
    "company_id",
    "comparison_id",
    "financial_claim_id",
    "claim_verification_id",
    "disclosure_change_id",
    "contradiction_type",
    "status",
    "risk_category",
    "severity",
    "confidence",
    "narrative_claim",
    "narrative_direction",
    "measured_direction",
    "reported_value",
    "calculated_value",
    "calculated_change",
    "difference",
    "qualifier",
    "finding_title",
    "finding_summary",
    "finding_explanation",
    "limitations",
    "deterministic_evidence",
    "supporting_evidence",
    "severity_components",
    "confidence_components",
    "detection_method",
    "rule_ids",
    "model_name",
    "model_version",
    "prompt_version",
    "original_model_output",
    "original_system_finding",
)
