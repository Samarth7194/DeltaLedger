from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

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
