from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.ai.embeddings import (
    DeterministicFakeEmbeddingProvider,
    EmbeddingService,
    SentenceTransformerEmbeddingProvider,
    _coerce_hf_vectors,
    create_embedding_service,
)
from app.ai.reranker import DeterministicFakeReranker
from app.core.config import Settings


class _FakeVector:
    def __init__(self, values: list[float]) -> None:
        self.values = values

    def astype(self, dtype: type[float]) -> _FakeVector:
        return self

    def tolist(self) -> list[float]:
        return self.values


def _install_fake_sentence_transformer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dimension: int = 1024,
) -> list[Any]:
    instances: list[Any] = []

    class _FakeSentenceTransformer:
        def __init__(self, model_name: str, *, device: str) -> None:
            self.model_name = model_name
            self.device = device
            self.encoded_texts: list[str] = []
            self.encode_kwargs: list[dict[str, object]] = []
            instances.append(self)

        def get_sentence_embedding_dimension(self) -> int:
            return dimension

        def encode(
            self,
            texts: list[str],
            *,
            batch_size: int,
            normalize_embeddings: bool,
            convert_to_numpy: bool,
        ) -> list[_FakeVector]:
            self.encoded_texts.extend(texts)
            self.encode_kwargs.append(
                {
                    "batch_size": batch_size,
                    "normalize_embeddings": normalize_embeddings,
                    "convert_to_numpy": convert_to_numpy,
                }
            )
            return [_FakeVector([float(index)] * dimension) for index, _ in enumerate(texts)]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer),
    )
    return instances


def _sentence_transformer_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "embedding_provider": "sentence_transformers",
        "embedding_model": "BAAI/bge-large-en-v1.5",
        "embedding_model_name": "BAAI/bge-large-en-v1.5",
        "embedding_dimension": 1024,
        "embedding_dimensions": 1024,
        "embedding_batch_size": 16,
        "embedding_device": "cpu",
        "embedding_normalize": True,
    }
    values.update(overrides)
    return Settings(**values)


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


def test_create_embedding_service_selects_sentence_transformers_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = _install_fake_sentence_transformer(monkeypatch)

    service = create_embedding_service(_sentence_transformer_settings())

    assert isinstance(service.provider, SentenceTransformerEmbeddingProvider)
    assert service.model_name == "BAAI/bge-large-en-v1.5"
    assert instances[0].model_name == "BAAI/bge-large-en-v1.5"
    assert instances[0].device == "cpu"


@pytest.mark.asyncio
async def test_sentence_transformers_document_embedding_validates_1024_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = _install_fake_sentence_transformer(monkeypatch, dimension=1024)
    service = create_embedding_service(_sentence_transformer_settings())

    vectors = await service.embed_documents(["revenue increased", "liquidity remained strong"])

    assert len(vectors) == 2
    assert all(len(vector) == 1024 for vector in vectors)
    assert instances[0].encoded_texts == ["revenue increased", "liquidity remained strong"]
    assert instances[0].encode_kwargs == [
        {"batch_size": 16, "normalize_embeddings": True, "convert_to_numpy": True}
    ]


def test_sentence_transformers_dimension_mismatch_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_sentence_transformer(monkeypatch, dimension=768)

    with pytest.raises(ValueError, match="Embedding model dimension 768"):
        create_embedding_service(_sentence_transformer_settings())


@pytest.mark.asyncio
async def test_sentence_transformers_query_instruction_applies_only_to_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = _install_fake_sentence_transformer(monkeypatch)
    service = create_embedding_service(
        _sentence_transformer_settings(
            embedding_query_instruction="Represent this sentence for searching relevant passages: ",
        )
    )

    await service.embed_documents(["stored risk-factor passage"])
    await service.embed_query("customer concentration")

    assert instances[0].encoded_texts == [
        "stored risk-factor passage",
        "Represent this sentence for searching relevant passages: customer concentration",
    ]


@pytest.mark.asyncio
async def test_embedding_service_batches_sentence_transformer_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = _install_fake_sentence_transformer(monkeypatch)
    service = create_embedding_service(_sentence_transformer_settings(embedding_batch_size=2))

    vectors = await service.embed_documents(["a", "b", "c"])

    assert len(vectors) == 3
    assert instances[0].encode_kwargs == [
        {"batch_size": 2, "normalize_embeddings": True, "convert_to_numpy": True},
        {"batch_size": 2, "normalize_embeddings": True, "convert_to_numpy": True},
    ]


def test_production_profile_allows_local_sentence_transformer_embeddings() -> None:
    settings = Settings(
        app_profile="production",
        environment="production",
        cors_allowed_origins="https://delta-ledger.vercel.app",
        readiness_dependency_checks_enabled=True,
        auth_enabled=True,
        auth_secret_key="0123456789abcdef0123456789abcdef",
        auth_login_password="fedcba9876543210fedcba9876543210",
        workflow_checkpoint_provider="postgres",
        object_storage_provider="minio",
        minio_endpoint="https://s3.us-west-004.backblazeb2.com",
        minio_access_key="prod-access-key",
        minio_secret_key="prod-secret-key",
        sec_user_agent="DeltaLedgerAI/0.1 ops@deltaledger.local",
        database_url="postgresql+asyncpg://user:pass@db.example.com/neondb?ssl=require",
        test_database_url="postgresql+asyncpg://user:pass@db.example.com/neondb_test?ssl=require",
        redis_url="rediss://redis.example.com:6379/0",
        embedding_provider="sentence_transformers",
        embedding_model="BAAI/bge-large-en-v1.5",
        embedding_model_name="BAAI/bge-large-en-v1.5",
        embedding_dimension=1024,
        embedding_dimensions=1024,
        change_classifier_provider="openai_compatible",
        change_classifier_model="gemini-3.6-flash",
        claim_extractor_provider="openai_compatible",
        claim_extractor_model="gemini-3.6-flash",
        contradiction_classifier_provider="openai_compatible",
        contradiction_classifier_model="gemini-3.6-flash",
        ai_provider_api_key="0123456789abcdef0123456789abcdef",
        ai_provider_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    assert settings.embedding_provider == "sentence_transformers"
    assert settings.change_classifier_provider == "openai_compatible"


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
