from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import anyio
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.ai.openai_compatible import OpenAICompatibleClient
from app.core.config import Settings
from app.core.exceptions import DeltaLedgerError


class EmbeddingProvider(Protocol):
    model_name: str
    model_version: str
    dimension: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


@dataclass
class DeterministicFakeEmbeddingProvider:
    dimension: int = 1024
    model_name: str = "deterministic-fake-embedding"
    model_version: str = "test-v1"

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        values: list[float] = []
        seed = text.encode("utf-8")
        counter = 0
        while len(values) < self.dimension:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            values.extend((byte / 127.5) - 1.0 for byte in digest)
            counter += 1
        vector = values[: self.dimension]
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class SentenceTransformerEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for EMBEDDING_PROVIDER=sentence_transformers. "
                "Install backend with the ai extra: python -m pip install -e '.[ai]'."
            ) from exc
        self.model_name = settings.embedding_model
        self.model_version = settings.embedding_model
        self.dimension = settings.embedding_dimension
        self.batch_size = settings.embedding_batch_size
        self.normalize = settings.embedding_normalize
        self.query_instruction = settings.embedding_query_instruction or ""
        self._model = SentenceTransformer(
            settings.embedding_model,
            device=settings.embedding_device,
        )
        model_dimension = int(self._model.get_sentence_embedding_dimension())
        if model_dimension != self.dimension:
            raise ValueError(
                f"Embedding model dimension {model_dimension} does not match "
                f"configured PGVector dimension {self.dimension}."
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=8),
        retry=retry_if_exception_type(RuntimeError),
        reraise=True,
    )
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await anyio.to_thread.run_sync(self._encode, texts)

    async def embed_query(self, text: str) -> list[float]:
        query_text = f"{self.query_instruction}{text}" if self.query_instruction else text
        return (await self.embed_documents([query_text]))[0]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,
            convert_to_numpy=True,
        )
        return [vector.astype(float).tolist() for vector in vectors]


class HuggingFaceInferenceEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.hf_token:
            raise DeltaLedgerError(
                "HF_TOKEN is required for EMBEDDING_PROVIDER=huggingface_inference."
            )
        self.model_name = settings.embedding_model
        self.model_version = settings.embedding_model
        self.dimension = settings.embedding_dimension
        self.batch_size = settings.embedding_batch_size
        self.normalize = settings.embedding_normalize
        self.timeout = settings.embedding_timeout_seconds
        base_url = settings.hf_inference_base_url.rstrip("/")
        model_path = quote(settings.embedding_model, safe="")
        self.url = f"{base_url}/pipeline/feature-extraction/{model_path}"
        self.headers = {"Authorization": f"Bearer {settings.hf_token}"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=8),
        retry=retry_if_exception_type((httpx.HTTPError, DeltaLedgerError)),
        reraise=True,
    )
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        payload = {"inputs": texts, "options": {"wait_for_model": True}}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, headers=self.headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise DeltaLedgerError(
                f"Hugging Face inference request failed with status {exc.response.status_code}."
            ) from exc
        data = response.json()
        vectors = _coerce_hf_vectors(data)
        if len(vectors) != len(texts):
            raise DeltaLedgerError("Hugging Face inference returned an unexpected vector count.")
        if self.normalize:
            vectors = [_normalize_vector(vector) for vector in vectors]
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.embedding_model
        self.model_version = settings.embedding_model
        self.dimension = settings.embedding_dimension
        self.batch_size = settings.embedding_batch_size
        self.normalize = settings.embedding_normalize
        self._client = OpenAICompatibleClient(settings, provider_type="embedding")
        self.last_metadata: dict[str, object] | None = None

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors, metadata = await self._client.embeddings(
            model=self.model_name,
            inputs=texts,
            dimensions=self.dimension,
        )
        if self.normalize:
            vectors = [_normalize_vector(vector) for vector in vectors]
        self.last_metadata = metadata.model_dump()
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


