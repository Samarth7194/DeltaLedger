from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    AnalysisCreateRequest,
    AnalysisCreateResponse,
    AnalysisReportResponse,
    AnalysisReviewRequestResponse,
    AnalysisReviewSubmitRequest,
    AnalysisRunResponse,
    AnalysisWorkflowEventResponse,
    ResponseEnvelope,
    ResponseMeta,
)
from app.core.auth import AuthPrincipal, require_role
from app.db.session import get_session
from app.repositories.workflow_repository import WorkflowRepository
from app.services.analysis_workflow_service import AnalysisWorkflowService, WorkflowError
from app.workers.tasks import (
    enqueue_resume_analysis_workflow,
    enqueue_run_analysis_workflow,
)

router = APIRouter(prefix="/analyses")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AnalystDep = Annotated[AuthPrincipal, Depends(require_role("analyst"))]
ReviewerDep = Annotated[AuthPrincipal, Depends(require_role("reviewer"))]


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_analysis(
    payload: AnalysisCreateRequest,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    service = AnalysisWorkflowService(session, _settings())
    try:
        run, _ = await service.create_analysis(
            current_filing_id=payload.current_filing_id,
            comparison_filing_id=payload.comparison_filing_id,
        )
    except WorkflowError as exc:
        raise HTTPException(status_code=422, detail=_error_detail(exc)) from exc
    job_id = enqueue_run_analysis_workflow(run.id)
    data = AnalysisCreateResponse(analysis_run_id=run.id, status=run.status, job_id=job_id)
    return ResponseEnvelope(data=data.model_dump(), meta=_meta(request))


@router.get("")
async def list_analyses(
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
    company_id: uuid.UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    current_filing_id: uuid.UUID | None = None,
    comparison_filing_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResponseEnvelope:
    repo = WorkflowRepository(session)
    runs = await repo.list_runs(
        company_id=company_id,
        status=status_filter,
        current_filing_id=current_filing_id,
        comparison_filing_id=comparison_filing_id,
        limit=limit,
        offset=offset,
    )
    data = [await _run_response(repo, run) for run in runs]
    return ResponseEnvelope(
        data=[item.model_dump() for item in data],
        meta=_meta(request, {"limit": limit, "offset": offset}),
    )


@router.get("/{analysis_run_id}")
async def get_analysis(
    analysis_run_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    repo = WorkflowRepository(session)
    run = await repo.get_run(analysis_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    return ResponseEnvelope(data=(await _run_response(repo, run)).model_dump(), meta=_meta(request))


@router.get("/{analysis_run_id}/events")
async def list_analysis_events(
    analysis_run_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResponseEnvelope:
    repo = WorkflowRepository(session)
    if await repo.get_run(analysis_run_id) is None:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    events = await repo.list_events(analysis_run_id, limit=limit, offset=offset)
    return ResponseEnvelope(
        data=[_event(event).model_dump() for event in events],
        meta=_meta(request, {"limit": limit, "offset": offset}),
    )


@router.get("/{analysis_run_id}/review")
async def get_analysis_review(
    analysis_run_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    repo = WorkflowRepository(session)
    review = await repo.get_latest_review(analysis_run_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review request not found.")
    return ResponseEnvelope(data=_review(review).model_dump(), meta=_meta(request))


@router.patch("/{analysis_run_id}/review")
@router.post("/{analysis_run_id}/review")
async def submit_analysis_review(
    analysis_run_id: uuid.UUID,
    payload: AnalysisReviewSubmitRequest,
    request: Request,
    session: SessionDep,
    _principal: ReviewerDep,
) -> ResponseEnvelope:
    if payload.status not in {
        "approved",
        "rejected",
        "partially_approved",
        "needs_changes",
        "uncertain",
    }:
        raise HTTPException(status_code=422, detail="Unsupported workflow review status.")
    service = AnalysisWorkflowService(session, _settings())
    try:
        review = await service.submit_review(
            analysis_run_id,
            status=payload.status,
            reviewed_by=payload.reviewed_by,
            comment=payload.comment,
            payload=payload.review_payload,
        )
    except WorkflowError as exc:
        raise HTTPException(status_code=422, detail=_error_detail(exc)) from exc
    return ResponseEnvelope(data=_review(review).model_dump(), meta=_meta(request))


@router.post("/{analysis_run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_analysis(
    analysis_run_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: ReviewerDep,
) -> ResponseEnvelope:
    repo = WorkflowRepository(session)
    run = await repo.get_run(analysis_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    if run.status != "awaiting_human_review":
        raise HTTPException(
            status_code=422,
            detail="Analysis can only resume from awaiting human review.",
        )
    review = await repo.get_latest_review(analysis_run_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review request not found.")
    if review.status == "pending":
        raise HTTPException(status_code=422, detail="Review request is still pending.")
    job_id = enqueue_resume_analysis_workflow(analysis_run_id, review.id)
    return ResponseEnvelope(
        data={"analysis_run_id": analysis_run_id, "review_request_id": review.id, "job_id": job_id},
        meta=_meta(request),
    )


@router.get("/{analysis_run_id}/report")
async def get_analysis_report(
    analysis_run_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    report = await WorkflowRepository(session).get_report(analysis_run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Analysis report not found.")
    return ResponseEnvelope(data=_report(report).model_dump(), meta=_meta(request))


@router.post("/{analysis_run_id}/cancel")
async def cancel_analysis(
    analysis_run_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: ReviewerDep,
) -> ResponseEnvelope:
    try:
        run = await AnalysisWorkflowService(session, _settings()).cancel_analysis(analysis_run_id)
    except WorkflowError as exc:
        raise HTTPException(status_code=422, detail=_error_detail(exc)) from exc
    return ResponseEnvelope(
        data=(await _run_response(WorkflowRepository(session), run)).model_dump(),
        meta=_meta(request),
    )


async def _run_response(repo: WorkflowRepository, run: object) -> AnalysisRunResponse:
    review = await repo.get_latest_review(run.id)
    report = await repo.get_report(run.id)
    metrics = run.processing_metrics or {}
    completed_nodes = [
        str(item) for item in metrics.get("completed_nodes", []) if isinstance(item, str)
    ]
    warnings = [str(item) for item in metrics.get("warnings", [])]
    return AnalysisRunResponse(
        id=run.id,
        company_id=run.company_id,
        current_filing_id=run.current_filing_id,
        comparison_filing_id=run.comparison_filing_id,
        comparison_id=run.comparison_id,
        status=run.status,
        current_node=run.current_node,
        workflow_version=run.workflow_version,
        graph_version=run.graph_version,
        requires_human_review=run.requires_human_review,
        review_gate_reason=run.review_gate_reason,
        review_request_id=review.id if review else None,
        report_id=report.id if report else None,
        progress={
            "status": run.status,
            "current_node": run.current_node,
            "completed_nodes": completed_nodes,
            "progress_percent": _progress_percent(completed_nodes, run.status),
        },
        counts={key: value for key, value in metrics.items() if key != "completed_nodes"},
        warnings=warnings,
        failure_code=run.failure_code,
        failure_message=run.failure_message,
        failure_node=run.failure_node,
    )


def _event(event: object) -> AnalysisWorkflowEventResponse:
    return AnalysisWorkflowEventResponse(
        id=event.id,
        analysis_run_id=event.analysis_run_id,
        event_type=event.event_type,
        node_name=event.node_name,
        attempt_number=event.attempt_number,
        event_payload=event.event_payload,
        duration_ms=event.duration_ms,
    )


def _review(review: object) -> AnalysisReviewRequestResponse:
    return AnalysisReviewRequestResponse(
        id=review.id,
        analysis_run_id=review.analysis_run_id,
        review_type=review.review_type,
        status=review.status,
        reason=review.reason,
        finding_ids=review.finding_ids,
        claim_ids=review.claim_ids,
        verification_ids=review.verification_ids,
        reviewed_by=review.reviewed_by,
        review_comment=review.review_comment,
        review_payload=review.review_payload,
    )


def _report(report: object) -> AnalysisReportResponse:
    return AnalysisReportResponse(
        id=report.id,
        analysis_run_id=report.analysis_run_id,
        report_version=report.report_version,
        status=report.status,
        executive_summary=report.executive_summary,
        comparison_summary=report.comparison_summary,
        disclosure_change_summary=report.disclosure_change_summary,
        financial_verification_summary=report.financial_verification_summary,
        contradiction_summary=report.contradiction_summary,
        high_priority_findings=report.high_priority_findings,
        limitations=report.limitations,
        evidence_manifest=report.evidence_manifest,
        report_payload=report.report_payload,
        content_hash=report.content_hash,
    )


def _progress_percent(completed_nodes: list[str], run_status: str) -> int:
    if run_status in {"completed", "completed_with_warnings"}:
        return 100
    if run_status in {"failed", "cancelled"}:
        return min(99, int((len(completed_nodes) / 12) * 100))
    return min(95, int((len(completed_nodes) / 12) * 100))


def _error_detail(exc: WorkflowError) -> dict[str, str | None]:
    return {
        "category": exc.category,
        "code": exc.code,
        "message": exc.public_message,
        "node": exc.node,
    }


def _settings():
    from app.core.config import get_settings

    return get_settings()


def _meta(request: Request, pagination: dict[str, object] | None = None) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", None),
        pagination=pagination,
    )
