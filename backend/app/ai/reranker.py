from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import anyio

from app.core.config import Settings


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


class RerankerProvider(Protocol):
    model_name: str
    model_version: str

    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[RerankResult]: ...


@dataclass
class DeterministicFakeReranker:
    model_name: str = "deterministic-fake-reranker"
    model_version: str = "test-v1"

    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[RerankResult]:
        query_terms = set(query.lower().split())
        results = []
        for index, document in enumerate(documents):
            doc_terms = set(document.lower().split())
            denominator = len(query_terms) or 1
            score = len(query_terms & doc_terms) / denominator
            results.append(RerankResult(index=index, score=score))
        return sorted(results, key=lambda result: result.score, reverse=True)[:top_k]


class CrossEncoderReranker:
    def __init__(self, settings: Settings) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for RERANKER_PROVIDER=sentence_transformers. "
                "Install backend with the ai extra: python -m pip install -e '.[ai]'."
            ) from exc
        self.model_name = settings.reranker_model
        self.model_version = settings.reranker_model
        self.batch_size = settings.reranker_batch_size
        self._model = CrossEncoder(settings.reranker_model)

    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[RerankResult]:
        pairs = [(query, document) for document in documents]
        scores = await anyio.to_thread.run_sync(
            self._model.predict,
            pairs,
            batch_size=self.batch_size,
        )
        results = [
            RerankResult(index=index, score=float(score))
            for index, score in enumerate(scores)
        ]
        return sorted(results, key=lambda result: result.score, reverse=True)[:top_k]


def create_reranker(settings: Settings) -> RerankerProvider | None:
    if not settings.reranker_enabled:
        return None
    if settings.reranker_provider == "fake":
        return DeterministicFakeReranker()
    if settings.reranker_provider == "sentence_transformers":
        return CrossEncoderReranker(settings)
    raise ValueError(f"Unsupported reranker provider: {settings.reranker_provider}")
