from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.embeddings import DeterministicFakeEmbeddingProvider, EmbeddingService
from app.ai.reranker import DeterministicFakeReranker
from app.db.session import get_session
from app.main import create_app
from app.repositories.chunk_repository import ChunkRepository
from app.services.retrieval_service import RetrievalService
from tests.integration_helpers import create_retrieval_corpus

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_retrieval_api_returns_real_database_records(integration_session) -> None:
    corpus = await create_retrieval_corpus(integration_session)
    app = create_app()

    async def override_session():
        yield integration_session

    def override_service(session):
        return RetrievalService(
            chunks=ChunkRepository(session),
            embeddings=EmbeddingService(
                DeterministicFakeEmbeddingProvider(dimension=1024),
                expected_dimension=1024,
                batch_size=2,
            ),
            reranker=DeterministicFakeReranker(),
        )

    app.dependency_overrides[get_session] = override_session
    from app.api.routes import retrieval

    original_service = retrieval._service
    retrieval._service = override_service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/retrieval/search",
                json={
                    "query": "customer concentration increased",
                    "company_id": str(corpus["company_id"]),
                    "section_types": ["risk_factors", "mda"],
                    "top_k": 2,
                    "candidate_k": 6,
                    "use_reranker": True,
                },
            )
    finally:
        retrieval._service = original_service
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"][0]["chunk_id"] == str(corpus["customer_chunk_id"])
    assert payload["data"][0]["dense_score"] is not None
    assert payload["data"][0]["lexical_score"] is not None
    assert payload["data"][0]["fusion_score"] is not None
    assert payload["data"][0]["reranker_score"] is not None
    assert payload["data"][0]["source"]["section_type"] == "risk_factors"
