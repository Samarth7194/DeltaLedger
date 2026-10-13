from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.embeddings import DeterministicFakeEmbeddingProvider, EmbeddingService
from app.ai.reranker import RerankResult
from app.repositories.chunk_repository import (
    ChunkRepository,
    RetrievalChunkResult,
    RetrievalFilters,
)
from app.services.retrieval_service import (
    HybridSearchRequest,
    RetrievalService,
    reciprocal_rank_fusion,
)


def _result(chunk_id: uuid.UUID, score: float, text: str = "text") -> RetrievalChunkResult:
    return RetrievalChunkResult(
        chunk_id=chunk_id,
        filing_id=uuid.uuid4(),
        section_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        text=text,
        score=score,
        source_metadata={"section_type": "mda"},
    )


def test_reciprocal_rank_fusion_deduplicates_and_preserves_scores() -> None:
    shared = uuid.uuid4()
    dense_only = uuid.uuid4()
    lexical_only = uuid.uuid4()

    fused = reciprocal_rank_fusion(
        [_result(shared, 0.9), _result(dense_only, 0.8)],
        [_result(lexical_only, 0.7), _result(shared, 0.6)],
    )

    by_id = {result.chunk_id: result for result in fused}
    assert len(fused) == 3
    assert by_id[shared].dense_score == 0.9
    assert by_id[shared].lexical_score == 0.6
    assert fused[0].chunk_id == shared


@pytest.mark.asyncio
@pytest.mark.parametrize("search_method", ["hybrid_search", "dense_search"])
async def test_dense_retrieval_uses_query_embedding_model_and_version(search_method: str) -> None:
    chunks = SimpleNamespace(
        dense_search=AsyncMock(return_value=[]), lexical_search=AsyncMock(return_value=[])
    )
    embeddings = EmbeddingService(
        DeterministicFakeEmbeddingProvider(dimension=8), expected_dimension=8, batch_size=2
    )
    service = RetrievalService(chunks=chunks, embeddings=embeddings)

    await getattr(service, search_method)(HybridSearchRequest(query="liquidity"))

    request = chunks.dense_search.call_args.kwargs
    assert request["embedding_model"] == embeddings.model_name
    assert request["embedding_version"] == embeddings.model_version


@pytest.mark.asyncio
@pytest.mark.parametrize("scores", [(-1.0, -2.0), (0.0, 0.0)])
async def test_reranked_results_do_not_compete_with_unreranked_fusion_scores(
    scores: tuple[float, float],
) -> None:
    candidates = [_result(uuid.uuid4(), score) for score in (0.9, 0.8, 0.7)]
    chunks = SimpleNamespace(
        dense_search=AsyncMock(return_value=candidates), lexical_search=AsyncMock(return_value=[])
    )
    reranker = SimpleNamespace(
        rerank=AsyncMock(return_value=[RerankResult(1, scores[0]), RerankResult(0, scores[1])])
    )
    service = RetrievalService(
        chunks=chunks,
        embeddings=EmbeddingService(
            DeterministicFakeEmbeddingProvider(dimension=8), expected_dimension=8, batch_size=2
        ),
        reranker=reranker,
    )

    results = await service.hybrid_search(
        HybridSearchRequest(query="liquidity", top_k=2, candidate_k=3)
    )

    assert [result.chunk_id for result in results] == [
        candidates[1].chunk_id,
        candidates[0].chunk_id,
    ]
    assert [result.final_score for result in results] == list(scores)
    assert all(result.reranker_score is not None for result in results)


@pytest.mark.asyncio
async def test_disabled_reranking_preserves_fusion_order() -> None:
    candidates = [_result(uuid.uuid4(), score) for score in (0.9, 0.8, 0.7)]
    chunks = SimpleNamespace(
        dense_search=AsyncMock(return_value=candidates), lexical_search=AsyncMock(return_value=[])
    )
    reranker = SimpleNamespace(rerank=AsyncMock())
    service = RetrievalService(
        chunks=chunks,
        embeddings=EmbeddingService(
            DeterministicFakeEmbeddingProvider(dimension=8), expected_dimension=8, batch_size=2
        ),
        reranker=reranker,
    )

    results = await service.hybrid_search(
        HybridSearchRequest(query="liquidity", top_k=2, candidate_k=3, use_reranker=False)
    )

    assert [result.chunk_id for result in results] == [
        candidate.chunk_id for candidate in candidates[:2]
    ]
    assert all(result.reranker_score is None for result in results)
    reranker.rerank.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_dense_query_requires_matching_embedding_metadata() -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=[]))
    repo = ChunkRepository(session)

    await repo.dense_search(
        query_embedding=[1.0] + [0.0] * 1023,
        embedding_model="BAAI/bge-large-en-v1.5",
        embedding_version="BAAI/bge-large-en-v1.5",
        filters=RetrievalFilters(),
        top_k=5,
    )

    statement = session.execute.call_args.args[0]
    predicate = statement.whereclause.compile()
    assert "filing_chunks.embedding IS NOT NULL" in str(predicate)
    assert predicate.params["embedding_model_1"] == "BAAI/bge-large-en-v1.5"
    assert predicate.params["embedding_version_1"] == "BAAI/bge-large-en-v1.5"


@pytest.mark.asyncio
async def test_repository_lexical_query_is_independent_of_embedding_metadata() -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=[]))
    repo = ChunkRepository(session)

    await repo.lexical_search(query="liquidity", filters=RetrievalFilters(), top_k=5)

    statement = session.execute.call_args.args[0]
    predicate = str(statement.whereclause.compile())
    assert "embedding" not in predicate
