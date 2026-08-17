from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ContradictionEvidenceResponse,
    ContradictionFindingResponse,
    ContradictionJobResponse,
    ContradictionReviewRequest,
    ResponseEnvelope,
    ResponseMeta,
)
from app.core.auth import AuthPrincipal, require_role
from app.db.session import get_session
from app.repositories.comparison_repository import ComparisonRepository
from app.repositories.contradiction_repository import ContradictionRepository
from app.workers.tasks import enqueue_analyze_contradictions

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AnalystDep = Annotated[AuthPrincipal, Depends(require_role("analyst"))]
ReviewerDep = Annotated[AuthPrincipal, Depends(require_role("reviewer"))]


@router.post(
    "/comparisons/{comparison_id}/contradictions/analyze",
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_comparison_contradictions(
    comparison_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    if await ComparisonRepository(session).get_comparison(comparison_id) is None:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    job_id = enqueue_analyze_contradictions(comparison_id)
    data = ContradictionJobResponse(comparison_id=comparison_id, job_id=job_id, status="queued")
    return ResponseEnvelope(data=data.model_dump(), meta=_meta(request))


@router.get("/comparisons/{comparison_id}/contradictions")
async def list_comparison_contradictions(
    comparison_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
    contradiction_type: str | None = None,
    severity: str | None = None,
    risk_category: str | None = None,
    min_confidence: Annotated[Decimal | None, Query(ge=0, le=1)] = None,
    review_status: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResponseEnvelope:
    repo = ContradictionRepository(session)
    if await ComparisonRepository(session).get_comparison(comparison_id) is None:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    findings = await repo.list_findings(
        comparison_id=comparison_id,
        contradiction_type=contradiction_type,
        severity=severity,
        risk_category=risk_category,
        min_confidence=min_confidence,
        review_status=review_status,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return ResponseEnvelope(
        data=[_finding(finding).model_dump() for finding in findings],
        meta=_meta(request, {"limit": limit, "offset": offset}),
    )


@router.get("/comparisons/{comparison_id}/contradiction-summary")
async def get_comparison_contradiction_summary(
    comparison_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    if await ComparisonRepository(session).get_comparison(comparison_id) is None:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    summary = await ContradictionRepository(session).summarize_findings(comparison_id)
    return ResponseEnvelope(data=summary, meta=_meta(request))


@router.get("/contradictions/{finding_id}")
async def get_contradiction(
    finding_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    repo = ContradictionRepository(session)
    finding = await repo.get_finding(finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Contradiction finding not found.")
    evidence = await repo.list_evidence(finding_id)
    data = _finding(finding).model_dump()
    data["evidence"] = [_evidence(item).model_dump() for item in evidence]
    data["calculation"] = finding.deterministic_evidence.get("calculation_output", {})
    return ResponseEnvelope(data=data, meta=_meta(request))


@router.get("/contradictions/{finding_id}/evidence")
async def list_contradiction_evidence(
    finding_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    repo = ContradictionRepository(session)
    if await repo.get_finding(finding_id) is None:
        raise HTTPException(status_code=404, detail="Contradiction finding not found.")
    evidence = await repo.list_evidence(finding_id)
    return ResponseEnvelope(
        data=[_evidence(item).model_dump() for item in evidence],
        meta=_meta(request),
    )


@router.patch("/contradictions/{finding_id}/review")
async def review_contradiction(
    finding_id: uuid.UUID,
    payload: ContradictionReviewRequest,
    request: Request,
    session: SessionDep,
    _principal: ReviewerDep,
) -> ResponseEnvelope:
    repo = ContradictionRepository(session)
    finding = await repo.get_finding(finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Contradiction finding not found.")
    if payload.review_status not in {"pending", "approved", "rejected", "edited", "uncertain"}:
        raise HTTPException(status_code=422, detail="Unsupported review status.")
    updated = await repo.apply_review(
        finding,
        review_status=payload.review_status,
        comment=payload.comment,
        reviewer_id=payload.reviewer_id,
        contradiction_type=payload.contradiction_type,
        severity=payload.severity,
        risk_category=payload.risk_category,
        summary=payload.summary,
        explanation=payload.explanation,
    )
    await session.commit()
    return ResponseEnvelope(data=_finding(updated).model_dump(), meta=_meta(request))


def _finding(finding: object) -> ContradictionFindingResponse:
    return ContradictionFindingResponse(
        id=finding.id,
        company_id=finding.company_id,
        comparison_id=finding.comparison_id,
        financial_claim_id=finding.financial_claim_id,
        claim_verification_id=finding.claim_verification_id,
        disclosure_change_id=finding.disclosure_change_id,
        contradiction_type=finding.contradiction_type,
        status=finding.status,
        risk_category=finding.risk_category,
        severity=finding.severity,
        confidence=finding.confidence,
        narrative_claim=finding.narrative_claim,
        narrative_direction=finding.narrative_direction,
        measured_direction=finding.measured_direction,
        reported_value=finding.reported_value,
        calculated_value=finding.calculated_value,
        calculated_change=finding.calculated_change,
        difference=finding.difference,
        qualifier=finding.qualifier,
        finding_title=finding.finding_title,
        finding_summary=finding.finding_summary,
        finding_explanation=finding.finding_explanation,
        limitations=finding.limitations,
        deterministic_evidence=finding.deterministic_evidence,
        supporting_evidence=finding.supporting_evidence,
        severity_components=finding.severity_components,
        confidence_components=finding.confidence_components,
        detection_method=finding.detection_method,
        rule_ids=finding.rule_ids,
        model_name=finding.model_name,
        model_version=finding.model_version,
        prompt_version=finding.prompt_version,
        original_model_output=finding.original_model_output,
        review_status=finding.review_status,
        review_comment=finding.review_comment,
        reviewed_by=finding.reviewed_by,
        reviewer_edits=finding.reviewer_edits,
    )


def _evidence(evidence: object) -> ContradictionEvidenceResponse:
    return ContradictionEvidenceResponse(
        id=evidence.id,
        contradiction_finding_id=evidence.contradiction_finding_id,
        evidence_type=evidence.evidence_type,
        filing_id=evidence.filing_id,
        section_id=evidence.section_id,
        passage_id=evidence.passage_id,
        xbrl_fact_id=evidence.xbrl_fact_id,
        financial_claim_id=evidence.financial_claim_id,
        claim_verification_id=evidence.claim_verification_id,
        disclosure_change_id=evidence.disclosure_change_id,
        derived_metric_id=evidence.derived_metric_id,
        source_text=evidence.source_text,
        source_hash=evidence.source_hash,
        source_anchor=evidence.source_anchor,
        evidence_role=evidence.evidence_role,
        metadata=evidence.metadata_,
    )


def _meta(request: Request, pagination: dict[str, object] | None = None) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", None),
        pagination=pagination,
    )
