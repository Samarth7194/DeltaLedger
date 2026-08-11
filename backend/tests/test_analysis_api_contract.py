from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import create_app

RUN_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
COMPANY_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
CURRENT_FILING_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
PREVIOUS_FILING_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
COMPARISON_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")
REVIEW_ID = uuid.UUID("88888888-8888-4888-8888-888888888888")
REPORT_ID = uuid.UUID("99999999-9999-4999-8999-999999999999")


@dataclass
class FakeRun:
    id: uuid.UUID = RUN_ID
    company_id: uuid.UUID = COMPANY_ID
    current_filing_id: uuid.UUID = CURRENT_FILING_ID
    comparison_filing_id: uuid.UUID = PREVIOUS_FILING_ID
    comparison_id: uuid.UUID | None = COMPARISON_ID
    status: str = "awaiting_human_review"
    current_node: str | None = "review_gate"
    workflow_version: str = "phase6-v1"
    graph_version: str = "phase6-langgraph-v1"
    checkpoint_thread_id: str = "internal-thread-id"
    requires_human_review: bool = True
    review_gate_reason: dict[str, object] | None = field(
        default_factory=lambda: {"reason": "Numerical contradiction candidate requires review."}
    )
    processing_metrics: dict[str, object] = field(
        default_factory=lambda: {
            "completed_nodes": ["validate_analysis_request", "run_disclosure_comparison"],
            "warnings": [],
            "disclosure_changes": 1,
        }
    )
    warnings: list[str] = field(default_factory=list)
    failure_code: str | None = None
    failure_message: str | None = None
    failure_node: str | None = None


@dataclass
class FakeEvent:
    id: uuid.UUID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    analysis_run_id: uuid.UUID = RUN_ID
    event_type: str = "node_completed"
    node_name: str | None = "run_disclosure_comparison"
    attempt_number: int | None = 1
    event_payload: dict[str, object] = field(default_factory=lambda: {"outputs": {"count": 1}})
    duration_ms: int | None = 42


@dataclass
class FakeReview:
    id: uuid.UUID = REVIEW_ID
    analysis_run_id: uuid.UUID = RUN_ID
    review_type: str = "contradiction_review"
    status: str = "approved"
    reason: str = "High severity potential inconsistency requires analyst review."
    finding_ids: list[str] = field(default_factory=lambda: ["finding-1"])
    claim_ids: list[str] = field(default_factory=lambda: ["claim-1"])
    verification_ids: list[str] = field(default_factory=lambda: ["verification-1"])
    reviewed_by: str | None = "analyst"
    review_comment: str | None = "Approved."
    review_payload: dict[str, object] | None = field(default_factory=dict)


@dataclass
class FakeReport:
    id: uuid.UUID = REPORT_ID
    analysis_run_id: uuid.UUID = RUN_ID
    report_version: str = "phase6-report-v1"
    status: str = "finalized"
    executive_summary: str = "Structured summary."
    comparison_summary: dict[str, object] = field(default_factory=lambda: {"company": "AAPL"})
    disclosure_change_summary: dict[str, object] = field(default_factory=lambda: {"count": 1})
    financial_verification_summary: dict[str, object] = field(default_factory=lambda: {"count": 1})
    contradiction_summary: dict[str, object] = field(default_factory=lambda: {"count": 1})
    high_priority_findings: list[dict[str, object]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=lambda: ["Ambiguous XBRL fact"])
    evidence_manifest: dict[str, object] = field(default_factory=lambda: {"evidence_ids": ["e1"]})
    report_payload: dict[str, object] = field(
        default_factory=lambda: {"review_outcomes": {"approved": 1}}
    )
    content_hash: str = "hash"


class FakeRepo:
    def __init__(self, _session) -> None:
        self.run = FakeRun()

    async def get_run(self, _analysis_run_id):
        return self.run

    async def list_runs(self, **_kwargs):
        return [self.run]

    async def list_events(self, _analysis_run_id, **_kwargs):
        return [FakeEvent()]

    async def get_latest_review(self, _analysis_run_id):
        return FakeReview()

    async def get_report(self, _analysis_run_id):
        return FakeReport()


class FakeService:
    def __init__(self, _session, _settings) -> None:
        self.run = FakeRun(status="queued", current_node=None, requires_human_review=False)

    async def create_analysis(self, *, current_filing_id, comparison_filing_id):
        assert current_filing_id == CURRENT_FILING_ID
        assert comparison_filing_id == PREVIOUS_FILING_ID
        return self.run, True

    async def submit_review(self, _analysis_run_id, **_kwargs):
        return FakeReview()

    async def cancel_analysis(self, _analysis_run_id):
        return FakeRun(status="cancelled", current_node=None, requires_human_review=False)


def test_analysis_api_contract_matches_frontend_consumed_shape(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.analyses.WorkflowRepository", FakeRepo)
    monkeypatch.setattr("app.api.routes.analyses.AnalysisWorkflowService", FakeService)
    monkeypatch.setattr(
        "app.api.routes.analyses.enqueue_run_analysis_workflow",
        lambda _run_id: "job-analysis",
    )
    monkeypatch.setattr(
        "app.api.routes.analyses.enqueue_resume_analysis_workflow",
        lambda _run_id, _review_id: "job-resume",
    )

    with _client() as client:
        create_response = client.post(
            "/api/v1/analyses",
            json={
                "current_filing_id": str(CURRENT_FILING_ID),
                "comparison_filing_id": str(PREVIOUS_FILING_ID),
            },
        )
        list_response = client.get("/api/v1/analyses")
        detail_response = client.get(f"/api/v1/analyses/{RUN_ID}")
        events_response = client.get(f"/api/v1/analyses/{RUN_ID}/events")
        review_response = client.get(f"/api/v1/analyses/{RUN_ID}/review")
        submit_response = client.post(
            f"/api/v1/analyses/{RUN_ID}/review",
            json={"status": "approved", "comment": "Approved."},
        )
        resume_response = client.post(f"/api/v1/analyses/{RUN_ID}/resume")
        report_response = client.get(f"/api/v1/analyses/{RUN_ID}/report")

    assert create_response.status_code == 202
    assert create_response.json()["data"]["analysis_run_id"] == str(RUN_ID)
    assert list_response.status_code == 200
    detail_payload = detail_response.json()["data"]
    assert detail_payload["id"] == str(RUN_ID)
    assert detail_payload["progress"]["progress_percent"] > 0
    assert "checkpoint_thread_id" not in detail_payload
    assert events_response.json()["data"][0]["node_name"] == "run_disclosure_comparison"
    assert review_response.json()["data"]["status"] == "approved"
    assert submit_response.json()["data"]["review_comment"] == "Approved."
    assert resume_response.status_code == 202
    assert resume_response.json()["data"]["review_request_id"] == str(REVIEW_ID)
    assert report_response.json()["data"]["evidence_manifest"]["evidence_ids"] == ["e1"]


def _client() -> TestClient:
    app = create_app()

    async def override_session():
        yield object()

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)
