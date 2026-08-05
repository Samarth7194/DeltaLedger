from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.ai.embeddings import EmbeddingService
from app.ai.reranker import RerankerProvider
from app.repositories.chunk_repository import (
    ChunkRepository,
    RetrievalChunkResult,
    RetrievalFilters,
)


@dataclass(frozen=True)
class HybridSearchRequest:
    query: str
    company_id: uuid.UUID | None = None
    filing_ids: list[uuid.UUID] | None = None
    section_types: list[str] | None = None
    part_numbers: list[str] | None = None
    item_numbers: list[str] | None = None
    report_period_from: date | None = None
    report_period_to: date | None = None
    top_k: int = 10
    candidate_k: int = 40
    use_reranker: bool = True
    min_dense_similarity: float | None = None


@dataclass(frozen=True)
class HybridSearchResult:
    chunk_id: uuid.UUID
    filing_id: uuid.UUID
    section_id: uuid.UUID
    company_id: uuid.UUID
    text: str
    dense_score: float | None
    lexical_score: float | None
    fusion_score: float
    reranker_score: float | None
    final_score: float
    source: dict[str, Any]


class RetrievalService:
    def __init__(
        self,
        *,
        chunks: ChunkRepository,
        embeddings: EmbeddingService,
        reranker: RerankerProvider | None = None,
        reranker_candidate_limit: int = 40,
    ) -> None:
        self.chunks = chunks
        self.embeddings = embeddings
        self.reranker = reranker
        self.reranker_candidate_limit = reranker_candidate_limit

    async def hybrid_search(self, request: HybridSearchRequest) -> list[HybridSearchResult]:
        filters = RetrievalFilters(
            company_id=request.company_id,
            filing_ids=request.filing_ids,
            section_types=request.section_types,
            part_numbers=request.part_numbers,
            item_numbers=request.item_numbers,
            report_period_from=request.report_period_from,
            report_period_to=request.report_period_to,
        )
        query_embedding = await self.embeddings.embed_query(request.query)
        dense_results = await self.chunks.dense_search(
            query_embedding=query_embedding,
            filters=filters,
            top_k=request.candidate_k,
            min_similarity=request.min_dense_similarity,
        )
        lexical_results = await self.chunks.lexical_search(
            query=request.query,
            filters=filters,
            top_k=request.candidate_k,
        )
        fused = reciprocal_rank_fusion(dense_results, lexical_results)
        candidates = fused[: min(request.candidate_k, self.reranker_candidate_limit)]

        reranker_scores: dict[uuid.UUID, float] = {}
        if request.use_reranker and self.reranker is not None and candidates:
            reranked = await self.reranker.rerank(
                request.query,
                [candidate.text for candidate in candidates],
                top_k=min(request.top_k, len(candidates)),
            )
            reranker_scores = {
                candidates[result.index].chunk_id: result.score for result in reranked
            }
            candidates = sorted(
                candidates,
                key=lambda candidate: reranker_scores.get(
                    candidate.chunk_id,
                    candidate.fusion_score,
                ),
                reverse=True,
            )

        final_results: list[HybridSearchResult] = []
        for candidate in candidates[: request.top_k]:
            reranker_score = reranker_scores.get(candidate.chunk_id)
            final_score = reranker_score if reranker_score is not None else candidate.fusion_score
            final_results.append(
                HybridSearchResult(
                    chunk_id=candidate.chunk_id,
                    filing_id=candidate.filing_id,
                    section_id=candidate.section_id,
                    company_id=candidate.company_id,
                    text=candidate.text,
                    dense_score=candidate.dense_score,
                    lexical_score=candidate.lexical_score,
                    fusion_score=candidate.fusion_score,
                    reranker_score=reranker_score,
                    final_score=final_score,
                    source=candidate.source_metadata,
                )
            )
        return final_results

    async def dense_search(self, request: HybridSearchRequest) -> list[RetrievalChunkResult]:
        filters = RetrievalFilters(
            company_id=request.company_id,
            filing_ids=request.filing_ids,
            section_types=request.section_types,
            part_numbers=request.part_numbers,
            item_numbers=request.item_numbers,
            report_period_from=request.report_period_from,
            report_period_to=request.report_period_to,
        )
        query_embedding = await self.embeddings.embed_query(request.query)
        return await self.chunks.dense_search(
            query_embedding=query_embedding,
            filters=filters,
            top_k=request.top_k,
            min_similarity=request.min_dense_similarity,
        )

    async def lexical_search(self, request: HybridSearchRequest) -> list[RetrievalChunkResult]:
        filters = RetrievalFilters(
            company_id=request.company_id,
            filing_ids=request.filing_ids,
            section_types=request.section_types,
            part_numbers=request.part_numbers,
            item_numbers=request.item_numbers,
            report_period_from=request.report_period_from,
            report_period_to=request.report_period_to,
        )
        return await self.chunks.lexical_search(
            query=request.query,
            filters=filters,
            top_k=request.top_k,
        )


@dataclass(frozen=True)
class _FusedCandidate:
    chunk_id: uuid.UUID
    filing_id: uuid.UUID
    section_id: uuid.UUID
    company_id: uuid.UUID
    text: str
    dense_score: float | None
    lexical_score: float | None
    fusion_score: float
    source_metadata: dict[str, Any]


def reciprocal_rank_fusion(
    dense_results: list[RetrievalChunkResult],
    lexical_results: list[RetrievalChunkResult],
    *,
    rank_constant: int = 60,
) -> list[_FusedCandidate]:
    candidates: dict[uuid.UUID, dict[str, Any]] = {}

    def add_result(result: RetrievalChunkResult, source: str, rank: int) -> None:
        candidate = candidates.setdefault(
            result.chunk_id,
            {
                "result": result,
                "dense_score": None,
                "lexical_score": None,
                "fusion_score": 0.0,
            },
        )
        candidate[f"{source}_score"] = result.score
        candidate["fusion_score"] += 1.0 / (rank_constant + rank)

    for rank, result in enumerate(dense_results, start=1):
        add_result(result, "dense", rank)
    for rank, result in enumerate(lexical_results, start=1):
        add_result(result, "lexical", rank)

    fused = [
        _FusedCandidate(
            chunk_id=data["result"].chunk_id,
            filing_id=data["result"].filing_id,
            section_id=data["result"].section_id,
            company_id=data["result"].company_id,
            text=data["result"].text,
            dense_score=data["dense_score"],
            lexical_score=data["lexical_score"],
            fusion_score=data["fusion_score"],
            source_metadata=data["result"].source_metadata,
        )
        for data in candidates.values()
    ]
    return sorted(fused, key=lambda candidate: candidate.fusion_score, reverse=True)
