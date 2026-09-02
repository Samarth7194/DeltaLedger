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


@pytest.mark.asyncio
async def test_embed_documents_persists_completed_batches_before_a_later_failure() -> None:
    class _FlakyProvider:
        model_name = "flaky"
        model_version = "v1"
        dimension = 2

        def __init__(self) -> None:
            self.calls = 0

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("rate limited")
            return [[1.0, 0.0] for _ in texts]

        async def embed_query(self, text: str) -> list[float]:
            return [1.0, 0.0]

    provider = _FlakyProvider()
    service = EmbeddingService(provider, expected_dimension=2, batch_size=1)
    persisted: list[tuple[list[str], list[list[float]]]] = []

    async def on_batch(batch_texts: list[str], batch_vectors: list[list[float]]) -> None:
        persisted.append((batch_texts, batch_vectors))

    with pytest.raises(RuntimeError):
        await service.embed_documents(["a", "b", "c"], on_batch=on_batch)

    assert persisted == [(["a"], [[1.0, 0.0]])]
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_embed_documents_paces_successful_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.embeddings.asyncio.sleep", _record_sleep)
    service = EmbeddingService(
        DeterministicFakeEmbeddingProvider(dimension=2),
        expected_dimension=2,
        batch_size=2,
        batch_delay_seconds=0.75,
    )

    vectors = await service.embed_documents(["a", "b", "c", "d", "e"])

    assert len(vectors) == 5
    assert sleep_calls == [0.75, 0.75]


@pytest.mark.asyncio
async def test_embed_documents_does_not_sleep_after_final_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.embeddings.asyncio.sleep", _record_sleep)
    service = EmbeddingService(
        DeterministicFakeEmbeddingProvider(dimension=2),
        expected_dimension=2,
        batch_size=2,
        batch_delay_seconds=0.75,
    )

    await service.embed_documents(["a", "b", "c", "d"])

    assert sleep_calls == [0.75]


@pytest.mark.asyncio
async def test_embed_documents_one_batch_has_no_pacing_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.ai.embeddings.asyncio.sleep", _record_sleep)
    service = EmbeddingService(
        DeterministicFakeEmbeddingProvider(dimension=2),
        expected_dimension=2,
        batch_size=16,
        batch_delay_seconds=0.75,
    )

    await service.embed_documents(["a"])

    assert sleep_calls == []


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
