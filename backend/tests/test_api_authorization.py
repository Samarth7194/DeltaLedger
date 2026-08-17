from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app

SECRET = "0123456789abcdef0123456789abcdef"
RUN_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")


@dataclass
class FakeRun:
    id: uuid.UUID = RUN_ID
    company_id: uuid.UUID = uuid.UUID("11111111-1111-4111-8111-111111111111")
    current_filing_id: uuid.UUID = uuid.UUID("22222222-2222-4222-8222-222222222222")
    comparison_filing_id: uuid.UUID = uuid.UUID("33333333-3333-4333-8333-333333333333")
    comparison_id: uuid.UUID | None = None
    status: str = "awaiting_human_review"
    current_node: str | None = "review_gate"
    workflow_version: str = "phase6-v1"
    graph_version: str = "phase6-langgraph-v1"
    requires_human_review: bool = True
    review_gate_reason: dict[str, object] | None = field(
        default_factory=lambda: {"reason": "Review required."}
    )
    processing_metrics: dict[str, object] = field(default_factory=dict)
    failure_code: str | None = None
    failure_message: str | None = None
    failure_node: str | None = None


@dataclass
class FakeReview:
    id: uuid.UUID = uuid.UUID("88888888-8888-4888-8888-888888888888")
    analysis_run_id: uuid.UUID = RUN_ID
    review_type: str = "contradiction_review"
    status: str = "approved"
    reason: str = "High severity potential inconsistency requires analyst review."
    finding_ids: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    verification_ids: list[str] = field(default_factory=list)
    reviewed_by: str | None = "reviewer@example.com"
    review_comment: str | None = "Reviewed."
    review_payload: dict[str, object] | None = field(default_factory=dict)


class FakeWorkflowRepository:
    def __init__(self, _session) -> None:
        self.run = FakeRun()

    async def list_runs(self, **_kwargs):
        return [self.run]

    async def get_run(self, _analysis_run_id):
        return self.run

    async def get_latest_review(self, _analysis_run_id):
        return FakeReview()

    async def get_report(self, _analysis_run_id):
        return None


