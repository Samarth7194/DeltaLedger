from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import create_embedding_service
from app.ai.reranker import create_reranker
from app.ai.semantic_change import create_change_classifier
from app.core.config import Settings
from app.core.exceptions import DeltaLedgerError
from app.db.models import Filing, FilingChunk, FilingSection
from app.repositories.comparison_repository import ComparisonRepository
from app.repositories.filing_repository import FilingRepository
from app.repositories.section_repository import SectionRepository
from app.services.disclosure_change_service import DisclosureChangeService
from app.services.passage_alignment_service import PassageAlignmentService
from app.services.passage_segmentation_service import PassageSegmentationService
from app.services.section_matching_service import SectionMatchingService


class FilingComparisonError(DeltaLedgerError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ComparisonCreateResult:
    comparison_id: uuid.UUID
    status: str
    created: bool


class FilingComparisonService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.comparisons = ComparisonRepository(session)
        self.filings = FilingRepository(session)
        self.sections = SectionRepository(session)
        embeddings = create_embedding_service(settings)
        reranker = create_reranker(settings)
        self.segmenter = PassageSegmentationService(settings)
        self.matcher = SectionMatchingService(settings, embeddings, reranker)
        self.aligner = PassageAlignmentService(settings, embeddings, reranker)
        self.change_detector = DisclosureChangeService(settings, create_change_classifier(settings))

    async def create_comparison(
        self,
        *,
        current_filing_id: uuid.UUID,
        comparison_filing_id: uuid.UUID,
    ) -> ComparisonCreateResult:
        current, previous = await self.validate_pair(current_filing_id, comparison_filing_id)
        existing = await self.comparisons.get_existing_comparison(
            current_filing_id=current.id,
            comparison_filing_id=previous.id,
            comparison_version=self.settings.comparison_version,
        )
        comparison = await self.comparisons.create_comparison(
            company_id=current.company_id,
            current_filing_id=current.id,
            comparison_filing_id=previous.id,
            comparison_version=self.settings.comparison_version,
        )
        await self.session.commit()
        return ComparisonCreateResult(
            comparison_id=comparison.id,
            status=comparison.status,
            created=existing is None,
        )

    async def validate_pair(
        self,
        current_filing_id: uuid.UUID,
        comparison_filing_id: uuid.UUID,
    ) -> tuple[Filing, Filing]:
        if current_filing_id == comparison_filing_id:
            raise FilingComparisonError(
                "same_filing",
                "Current and comparison filings must differ.",
            )
        current = await self.filings.get(current_filing_id)
        previous = await self.filings.get(comparison_filing_id)
        if current is None or previous is None:
            raise FilingComparisonError("filing_not_found", "Both filings must exist.")
        if current.company_id != previous.company_id:
            raise FilingComparisonError(
                "different_companies",
                "Filings must belong to the same company.",
            )
        if current.form_type != "10-Q" or previous.form_type != "10-Q":
            raise FilingComparisonError(
                "unsupported_form",
                "Phase 3 comparison supports 10-Q only.",
            )
        current_period = _period(current)
        previous_period = _period(previous)
        if current_period == previous_period:
            raise FilingComparisonError("same_period", "Filing periods must be different.")
        if current_period <= previous_period:
            raise FilingComparisonError(
                "invalid_period_order",
                "Current filing period must be later than comparison filing period.",
            )
        if not await self._has_parsed_content(
            current.id
        ) or not await self._has_parsed_content(previous.id):
            raise FilingComparisonError(
                "missing_parsed_content",
                "Both filings need parsed sections and chunks.",
            )
        return current, previous

    async def process_comparison(self, comparison_id: uuid.UUID) -> None:
        lock_acquired = await self.comparisons.try_acquire_comparison_lock(comparison_id)
        if not lock_acquired:
            return
        try:
            await self._process_comparison_locked(comparison_id)
        finally:
            await self.comparisons.release_comparison_lock(comparison_id)

    async def _process_comparison_locked(self, comparison_id: uuid.UUID) -> None:
        comparison = await self.comparisons.get_comparison(comparison_id)
        if comparison is None:
            raise FilingComparisonError("comparison_not_found", "Comparison not found.")
        if comparison.status == "completed":
            return
        try:
            await self.comparisons.set_status(comparison, "matching_sections")
            current_sections = await self.sections.get_sections_with_chunks(
                comparison.current_filing_id
            )
            previous_sections = await self.sections.get_sections_with_chunks(
                comparison.comparison_filing_id
            )
            await self._segment_sections(current_sections + previous_sections)
            section_matches = await self.matcher.match_sections(
                comparison_id=comparison.id,
                current_sections=current_sections,
                previous_sections=previous_sections,
            )
            stored_section_matches = await self.comparisons.replace_section_matches(
                comparison.id, section_matches
            )

            await self.comparisons.set_status(comparison, "aligning_passages")
            section_by_id = {
                section.id: section for section in current_sections + previous_sections
            }
            all_passage_matches = []
            for section_match in stored_section_matches:
                current_passages = await self._passages(section_match.current_section_id)
                previous_passages = await self._passages(section_match.previous_section_id)
                matches = await self.aligner.align_passages(
                    section_match_id=section_match.id,
                    current_passages=current_passages,
                    previous_passages=previous_passages,
                )
                all_passage_matches.extend(
                    await self.comparisons.replace_passage_matches(section_match.id, matches)
                )

            await self.comparisons.set_status(comparison, "detecting_changes")
            passages = {
                passage.id: passage
                for section in current_sections + previous_sections
                for passage in await self._passages(section.id)
            }
            changes = []
            for section_match in stored_section_matches:
                section_passage_matches = [
                    match
                    for match in all_passage_matches
                    if match.section_match_id == section_match.id
                ]
                for passage_match in section_passage_matches:
                    change = await self.change_detector.detect_change(
                        comparison_id=comparison.id,
                        section_match=section_match,
                        passage_match=passage_match,
                        current_passage=passages.get(passage_match.current_passage_id),
                        previous_passage=passages.get(passage_match.previous_passage_id),
                        current_section=section_by_id.get(section_match.current_section_id),
                        previous_section=section_by_id.get(section_match.previous_section_id),
                    )
                    if change is not None:
                        changes.append(change)
            stored_changes = await self.comparisons.replace_changes(comparison.id, changes)
            metrics = {
                "sections_matched": len(
                    [
                        match
                        for match in stored_section_matches
                        if match.match_type
                        not in {"unmatched_current", "unmatched_previous"}
                    ]
                ),
                "unmatched_sections": len(
                    [
                        match
                        for match in stored_section_matches
                        if match.match_type.startswith("unmatched")
                    ]
                ),
                "passage_matches": len(all_passage_matches),
                "findings_generated": len(stored_changes),
                "model_calls": len(all_passage_matches),
            }
            comparison.matching_model_name = self.matcher.embeddings.model_name
            comparison.matching_model_version = self.matcher.embeddings.model_version
            comparison.change_model_name = self.change_detector.classifier.model_name
            comparison.change_model_version = self.change_detector.classifier.model_version
            await self.comparisons.set_status(comparison, "completed", metrics=metrics)
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            comparison = await self.comparisons.get_comparison(comparison_id)
            if comparison is not None:
                await self.comparisons.set_status(
                    comparison,
                    "failed",
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                )
                await self.session.commit()
            raise

    async def _segment_sections(self, sections: list[FilingSection]) -> None:
        for section in sections:
            units = self.segmenter.segment_section(section)
            await self.comparisons.get_or_create_passages(
                section.id,
                units,
                segmentation_version=self.settings.passage_segmentation_version,
            )
        await self.session.flush()

    async def _passages(self, section_id: uuid.UUID | None):
        if section_id is None:
            return []
        return await self.comparisons.list_passages_for_section(
            section_id,
            segmentation_version=self.settings.passage_segmentation_version,
        )

    async def _has_parsed_content(self, filing_id: uuid.UUID) -> bool:
        section_count = await self.session.scalar(
            select(func.count())
            .select_from(FilingSection)
            .where(FilingSection.filing_id == filing_id)
        )
        chunk_count = await self.session.scalar(
            select(func.count())
            .select_from(FilingChunk)
            .join(FilingSection)
            .where(FilingSection.filing_id == filing_id)
        )
        return bool(section_count and chunk_count)


def _period(filing: Filing) -> date:
    return filing.report_period or filing.filing_date