class EmbeddingService:
    def __init__(
        self,
        provider: EmbeddingProvider,
        *,
        expected_dimension: int,
        batch_size: int,
        batch_delay_seconds: float = 0.0,
    ) -> None:
        self.provider = provider
        self.expected_dimension = expected_dimension
        self.batch_size = batch_size
        self.batch_delay_seconds = batch_delay_seconds
        if provider.dimension != expected_dimension:
            raise ValueError(
                f"Embedding provider dimension {provider.dimension} does not match "
                f"expected dimension {expected_dimension}."
            )

    async def embed_documents(
        self,
        texts: list[str],
        *,
        on_batch: Callable[[list[str], list[list[float]]], Awaitable[None]] | None = None,
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        batches = _batches(texts, self.batch_size)
        for index, batch in enumerate(batches):
            batch_vectors = await self.provider.embed_documents(batch)
            self._validate_vectors(batch_vectors, len(batch))
            vectors.extend(batch_vectors)
            if on_batch is not None:
                await on_batch(batch, batch_vectors)
            if self.batch_delay_seconds > 0 and index < len(batches) - 1:
                await asyncio.sleep(self.batch_delay_seconds)
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        vector = await self.provider.embed_query(text)
        self._validate_vector(vector)
        return vector

    @property
    def model_name(self) -> str:
        return self.provider.model_name

    @property
    def model_version(self) -> str:
        return self.provider.model_version

    def _validate_vectors(self, vectors: list[list[float]], expected_count: int) -> None:
        if len(vectors) != expected_count:
            raise ValueError("Embedding provider returned an unexpected number of vectors.")
        for vector in vectors:
            self._validate_vector(vector)

    def _validate_vector(self, vector: Sequence[float]) -> None:
        if len(vector) != self.expected_dimension:
            raise ValueError(
                f"Embedding vector has dimension {len(vector)}; expected {self.expected_dimension}."
            )


def create_embedding_service(settings: Settings) -> EmbeddingService:
    if settings.embedding_provider == "fake":
        provider: EmbeddingProvider = DeterministicFakeEmbeddingProvider(
            settings.embedding_dimension
        )
    elif settings.embedding_provider == "huggingface_inference":
        provider = HuggingFaceInferenceEmbeddingProvider(settings)
    elif settings.embedding_provider == "openai_compatible":
        provider = OpenAICompatibleEmbeddingProvider(settings)
    elif settings.embedding_provider == "sentence_transformers":
        provider = SentenceTransformerEmbeddingProvider(settings)
    else:
        raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")
    return EmbeddingService(
        provider,
        expected_dimension=settings.embedding_dimension,
        batch_size=settings.embedding_batch_size,
        batch_delay_seconds=settings.embedding_batch_delay_seconds,
    )


def _batches(items: list[str], batch_size: int) -> list[list[str]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _coerce_hf_vectors(data: object) -> list[list[float]]:
    if not isinstance(data, list):
        raise DeltaLedgerError("Hugging Face inference returned a non-list response.")
    if data and isinstance(data[0], list) and data[0] and isinstance(data[0][0], list):
        return [_mean_pool(tokens) for tokens in data]  # type: ignore[arg-type]
    if data and isinstance(data[0], list):
        return [[float(value) for value in vector] for vector in data]  # type: ignore[union-attr]
    raise DeltaLedgerError("Hugging Face inference returned an unsupported embedding shape.")


def _mean_pool(token_vectors: list[list[float]]) -> list[float]:
    if not token_vectors:
        raise DeltaLedgerError("Hugging Face inference returned an empty token embedding.")
    dimension = len(token_vectors[0])
    pooled = [0.0] * dimension
    for token_vector in token_vectors:
        if len(token_vector) != dimension:
            raise DeltaLedgerError("Hugging Face inference returned ragged token embeddings.")
        for index, value in enumerate(token_vector):
            pooled[index] += float(value)
    return [value / len(token_vectors) for value in pooled]


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]
