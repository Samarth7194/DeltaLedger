from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, Filing, FilingChunk, FilingSection
from app.services.chunking_service import ChunkSpec


@dataclass(frozen=True)
class RetrievalFilters:
    company_id: uuid.UUID | None = None
    filing_ids: list[uuid.UUID] | None = None
    section_types: list[str] | None = None
    part_numbers: list[str] | None = None
    item_numbers: list[str] | None = None
    report_period_from: object | None = None
    report_period_to: object | None = None


@dataclass(frozen=True)
class RetrievalChunkResult:
    chunk_id: uuid.UUID
    filing_id: uuid.UUID
    section_id: uuid.UUID
    company_id: uuid.UUID
    text: str
    score: float
    source_metadata: dict[str, Any]


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_chunks(
        self,
        filing_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FilingChunk]:
        stmt = (
            select(FilingChunk)
            .join(FilingSection)
            .where(FilingSection.filing_id == filing_id)
            .order_by(FilingSection.section_order, FilingChunk.chunk_index)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def replace_chunks(
        self,
        *,
        section_by_order: dict[int, FilingSection],
        chunks: list[ChunkSpec],
    ) -> list[FilingChunk]:
        section_ids = [section.id for section in section_by_order.values()]
        existing_chunks = await self._list_chunks_for_sections(section_ids)
        if self._chunks_unchanged(existing_chunks, section_by_order, chunks):
            return existing_chunks
        if section_ids:
            await self.session.execute(
                delete(FilingChunk).where(FilingChunk.filing_section_id.in_(section_ids))
            )
        stored: list[FilingChunk] = []
        for chunk in chunks:
            section = section_by_order[chunk.filing_section_order]
            stored_chunk = FilingChunk(
                filing_section_id=section.id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                source_reference=chunk.source_reference,
                content_hash=chunk.content_hash,
                source_text_hash=chunk.source_text_hash,
                parser_version=chunk.parser_version,
                chunker_version=chunk.chunker_version,
                metadata_=chunk.metadata,
            )
            self.session.add(stored_chunk)
            stored.append(stored_chunk)
        await self.session.flush()
        return stored

    async def _list_chunks_for_sections(self, section_ids: list[uuid.UUID]) -> list[FilingChunk]:
        if not section_ids:
            return []
        stmt = (
            select(FilingChunk)
            .where(FilingChunk.filing_section_id.in_(section_ids))
            .order_by(FilingChunk.chunk_index)
        )
        return list((await self.session.scalars(stmt)).all())

    def _chunks_unchanged(
        self,
        existing_chunks: list[FilingChunk],
        section_by_order: dict[int, FilingSection],
        chunks: list[ChunkSpec],
    ) -> bool:
        if len(existing_chunks) != len(chunks):
            return False
        section_id_by_order = {
            section_order: section.id for section_order, section in section_by_order.items()
        }
        by_index = {chunk.chunk_index: chunk for chunk in existing_chunks}
        for spec in chunks:
            existing = by_index.get(spec.chunk_index)
            if existing is None:
                return False
            if existing.filing_section_id != section_id_by_order[spec.filing_section_order]:
                return False
            if existing.content_hash != spec.content_hash:
                return False
            if existing.chunker_version != spec.chunker_version:
                return False
            if existing.parser_version != spec.parser_version:
                return False
        return True

    async def update_embeddings(
        self,
        chunks: list[FilingChunk],
        vectors: list[list[float]],
        *,
        model_name: str,
        model_version: str,
    ) -> None:
        embedded_at = datetime.now(UTC)
        for chunk, vector in zip(chunks, vectors, strict=True):
            if (
                chunk.embedding is not None
                and chunk.embedding_model == model_name
                and chunk.embedding_version == model_version
            ):
                continue
            chunk.embedding = vector
            chunk.embedding_model = model_name
            chunk.embedding_version = model_version
            chunk.embedded_at = embedded_at

    async def dense_search(
        self,
        *,
        query_embedding: list[float],
        filters: RetrievalFilters,
        top_k: int,
        min_similarity: float | None = None,
    ) -> list[RetrievalChunkResult]:
        score_expr = (1 - FilingChunk.embedding.cosine_distance(query_embedding)).label("score")
        stmt = (
            select(FilingChunk, FilingSection, Filing, score_expr)
            .join(FilingSection, FilingChunk.filing_section_id == FilingSection.id)
            .join(Filing, FilingSection.filing_id == Filing.id)
            .join(Company, Filing.company_id == Company.id)
            .where(FilingChunk.embedding.is_not(None), Company.is_active.is_(True))
        )
        stmt = self._apply_filters(stmt, filters)
        if min_similarity is not None:
            stmt = stmt.where(score_expr >= min_similarity)
        stmt = stmt.order_by(score_expr.desc()).limit(top_k)
        rows = await self.session.execute(stmt)
        return [
            self._map_result(row[0], row[1], row[2], float(row[3] or 0.0))
            for row in rows
        ]

    async def lexical_search(
        self,
        *,
        query: str,
        filters: RetrievalFilters,
        top_k: int,
    ) -> list[RetrievalChunkResult]:
        ts_query = func.websearch_to_tsquery("english", query)
        score_expr = func.ts_rank_cd(FilingChunk.search_vector, ts_query).label("score")
        stmt = (
            select(FilingChunk, FilingSection, Filing, score_expr)
            .join(FilingSection, FilingChunk.filing_section_id == FilingSection.id)
            .join(Filing, FilingSection.filing_id == Filing.id)
            .join(Company, Filing.company_id == Company.id)
            .where(FilingChunk.search_vector.op("@@")(ts_query), Company.is_active.is_(True))
        )
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(score_expr.desc()).limit(top_k)
        rows = await self.session.execute(stmt)
        return [
            self._map_result(row[0], row[1], row[2], float(row[3] or 0.0))
            for row in rows
        ]

    def _apply_filters(self, stmt: Any, filters: RetrievalFilters) -> Any:
        if filters.company_id is not None:
            stmt = stmt.where(Filing.company_id == filters.company_id)
        if filters.filing_ids:
            stmt = stmt.where(Filing.id.in_(filters.filing_ids))
        if filters.section_types:
            stmt = stmt.where(FilingSection.section_type.in_(filters.section_types))
        if filters.part_numbers:
            stmt = stmt.where(FilingSection.part_number.in_(filters.part_numbers))
        if filters.item_numbers:
            stmt = stmt.where(FilingSection.item_number.in_(filters.item_numbers))
        if filters.report_period_from is not None:
            stmt = stmt.where(Filing.report_period >= filters.report_period_from)
        if filters.report_period_to is not None:
            stmt = stmt.where(Filing.report_period <= filters.report_period_to)
        stmt = stmt.where(Filing.ingestion_status.not_in(["failed"]))
        return stmt

    def _map_result(
        self,
        chunk: FilingChunk,
        section: FilingSection,
        filing: Filing,
        score: float,
    ) -> RetrievalChunkResult:
        return RetrievalChunkResult(
            chunk_id=chunk.id,
            filing_id=filing.id,
            section_id=section.id,
            company_id=filing.company_id,
            text=chunk.text,
            score=score,
            source_metadata={
                "report_period": filing.report_period.isoformat() if filing.report_period else None,
                "form_type": filing.form_type,
                "section_type": section.section_type,
                "canonical_section_type": section.canonical_section_type,
                "section_title": section.section_title,
                "part_number": section.part_number,
                "item_number": section.item_number,
                "source_anchor": chunk.source_reference,
                "chunk_index": chunk.chunk_index,
                "start_offset": chunk.start_offset,
                "end_offset": chunk.end_offset,
                "content_hash": chunk.content_hash,
                "parser_version": chunk.parser_version,
                "chunker_version": chunk.chunker_version,
                "embedding_model": chunk.embedding_model,
                "embedding_version": chunk.embedding_version,
            },
        )
