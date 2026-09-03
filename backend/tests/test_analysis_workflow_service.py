from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.ai.openai_compatible import ProviderRequestError
from app.api.routes.analyses import _progress_percent
from app.core.config import Settings
from app.db.models import ContradictionFinding
from app.services.analysis_workflow_service import (
    AnalysisWorkflowService,
    WorkflowError,
    _checkpoint_conninfo,
    _checkpoint_database_url,
    create_workflow_checkpointer,
)


def test_review_policy_requires_numerical_contradiction() -> None:
    service = AnalysisWorkflowService.__new__(AnalysisWorkflowService)
    service.settings = Settings()

    requires_review, reason = service._review_policy(
        [_finding("numerical_claim_contradiction", "low", Decimal("0.9500"))]
    )

    assert requires_review is True
    assert "Numerical contradiction" in reason["reason"]


def test_review_policy_uses_severity_and_confidence_thresholds() -> None:
    service = AnalysisWorkflowService.__new__(AnalysisWorkflowService)
    service.settings = Settings(
        workflow_review_min_severity="high",
        workflow_review_low_confidence_threshold=0.70,
    )

    high_review, _ = service._review_policy(
        [_finding("magnitude_overstatement", "high", Decimal("0.9000"))]
    )
    low_confidence_review, _ = service._review_policy(
        [_finding("magnitude_understatement", "low", Decimal("0.5000"))]
    )
    no_review, reason = service._review_policy(
        [_finding("magnitude_understatement", "low", Decimal("0.9000"))]
    )

    assert high_review is True
    assert low_confidence_review is True
    assert no_review is False
    assert "No workflow-level review" in reason["reason"]


@pytest.mark.asyncio
async def test_memory_checkpointer_is_allowed_for_non_production_tests() -> None:
    checkpointer = await create_workflow_checkpointer(
        Settings(environment="test", workflow_checkpoint_provider="memory")
    )

    assert checkpointer is not None


def test_checkpoint_conninfo_normalizes_sqlalchemy_driver_urls() -> None:
    assert _checkpoint_conninfo("postgresql+psycopg://user@host/db") == (
        "postgresql://user@host/db"
    )
    assert _checkpoint_conninfo("postgresql+asyncpg://user@host/db") == (
        "postgresql://user@host/db"
    )
    assert _checkpoint_conninfo("postgresql+asyncpg://user@host/db?ssl=require") == (
        "postgresql://user@host/db?sslmode=require"
    )


def test_checkpoint_database_url_uses_runtime_database_not_alembic_url() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://user@host/runtime_db",
        alembic_database_url="postgresql+psycopg://user@host/migration_db",
    )

    assert _checkpoint_database_url(settings) == "postgresql://user@host/runtime_db"


@pytest.mark.asyncio
async def test_resume_rejects_submitted_review_when_run_is_not_waiting() -> None:
    run_id = uuid.uuid4()
    review_id = uuid.uuid4()
    service = AnalysisWorkflowService.__new__(AnalysisWorkflowService)
    service.workflow = _WorkflowForResumeGuard(
        run=SimpleNamespace(id=run_id, status="completed"),
        review=SimpleNamespace(id=review_id, status="approved", review_payload={}),
    )

    with pytest.raises(WorkflowError) as exc:
        await service.resume_analysis(run_id, review_id)

    assert exc.value.code == "resume_not_allowed"


@pytest.mark.parametrize(
    ("completed", "status", "expected"),
    [
        ([], "queued", 0),
        (["validate_analysis_request"] * 6, "verifying_claims", 50),
        (["x"], "completed", 100),
    ],
)
def test_progress_percent_uses_defined_stages(
    completed: list[str],
    status: str,
    expected: int,
) -> None:
    assert _progress_percent(completed, status) == expected


class _MissingGreenletError(RuntimeError):
    """Stands in for sqlalchemy.exc.MissingGreenlet without needing a real
    async engine/greenlet context to reproduce it."""


class _ExpiringRun:
    """Mimics an ORM object that SQLAlchemy has expired (e.g. because a
    nested service rolled back the shared session), where a plain
    synchronous attribute read on `current_node` would trigger an implicit
    lazy refresh outside the async greenlet context. `refresh()` mirrors
    what an explicit, awaited re-fetch does in real async SQLAlchemy:
    repopulate the object so subsequent reads are safe again.
    """

    def __init__(self, *, run_id: uuid.UUID, checkpoint_thread_id: str, current_node: str) -> None:
        self.id = run_id
        self.checkpoint_thread_id = checkpoint_thread_id
        self.started_at = None
        self._current_node = current_node
        self._expired = False

    def expire(self) -> None:
        self._expired = True

    def refresh(self) -> None:
        self._expired = False

    @property
    def current_node(self) -> str:
        if self._expired:
            raise _MissingGreenletError(
                "greenlet_spawn has not been called; can't call await_only() here"
            )
        return self._current_node

    @current_node.setter
    def current_node(self, value: str | None) -> None:
        self._current_node = value
        self._expired = False


