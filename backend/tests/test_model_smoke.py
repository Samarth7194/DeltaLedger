from __future__ import annotations

import math
import os

import pytest

from app.ai.embeddings import create_embedding_service
from app.ai.reranker import create_reranker
from app.core.config import Settings

pytestmark = [pytest.mark.model_smoke, pytest.mark.slow]


@pytest.mark.asyncio
async def test_real_embedding_model_smoke() -> None:
    settings = Settings(
        embedding_provider="sentence_transformers",
        embedding_model="BAAI/bge-m3",
        embedding_model_name="BAAI/bge-m3",
        embedding_dimension=1024,
        embedding_dimensions=1024,
        embedding_normalize=True,
    )
    service = create_embedding_service(settings)

    document_vectors = await service.embed_documents(
        ["customer concentration increased", "debt decreased"]
    )
    query_vector = await service.embed_query("customer concentration")

    assert len(document_vectors) == 2
    assert all(len(vector) == 1024 for vector in document_vectors)
    assert len(query_vector) == 1024
    assert math.isclose(math.sqrt(sum(value * value for value in query_vector)), 1.0, rel_tol=1e-3)


@pytest.mark.asyncio
async def test_real_reranker_model_smoke() -> None:
    settings = Settings(
        reranker_enabled=True,
        reranker_provider="sentence_transformers",
        reranker_model="BAAI/bge-reranker-base",
    )
    reranker = create_reranker(settings)
    assert reranker is not None

    results = await reranker.rerank(
        "customer concentration increased",
        ["customer concentration increased during the quarter", "weather was sunny"],
        top_k=2,
    )

    assert len(results) == 2
    assert results[0].index == 0
    assert results[0].score > results[1].score


@pytest.mark.hosted_model
@pytest.mark.asyncio
async def test_hugging_face_inference_embedding_smoke() -> None:
    token = os.getenv("HF_TOKEN")
    if not token:
        pytest.skip("set HF_TOKEN to run hosted Hugging Face inference smoke test")
    settings = Settings(
        embedding_provider="huggingface_inference",
        hf_token=token,
        embedding_model="BAAI/bge-m3",
        embedding_model_name="BAAI/bge-m3",
        embedding_dimension=1024,
        embedding_dimensions=1024,
        embedding_normalize=True,
    )
    service = create_embedding_service(settings)

    vectors = await service.embed_documents(["customer concentration increased"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 1024
