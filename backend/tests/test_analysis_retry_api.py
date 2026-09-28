"""POST /analyses/{id}/retry continues the SAME failed run and refuses everything
else; the run payload says whether a failure is retryable."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.models.workflow import BATCH_STAGE_DISCLOSURE_COMPARISON as DISCLOSURE
from app.db.session import get_session
from app.main import create_app
from app.repositories.stage_batch_repository import StageProgress
from tests.test_analysis_api_contract import RUN_ID, FakeRepo, FakeRun


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _Repo(FakeRepo):
    run_kwargs: dict = {}
    events: list = []

    def __init__(self, _session) -> None:
        self.run = FakeRun(**self.run_kwargs)

    async def add_event(self, **kwargs) -> None:
        type(self).events.append(kwargs)


def _client(session: _Session) -> TestClient:
    app = create_app()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def _setup(monkeypatch, *, batches=None, **run_kwargs):
    _Repo.run_kwargs = run_kwargs
    _Repo.events = []
    enqueued: list = []
    created: list = []
    session = _Session()

    async def fake_batches(_session, _run_id):
        return batches or {}

    monkeypatch.setattr("app.api.routes.analyses.WorkflowRepository", _Repo)
    monkeypatch.setattr("app.api.routes.analyses._batch_progress", fake_batches)
    monkeypatch.setattr(
        "app.api.routes.analyses.enqueue_run_analysis_workflow",
        lambda run_id: enqueued.append(run_id) or "job-retry",
    )
    monkeypatch.setattr(
        "app.api.routes.analyses.AnalysisWorkflowService",
        lambda *_: created.append("created") or None,
    )
    return session, enqueued, created


def _failed_disclosure(**kwargs) -> dict:
    return {
        DISCLOSURE: StageProgress(
            DISCLOSURE,
            total=17,
            completed=8,
            processing=0,
            failed=1,
            pending=8,
            provider_calls=9,
            retries=0,
            **kwargs,
        )
    }


FAILED = {
    "status": "failed",
    "current_node": None,
    "failure_node": "run_disclosure_comparison",
    "failure_code": "rate_limited",
    "failure_message": "openai_compatible request failed category=rate_limited",
    "requires_human_review": False,
}


def test_a_retryable_failure_is_re_enqueued_as_the_same_run(monkeypatch) -> None:
    session, enqueued, created = _setup(
        monkeypatch,
        batches=_failed_disclosure(last_provider_error_type="rate_limited_short_term"),
        **FAILED,
    )

    with _client(session) as client:
        response = client.post(f"/api/v1/analyses/{RUN_ID}/retry")

    assert response.status_code == 202
    assert response.json()["data"]["analysis_run_id"] == str(RUN_ID)
    assert enqueued == [RUN_ID]  # the existing run, re-enqueued
    assert created == []  # no new analysis was created
    assert _Repo.events[0]["event_type"] == "workflow_resumed"
    assert _Repo.events[0]["event_payload"]["reason"] == "retry_after_failure"
    assert session.commits == 1


def test_the_run_payload_reports_whether_a_failure_is_retryable(monkeypatch) -> None:
    session, _, _ = _setup(
        monkeypatch,
        batches=_failed_disclosure(last_provider_error_type="quota_exhausted_daily"),
        **FAILED,
    )
    with _client(session) as client:
        payload = client.get(f"/api/v1/analyses/{RUN_ID}").json()["data"]

    assert payload["progress"]["retryable"] is True
    stage = payload["progress"]["stages"][0]
    assert (stage["status"], stage["retryable"]) == ("failed", True)
    assert stage["last_provider_error_type"] == "quota_exhausted_daily"


@pytest.mark.parametrize(
    "run_kwargs",
    [
        {"status": "processing_filings", "current_node": "ensure_filings_processed"},
        {"status": "comparing_disclosures", "current_node": "run_disclosure_comparison"},
        {"status": "completed", "current_node": None, "requires_human_review": False},
        {"status": "cancelled", "current_node": None},
        {"status": "queued", "current_node": None},
    ],
    ids=["processing", "comparing", "completed", "cancelled", "queued"],
)
def test_only_a_failed_run_can_be_resumed(monkeypatch, run_kwargs) -> None:
    session, enqueued, _ = _setup(monkeypatch, **run_kwargs)

    with _client(session) as client:
        response = client.post(f"/api/v1/analyses/{RUN_ID}/retry")

    assert response.status_code == 422
    assert enqueued == [] and session.commits == 0


def test_a_run_awaiting_human_review_points_to_the_review_instead(monkeypatch) -> None:
    session, enqueued, _ = _setup(monkeypatch)  # FakeRun default: awaiting_human_review

    with _client(session) as client:
        response = client.post(f"/api/v1/analyses/{RUN_ID}/retry")

    assert response.status_code == 422
    assert "human review" in response.json()["detail"]
    assert enqueued == []


def test_a_failure_that_rerunning_cannot_fix_is_refused(monkeypatch) -> None:
    session, enqueued, _ = _setup(
        monkeypatch,
        **{**FAILED, "failure_code": "analysis_incomplete", "failure_node": "prioritize_findings"},
    )

    with _client(session) as client:
        run = client.get(f"/api/v1/analyses/{RUN_ID}").json()["data"]
        response = client.post(f"/api/v1/analyses/{RUN_ID}/retry")

    assert run["progress"]["retryable"] is False
    assert response.status_code == 422 and enqueued == []


def test_a_rejected_request_failure_is_not_retryable(monkeypatch) -> None:
    session, enqueued, _ = _setup(
        monkeypatch,
        batches=_failed_disclosure(last_provider_error_type="provider_rejected"),
        **FAILED,
    )

    with _client(session) as client:
        response = client.post(f"/api/v1/analyses/{RUN_ID}/retry")

    assert response.status_code == 422 and enqueued == []


def test_retrying_an_unknown_run_is_a_404(monkeypatch) -> None:
    session, enqueued, _ = _setup(monkeypatch, **FAILED)

    async def no_run(self, _run_id):
        return None

    monkeypatch.setattr(_Repo, "get_run", no_run)
    with _client(session) as client:
        response = client.post(f"/api/v1/analyses/{RUN_ID}/retry")

    assert response.status_code == 404 and enqueued == []