class _FakeWorkflowRepoForGreenletTest:
    def __init__(self, run: _ExpiringRun) -> None:
        self._run = run
        self.get_run_calls = 0

    async def get_run(self, _analysis_run_id: uuid.UUID) -> _ExpiringRun:
        self.get_run_calls += 1
        # A real `await self.session.get(...)` transparently repopulates an
        # expired object as part of the awaited call.
        self._run.refresh()
        return self._run

    async def set_run_status(self, run: _ExpiringRun, status: str, **kwargs: object) -> None:
        run.status = status
        run.failure_code = kwargs.get("failure_code")
        run.failure_message = kwargs.get("failure_message")
        run.failure_node = kwargs.get("failure_node")


class _FakeSessionForGreenletTest:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class _FakeGraphRaisingProviderError:
    """Simulates a node whose own service (e.g. FilingComparisonService)
    rolls back the shared session before re-raising a provider failure --
    which is exactly what expires every ORM object sharing that session."""

    def __init__(self, run: _ExpiringRun, error: Exception) -> None:
        self._run = run
        self._error = error

    async def ainvoke(self, state: dict[str, object], config: dict[str, object]) -> None:
        self._run.expire()
        raise self._error


@pytest.mark.asyncio
async def test_invoke_graph_reports_provider_error_without_missing_greenlet() -> None:
    run = _ExpiringRun(
        run_id=uuid.uuid4(),
        checkpoint_thread_id="analysis-thread-1",
        current_node="run_disclosure_comparison",
    )
    provider_error = ProviderRequestError(
        "OpenAI-compatible provider request failed after 5 attempt(s): quota exceeded",
        provider="openai_compatible",
        provider_type="disclosure_change_classifier",
        model="gemini-3.6-flash",
        status_code=429,
        retry_count=5,
        retry_after_seconds=34.7,
        error_category="rate_limited",
    )
    service = AnalysisWorkflowService.__new__(AnalysisWorkflowService)
    service.workflow = _FakeWorkflowRepoForGreenletTest(run)
    service.session = _FakeSessionForGreenletTest()

    async def _fake_compile_graph():
        return _FakeGraphRaisingProviderError(run, provider_error)

    service._compile_graph = _fake_compile_graph

    with pytest.raises(ProviderRequestError) as exc_info:
        await service._invoke_graph(run, {"analysis_run_id": str(run.id)})

    # The original provider failure must survive -- not get replaced by a
    # MissingGreenlet-style crash from reading the now-expired `run`.
    assert exc_info.value is provider_error
    assert run.status == "failed"
    assert run.failure_code == "rate_limited"
    # Recovered via an explicit, awaited re-fetch rather than the stale
    # in-memory attribute -- proving the node the failure happened on was
    # still captured correctly.
    assert run.failure_node == "run_disclosure_comparison"
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_invoke_graph_reports_workflow_error_without_missing_greenlet() -> None:
    run = _ExpiringRun(
        run_id=uuid.uuid4(),
        checkpoint_thread_id="analysis-thread-2",
        current_node="run_disclosure_comparison",
    )
    workflow_error = WorkflowError(
        "fatal_internal_error", "ValueError", "Analysis workflow failed unexpectedly."
    )
    service = AnalysisWorkflowService.__new__(AnalysisWorkflowService)
    service.workflow = _FakeWorkflowRepoForGreenletTest(run)
    service.session = _FakeSessionForGreenletTest()

    async def _fake_compile_graph():
        return _FakeGraphRaisingProviderError(run, workflow_error)

    service._compile_graph = _fake_compile_graph

    with pytest.raises(WorkflowError) as exc_info:
        await service._invoke_graph(run, {"analysis_run_id": str(run.id)})

    assert exc_info.value is workflow_error
    assert run.status == "failed"


def _finding(
    contradiction_type: str,
    severity: str,
    confidence: Decimal,
) -> ContradictionFinding:
    return ContradictionFinding(
        company_id=uuid.uuid4(),
        comparison_id=uuid.uuid4(),
        contradiction_type=contradiction_type,
        status="candidate",
        severity=severity,
        confidence=confidence,
        finding_title="Review candidate",
        finding_summary="Potential inconsistency requires review.",
        finding_explanation="Evidence-backed candidate.",
        limitations=[],
        deterministic_evidence={},
        supporting_evidence={},
        severity_components={},
        confidence_components={},
        detection_method="rule_based",
        rule_ids=[],
        original_system_finding={},
        finding_fingerprint=uuid.uuid4().hex,
        review_status="pending",
        reviewer_edits={},
    )


class _WorkflowForResumeGuard:
    def __init__(self, *, run: SimpleNamespace, review: SimpleNamespace) -> None:
        self.run = run
        self.review = review

    async def get_run(self, _analysis_run_id: uuid.UUID) -> SimpleNamespace:
        return self.run

    async def get_latest_review(self, _analysis_run_id: uuid.UUID) -> SimpleNamespace:
        return self.review
