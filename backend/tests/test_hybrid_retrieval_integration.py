from __future__ import annotations

import pytest

from app.ai.embeddings import DeterministicFakeEmbeddingProvider, EmbeddingService
from app.ai.reranker import DeterministicFakeReranker
from app.repositories.chunk_repository import ChunkRepository
from app.services.retrieval_service import HybridSearchRequest, RetrievalService
from tests.integration_helpers import create_retrieval_corpus

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_hybrid_retrieval_uses_real_dense_and_lexical_queries(integration_session) -> None:
    corpus = await create_retrieval_corpus(integration_session)
    service = RetrievalService(
        chunks=ChunkRepository(integration_session),
        embeddings=EmbeddingService(
            DeterministicFakeEmbeddingProvider(dimension=1024),
            expected_dimension=1024,
            batch_size=2,
        ),
        reranker=DeterministicFakeReranker(),
    )

    results = await service.hybrid_search(
        HybridSearchRequest(
            query="customer concentration increased",
            company_id=corpus["company_id"],
            section_types=["risk_factors", "mda"],
            top_k=3,
            candidate_k=6,
            use_reranker=True,
        )
    )

    assert results[0].chunk_id == corpus["customer_chunk_id"]
    assert results[0].dense_score is not None
    assert results[0].lexical_score is not None
    assert results[0].fusion_score > 0
    assert results[0].reranker_score is not None
    assert results[0].source["section_type"] == "risk_factors"
