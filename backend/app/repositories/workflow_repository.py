from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalysisReport,
    AnalysisReviewRequest,
    AnalysisRun,
    AnalysisWorkflowEvent,
    Filing,
)


class WorkflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def try_acquire_run_lock(self, analysis_run_id: uuid.UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(func.pg_try_advisory_lock(advisory_lock_key(analysis_run_id)))
            )
        )

    async def release_run_lock(self, analysis_run_id: uuid.UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(func.pg_advisory_unlock(advisory_lock_key(analysis_run_id)))
            )
        )

    async def get_run(self, analysis_run_id: uuid.UUID) -> AnalysisRun | None:
        return await self.session.get(AnalysisRun, analysis_run_id)

    async def create_or_get_run(
        self,
        *,
        current_filing: Filing,
        comparison_filing: Filing,
        workflow_version: str,
        graph_version: str,
    ) -> tuple[AnalysisRun, bool]:
        stmt = select(AnalysisRun).where(
            AnalysisRun.current_filing_id == current_filing.id,
            AnalysisRun.comparison_filing_id == comparison_filing.id,
            AnalysisRun.workflow_version == workflow_version,
        )
        existing = await self.session.scalar(stmt)
        if existing is not None:
            return existing, False
        run = AnalysisRun(
            company_id=current_filing.company_id,
            current_filing_id=current_filing.id,
            comparison_filing_id=comparison_filing.id,
            status="queued",
            workflow_version=workflow_version,
            graph_version=graph_version,
            checkpoint_thread_id=_thread_id(
                current_filing.id,
                comparison_filing.id,
                workflow_version,
            ),
            input_snapshot={
                "current_filing_id": str(current_filing.id),
                "comparison_filing_id": str(comparison_filing.id),
                "workflow_version": workflow_version,
            },
            processing_metrics={},
        )
        self.session.add(run)
        await self.session.flush()
        return run, True

    async def list_runs(
        self,
        *,
        company_id: uuid.UUID | None = None,
        status: str | None = None,
        current_filing_id: uuid.UUID | None = None,
        comparison_filing_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AnalysisRun]:
        stmt = select(AnalysisRun).order_by(AnalysisRun.created_at.desc())
        if company_id is not None:
            stmt = stmt.where(AnalysisRun.company_id == company_id)
        if status is not None:
            stmt = stmt.where(AnalysisRun.status == status)
        if current_filing_id is not None:
            stmt = stmt.where(AnalysisRun.current_filing_id == current_filing_id)
        if comparison_filing_id is not None:
            stmt = stmt.where(AnalysisRun.comparison_filing_id == comparison_filing_id)
        stmt = stmt.offset(offset).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def set_run_status(
        self,
        run: AnalysisRun,
        status: str,
        *,
        current_node: str | None = None,
        metrics: dict[str, object] | None = None,
        comparison_id: uuid.UUID | None = None,
        requires_human_review: bool | None = None,
        review_gate_reason: dict[str, object] | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
        failure_node: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        run.status = status
        run.current_node = current_node
        if run.started_at is None and status != "queued":
            run.started_at = now
        if status in {"completed", "completed_with_warnings", "failed", "cancelled"}:
            run.completed_at = now
        else:
            run.completed_at = None
        if metrics is not None:
            run.processing_metrics = {**(run.processing_metrics or {}), **metrics}
        if comparison_id is not None:
            run.comparison_id = comparison_id
        if requires_human_review is not None:
            run.requires_human_review = requires_human_review
        if review_gate_reason is not None:
            run.review_gate_reason = review_gate_reason
        run.failure_code = failure_code
        run.failure_message = failure_message
        run.failure_node = failure_node
        await self.session.flush()

    async def add_event(
        self,
        *,
        analysis_run_id: uuid.UUID,
        event_type: str,
        node_name: str | None = None,
        attempt_number: int | None = None,
        event_payload: dict[str, object] | None = None,
        duration_ms: int | None = None,
    ) -> AnalysisWorkflowEvent:
        event = AnalysisWorkflowEvent(
            analysis_run_id=analysis_run_id,
            event_type=event_type,
            node_name=node_name,
            attempt_number=attempt_number,
            event_payload=event_payload or {},
            duration_ms=duration_ms,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_events(
        self,
        analysis_run_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AnalysisWorkflowEvent]:
        stmt = (
            select(AnalysisWorkflowEvent)
            .where(AnalysisWorkflowEvent.analysis_run_id == analysis_run_id)
            .order_by(AnalysisWorkflowEvent.created_at, AnalysisWorkflowEvent.id)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_pending_review(
        self,
        analysis_run_id: uuid.UUID,
    ) -> AnalysisReviewRequest | None:
        stmt = (
            select(AnalysisReviewRequest)
            .where(
                AnalysisReviewRequest.analysis_run_id == analysis_run_id,
                AnalysisReviewRequest.status == "pending",
            )
            .order_by(AnalysisReviewRequest.created_at.desc())
        )
        return await self.session.scalar(stmt)

    async def get_latest_review(
        self,
        analysis_run_id: uuid.UUID,
    ) -> AnalysisReviewRequest | None:
        stmt = (
            select(AnalysisReviewRequest)
            .where(AnalysisReviewRequest.analysis_run_id == analysis_run_id)
            .order_by(AnalysisReviewRequest.created_at.desc())
        )
        return await self.session.scalar(stmt)

    async def create_review_request(
        self,
        *,
        analysis_run_id: uuid.UUID,
        review_type: str,
        reason: str,
        finding_ids: list[uuid.UUID],
        claim_ids: list[uuid.UUID],
        verification_ids: list[uuid.UUID],
    ) -> AnalysisReviewRequest:
        pending = await self.get_pending_review(analysis_run_id)
        if pending is not None:
            return pending
        request = AnalysisReviewRequest(
            analysis_run_id=analysis_run_id,
            review_type=review_type,
            status="pending",
            reason=reason,
            finding_ids=[str(item) for item in finding_ids],
            claim_ids=[str(item) for item in claim_ids],
            verification_ids=[str(item) for item in verification_ids],
            requested_at=datetime.now(UTC),
        )
        self.session.add(request)
        await self.session.flush()
        return request

    async def submit_review(
        self,
        request: AnalysisReviewRequest,
        *,
        status: str,
        reviewed_by: str | None,
        comment: str | None,
        payload: dict[str, object] | None,
    ) -> AnalysisReviewRequest:
        request.status = status
        request.reviewed_by = reviewed_by
        request.review_comment = comment
        request.review_payload = payload or {}
        request.reviewed_at = datetime.now(UTC)
        await self.session.flush()
        return request

    async def upsert_report(self, report: AnalysisReport) -> AnalysisReport:
        existing = await self.session.scalar(
            select(AnalysisReport).where(AnalysisReport.analysis_run_id == report.analysis_run_id)
        )
        if existing is None:
            self.session.add(report)
            await self.session.flush()
            return report
        for key in (
            "report_version",
            "status",
            "executive_summary",
            "comparison_summary",
            "disclosure_change_summary",
            "financial_verification_summary",
            "contradiction_summary",
            "high_priority_findings",
            "limitations",
            "evidence_manifest",
            "report_payload",
            "generator_name",
            "generator_version",
            "prompt_version",
            "generated_at",
            "finalized_at",
            "content_hash",
        ):
            setattr(existing, key, getattr(report, key))
        await self.session.flush()
        return existing

    async def get_report(self, analysis_run_id: uuid.UUID) -> AnalysisReport | None:
        stmt = select(AnalysisReport).where(AnalysisReport.analysis_run_id == analysis_run_id)
        return await self.session.scalar(stmt)


def advisory_lock_key(analysis_run_id: uuid.UUID) -> int:
    return analysis_run_id.int % (2**62 - 1) + (2**59)


def _thread_id(
    current_filing_id: uuid.UUID,
    comparison_filing_id: uuid.UUID,
    workflow_version: str,
) -> str:
    payload = {
        "current_filing_id": str(current_filing_id),
        "comparison_filing_id": str(comparison_filing_id),
        "workflow_version": workflow_version,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"analysis-{digest[:48]}"
