from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    DisclosureChange,
    FilingComparison,
    PassageMatch,
    PassageUnit,
    SectionMatch,
)


class ComparisonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_comparison(self, comparison_id: uuid.UUID) -> FilingComparison | None:
        return await self.session.get(FilingComparison, comparison_id)

    async def try_acquire_comparison_lock(self, comparison_id: uuid.UUID) -> bool:
        lock_key = advisory_lock_key(comparison_id)
        return bool(await self.session.scalar(select(func.pg_try_advisory_lock(lock_key))))

    async def release_comparison_lock(self, comparison_id: uuid.UUID) -> bool:
        lock_key = advisory_lock_key(comparison_id)
        return bool(await self.session.scalar(select(func.pg_advisory_unlock(lock_key))))

    async def get_existing_comparison(
        self,
        *,
        current_filing_id: uuid.UUID,
        comparison_filing_id: uuid.UUID,
        comparison_version: str,
    ) -> FilingComparison | None:
        stmt = select(FilingComparison).where(
            FilingComparison.current_filing_id == current_filing_id,
            FilingComparison.comparison_filing_id == comparison_filing_id,
            FilingComparison.comparison_version == comparison_version,
        )
        return await self.session.scalar(stmt)

    async def create_comparison(
        self,
        *,
        company_id: uuid.UUID,
        current_filing_id: uuid.UUID,
        comparison_filing_id: uuid.UUID,
        comparison_version: str,
    ) -> FilingComparison:
        existing = await self.get_existing_comparison(
            current_filing_id=current_filing_id,
            comparison_filing_id=comparison_filing_id,
            comparison_version=comparison_version,
        )
        if existing is not None:
            return existing
        comparison = FilingComparison(
            company_id=company_id,
            current_filing_id=current_filing_id,
            comparison_filing_id=comparison_filing_id,
            comparison_version=comparison_version,
            status="queued",
            processing_metrics={},
        )
        self.session.add(comparison)
        await self.session.flush()
        return comparison

    async def list_comparisons(
        self,
        *,
        company_id: uuid.UUID | None = None,
        status: str | None = None,
        current_filing_id: uuid.UUID | None = None,
        comparison_filing_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FilingComparison]:
        stmt = select(FilingComparison).order_by(FilingComparison.created_at.desc())
        if company_id is not None:
            stmt = stmt.where(FilingComparison.company_id == company_id)
        if status is not None:
            stmt = stmt.where(FilingComparison.status == status)
        if current_filing_id is not None:
            stmt = stmt.where(FilingComparison.current_filing_id == current_filing_id)
        if comparison_filing_id is not None:
            stmt = stmt.where(FilingComparison.comparison_filing_id == comparison_filing_id)
        stmt = stmt.offset(offset).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def set_status(
        self,
        comparison: FilingComparison,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        metrics: dict[str, object] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        comparison.status = status
        comparison.error_code = error_code
        comparison.error_message = error_message
        if metrics is not None:
            comparison.processing_metrics = metrics
        if status != "queued" and comparison.started_at is None:
            comparison.started_at = now
        if status in {"completed", "failed", "partial"}:
            comparison.completed_at = now
        await self.session.flush()

    async def replace_section_matches(
        self,
        comparison_id: uuid.UUID,
        matches: Iterable[SectionMatch],
    ) -> list[SectionMatch]:
        await self.session.execute(
            delete(SectionMatch).where(SectionMatch.comparison_id == comparison_id)
        )
        stored = list(matches)
        self.session.add_all(stored)
        await self.session.flush()
        return stored

    async def list_section_matches(self, comparison_id: uuid.UUID) -> list[SectionMatch]:
        stmt = (
            select(SectionMatch)
            .where(SectionMatch.comparison_id == comparison_id)
            .order_by(SectionMatch.created_at, SectionMatch.id)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_or_create_passages(
        self,
        section_id: uuid.UUID,
        passages: list[PassageUnit],
        *,
        segmentation_version: str,
    ) -> list[PassageUnit]:
        existing = await self.list_passages_for_section(
            section_id, segmentation_version=segmentation_version
        )
        if [unit.content_hash for unit in existing] == [unit.content_hash for unit in passages]:
            return existing
        await self.session.execute(
            delete(PassageUnit).where(
                PassageUnit.filing_section_id == section_id,
                PassageUnit.segmentation_version == segmentation_version,
            )
        )
        self.session.add_all(passages)
        await self.session.flush()
        return passages

    async def list_passages_for_section(
        self,
        section_id: uuid.UUID,
        *,
        segmentation_version: str | None = None,
    ) -> list[PassageUnit]:
        stmt = select(PassageUnit).where(PassageUnit.filing_section_id == section_id)
        if segmentation_version is not None:
            stmt = stmt.where(PassageUnit.segmentation_version == segmentation_version)
        stmt = stmt.order_by(PassageUnit.unit_index)
        return list((await self.session.scalars(stmt)).all())

    async def replace_passage_matches(
        self,
        section_match_id: uuid.UUID,
        matches: Iterable[PassageMatch],
    ) -> list[PassageMatch]:
        await self.session.execute(
            delete(PassageMatch).where(PassageMatch.section_match_id == section_match_id)
        )
        stored = list(matches)
        self.session.add_all(stored)
        await self.session.flush()
        return stored

    async def list_passage_matches(self, comparison_id: uuid.UUID) -> list[PassageMatch]:
        stmt = (
            select(PassageMatch)
            .join(SectionMatch, PassageMatch.section_match_id == SectionMatch.id)
            .where(SectionMatch.comparison_id == comparison_id)
            .order_by(PassageMatch.created_at, PassageMatch.id)
        )
        return list((await self.session.scalars(stmt)).all())

    async def replace_changes(
        self,
        comparison_id: uuid.UUID,
        changes: Iterable[DisclosureChange],
    ) -> list[DisclosureChange]:
        await self.session.execute(
            delete(DisclosureChange).where(DisclosureChange.comparison_id == comparison_id)
        )
        stored = list(changes)
        self.session.add_all(stored)
        await self.session.flush()
        return stored

    async def replace_changes_for_section_match(
        self,
        section_match_id: uuid.UUID,
        changes: Iterable[DisclosureChange],
    ) -> list[DisclosureChange]:
        await self.session.execute(
            delete(DisclosureChange).where(DisclosureChange.section_match_id == section_match_id)
        )
        stored = list(changes)
        self.session.add_all(stored)
        await self.session.flush()
        return stored

    async def list_changes(
        self,
        comparison_id: uuid.UUID,
        *,
        change_type: str | None = None,
        risk_category: str | None = None,
        min_materiality: float | None = None,
        review_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DisclosureChange]:
        stmt = select(DisclosureChange).where(DisclosureChange.comparison_id == comparison_id)
        if change_type is not None:
            stmt = stmt.where(DisclosureChange.change_type == change_type)
        if risk_category is not None:
            stmt = stmt.where(DisclosureChange.risk_category == risk_category)
        if min_materiality is not None:
            stmt = stmt.where(DisclosureChange.materiality_score >= min_materiality)
        if review_status is not None:
            stmt = stmt.where(DisclosureChange.review_status == review_status)
        stmt = stmt.order_by(DisclosureChange.materiality_score.desc()).offset(offset).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def get_change(
        self,
        comparison_id: uuid.UUID,
        change_id: uuid.UUID,
    ) -> DisclosureChange | None:
        stmt = select(DisclosureChange).where(
            DisclosureChange.comparison_id == comparison_id,
            DisclosureChange.id == change_id,
        )
        return await self.session.scalar(stmt)

    async def summarize_changes(self, comparison_id: uuid.UUID) -> dict[str, Any]:
        stmt = (
            select(DisclosureChange.change_type, func.count())
            .where(DisclosureChange.comparison_id == comparison_id)
            .group_by(DisclosureChange.change_type)
        )
        rows = await self.session.execute(stmt)
        return {str(row[0]): int(row[1]) for row in rows}

    async def apply_review(
        self,
        change: DisclosureChange,
        *,
        review_status: str,
        comment: str | None = None,
        reviewer_id: str | None = None,
        change_type: str | None = None,
        risk_category: str | None = None,
        summary: str | None = None,
    ) -> DisclosureChange:
        edits: dict[str, object] = dict(change.reviewer_edits or {})
        if change_type is not None:
            edits["change_type"] = change.change_type
            change.change_type = change_type
        if risk_category is not None:
            edits["risk_category"] = change.risk_category
            change.risk_category = risk_category
        if summary is not None:
            edits["change_summary"] = change.change_summary
            change.change_summary = summary
        change.review_status = review_status
        change.review_comment = comment
        change.reviewed_by = reviewer_id
        change.reviewed_at = datetime.now(UTC)
        change.reviewer_edits = edits
        await self.session.flush()
        return change


def advisory_lock_key(comparison_id: uuid.UUID) -> int:
    return comparison_id.int % (2**62 - 1) + 2**62
