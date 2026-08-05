from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.main import create_app


def test_process_endpoint_returns_202_and_request_id(monkeypatch) -> None:
    filing_id = uuid.uuid4()
    monkeypatch.setattr(
        "app.api.routes.filings.enqueue_process_filing",
        lambda _filing_id: "job-123",
    )
    with TestClient(create_app()) as client:
        response = client.post(
            f"/api/v1/filings/{filing_id}/process",
            headers={"X-Request-ID": "req-test"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["data"]["job_id"] == "job-123"
    assert payload["meta"]["request_id"] == "req-test"
    assert response.headers["X-Request-ID"] == "req-test"


def test_hybrid_retrieval_endpoint_returns_scored_chunks(monkeypatch) -> None:
    chunk_id = uuid.uuid4()
    filing_id = uuid.uuid4()
    section_id = uuid.uuid4()
    company_id = uuid.uuid4()

    @dataclass(frozen=True)
    class FakeResult:
        chunk_id: uuid.UUID
        filing_id: uuid.UUID
        section_id: uuid.UUID
        company_id: uuid.UUID
        text: str
        dense_score: float
        lexical_score: float
        fusion_score: float
        reranker_score: float
        final_score: float
        source: dict[str, object]

    class FakeService:
        async def hybrid_search(self, _request):
            return [
                FakeResult(
                    chunk_id=chunk_id,
                    filing_id=filing_id,
                    section_id=section_id,
                    company_id=company_id,
                    text="customer concentration increased",
                    dense_score=0.84,
                    lexical_score=0.71,
                    fusion_score=0.039,
                    reranker_score=0.91,
                    final_score=0.91,
                    source={"section_type": "risk_factors"},
                )
            ]

    monkeypatch.setattr("app.api.routes.retrieval._service", lambda _session: FakeService())
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/retrieval/search",
            json={"query": "customer concentration increased", "top_k": 1},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"][0]["chunk_id"] == str(chunk_id)
    assert payload["data"][0]["final_score"] == 0.91
    assert payload["data"][0]["source"]["section_type"] == "risk_factors"
