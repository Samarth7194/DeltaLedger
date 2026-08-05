from __future__ import annotations

import pytest

from app.ai.embeddings import (
    DeterministicFakeEmbeddingProvider,
    EmbeddingService,
    _coerce_hf_vectors,
)
from app.ai.reranker import DeterministicFakeReranker


@pytest.mark.asyncio
async def test_embedding_service_batches_and_validates_dimension() -> None:
    service = EmbeddingService(
        DeterministicFakeEmbeddingProvider(dimension=8),
        expected_dimension=8,
        batch_size=2,
    )

    vectors = await service.embed_documents(["revenue", "liquidity", "debt"])

    assert len(vectors) == 3
    assert all(len(vector) == 8 for vector in vectors)


def test_embedding_service_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValueError):
        EmbeddingService(
            DeterministicFakeEmbeddingProvider(dimension=4),
            expected_dimension=8,
            batch_size=2,
        )


def test_hugging_face_embedding_shape_coercion_mean_pools_tokens() -> None:
    vectors = _coerce_hf_vectors(
        [
            [[1.0, 3.0], [3.0, 5.0]],
            [[2.0, 4.0], [4.0, 6.0]],
        ]
    )

    assert vectors == [[2.0, 4.0], [3.0, 5.0]]


@pytest.mark.asyncio
async def test_fake_reranker_orders_by_query_overlap() -> None:
    reranker = DeterministicFakeReranker()

    results = await reranker.rerank(
        "customer concentration increased",
        ["debt decreased", "customer concentration increased materially"],
        top_k=2,
    )

    assert results[0].index == 1
    assert results[0].score > results[1].score