class FakeAnalysisWorkflowService:
    def __init__(self, _session, _settings) -> None:
        pass

    async def submit_review(self, _analysis_run_id, **_kwargs):
        return FakeReview()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/companies",
        "/api/v1/companies/11111111-1111-4111-8111-111111111111",
        "/api/v1/companies/11111111-1111-4111-8111-111111111111/filings",
        f"/api/v1/filings/{RUN_ID}/processing-status",
        f"/api/v1/filings/{RUN_ID}/sections",
        f"/api/v1/filings/{RUN_ID}/sections/11111111-1111-4111-8111-111111111111",
        f"/api/v1/filings/{RUN_ID}/tables",
        f"/api/v1/filings/{RUN_ID}/chunks",
        "/api/v1/analyses",
        f"/api/v1/analyses/{RUN_ID}",
        f"/api/v1/analyses/{RUN_ID}/events",
        f"/api/v1/analyses/{RUN_ID}/review",
        f"/api/v1/analyses/{RUN_ID}/report",
        "/api/v1/comparisons",
        f"/api/v1/comparisons/{RUN_ID}",
        f"/api/v1/comparisons/{RUN_ID}/section-matches",
        f"/api/v1/comparisons/{RUN_ID}/passage-matches",
        f"/api/v1/comparisons/{RUN_ID}/changes",
        f"/api/v1/comparisons/{RUN_ID}/changes/11111111-1111-4111-8111-111111111111",
        f"/api/v1/filings/{RUN_ID}/financial-claims",
        f"/api/v1/financial-claims/{RUN_ID}",
        f"/api/v1/financial-claims/{RUN_ID}/fact-candidates",
        f"/api/v1/financial-claims/{RUN_ID}/verification",
        f"/api/v1/comparisons/{RUN_ID}/financial-claims",
        f"/api/v1/comparisons/{RUN_ID}/financial-verifications",
        f"/api/v1/comparisons/{RUN_ID}/contradictions",
        f"/api/v1/comparisons/{RUN_ID}/contradiction-summary",
        f"/api/v1/contradictions/{RUN_ID}",
        f"/api/v1/contradictions/{RUN_ID}/evidence",
    ],
)
def test_sensitive_read_endpoints_require_authentication(path: str) -> None:
    with _client(auth_enabled=True) as client:
        response = client.get(path)

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_analyst_can_read_analysis_data_when_auth_enabled(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.analyses.WorkflowRepository", FakeWorkflowRepository)

    with _client(auth_enabled=True) as client:
        response = client.get(
            "/api/v1/analyses",
            headers=_auth_header("analyst"),
        )

    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == str(RUN_ID)


def test_analyst_cannot_submit_reviewer_action(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.analyses.WorkflowRepository", FakeWorkflowRepository)
    monkeypatch.setattr(
        "app.api.routes.analyses.AnalysisWorkflowService",
        FakeAnalysisWorkflowService,
    )

    with _client(auth_enabled=True) as client:
        response = client.post(
            f"/api/v1/analyses/{RUN_ID}/review",
            headers=_auth_header("analyst"),
            json={"status": "approved", "comment": "Reviewed."},
        )

    assert response.status_code == 403


def test_reviewer_can_submit_reviewer_action(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.analyses.WorkflowRepository", FakeWorkflowRepository)
    monkeypatch.setattr(
        "app.api.routes.analyses.AnalysisWorkflowService",
        FakeAnalysisWorkflowService,
    )

    with _client(auth_enabled=True) as client:
        response = client.post(
            f"/api/v1/analyses/{RUN_ID}/review",
            headers=_auth_header("reviewer"),
            json={"status": "approved", "comment": "Reviewed."},
        )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "approved"


def test_admin_can_submit_reviewer_action(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.analyses.WorkflowRepository", FakeWorkflowRepository)
    monkeypatch.setattr(
        "app.api.routes.analyses.AnalysisWorkflowService",
        FakeAnalysisWorkflowService,
    )

    with _client(auth_enabled=True) as client:
        response = client.post(
            f"/api/v1/analyses/{RUN_ID}/review",
            headers=_auth_header("admin"),
            json={"status": "approved", "comment": "Reviewed."},
        )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "approved"


def test_invalid_and_expired_route_tokens_are_denied(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.analyses.WorkflowRepository", FakeWorkflowRepository)
    expired = create_access_token(
        subject="analyst@example.com",
        role="analyst",
        settings=_settings(),
        issued_at=datetime.now(UTC) - timedelta(hours=2),
    )

    with _client(auth_enabled=True) as client:
        malformed = client.get("/api/v1/analyses", headers={"Authorization": "Bearer nope"})
        expired_response = client.get(
            "/api/v1/analyses",
            headers={"Authorization": f"Bearer {expired}"},
        )

    assert malformed.status_code == 401
    assert expired_response.status_code == 401
    assert expired_response.json()["detail"] == "Token expired."


def test_malformed_authorization_scheme_is_denied() -> None:
    with _client(auth_enabled=True) as client:
        response = client.get("/api/v1/analyses", headers={"Authorization": "Token nope"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def _client(*, auth_enabled: bool) -> TestClient:
    app = create_app()
    settings = _settings(auth_enabled=auth_enabled)

    async def override_settings() -> Settings:
        return settings

    async def override_session():
        yield object()

    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def _settings(*, auth_enabled: bool = True) -> Settings:
    return Settings(auth_enabled=auth_enabled, auth_secret_key=SECRET)


def _auth_header(role: str) -> dict[str, str]:
    token = create_access_token(
        subject=f"{role}@example.com",
        role=role,  # type: ignore[arg-type]
        settings=_settings(),
    )
    return {"Authorization": f"Bearer {token}"}
