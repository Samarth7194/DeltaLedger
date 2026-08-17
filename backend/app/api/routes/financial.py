from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ClaimFactCandidateResponse,
    ClaimFactCandidateReviewRequest,
    ClaimVerificationResponse,
    FinancialClaimResponse,
    FinancialClaimReviewRequest,
    FinancialJobResponse,
    ResponseEnvelope,
    ResponseMeta,
)
from app.core.auth import AuthPrincipal, require_role
from app.db.session import get_session
from app.repositories.financial_repository import FinancialRepository
from app.workers.tasks import (
    enqueue_extract_financial_claims,
    enqueue_verify_comparison_financials,
    enqueue_verify_financial_claim,
)

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AnalystDep = Annotated[AuthPrincipal, Depends(require_role("analyst"))]
ReviewerDep = Annotated[AuthPrincipal, Depends(require_role("reviewer"))]


@router.post("/filings/{filing_id}/financial-claims/extract", status_code=status.HTTP_202_ACCEPTED)
async def extract_filing_claims(
    filing_id: uuid.UUID,
    request: Request,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    job_id = enqueue_extract_financial_claims(filing_id)
    data = FinancialJobResponse(entity_id=filing_id, job_id=job_id, status="queued")
    return ResponseEnvelope(data=data.model_dump(), meta=_meta(request))


@router.get("/filings/{filing_id}/financial-claims")
async def list_filing_claims(
    filing_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
    canonical_metric: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ResponseEnvelope:
    claims = await FinancialRepository(session).list_claims(
        filing_id=filing_id,
        canonical_metric=canonical_metric,
        limit=limit,
        offset=offset,
    )
    return ResponseEnvelope(
        data=[_claim(claim).model_dump() for claim in claims],
        meta=_meta(request, {"limit": limit, "offset": offset}),
    )


@router.get("/financial-claims/{claim_id}")
async def get_claim(
    claim_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    claim = await FinancialRepository(session).get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Financial claim not found.")
    return ResponseEnvelope(data=_claim(claim).model_dump(), meta=_meta(request))


@router.get("/financial-claims/{claim_id}/fact-candidates")
async def list_fact_candidates(
    claim_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    repo = FinancialRepository(session)
    if await repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail="Financial claim not found.")
    candidates = await repo.list_fact_candidates(claim_id)
    return ResponseEnvelope(
        data=[_candidate(candidate).model_dump() for candidate in candidates],
        meta=_meta(request),
    )


@router.patch("/financial-claims/{claim_id}/fact-candidates/{candidate_id}/review")
async def review_fact_candidate(
    claim_id: uuid.UUID,
    candidate_id: uuid.UUID,
    payload: ClaimFactCandidateReviewRequest,
    request: Request,
    session: SessionDep,
    _principal: ReviewerDep,
) -> ResponseEnvelope:
    repo = FinancialRepository(session)
    if await repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail="Financial claim not found.")
    candidate = await repo.select_fact_candidate(
        claim_id=claim_id,
        candidate_id=candidate_id,
        reviewer_id=payload.reviewer_id,
        comment=payload.comment,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Fact candidate not found.")
    await session.commit()
    return ResponseEnvelope(data=_candidate(candidate).model_dump(), meta=_meta(request))


@router.post("/financial-claims/{claim_id}/verify", status_code=status.HTTP_202_ACCEPTED)
async def verify_claim(
    claim_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    if await FinancialRepository(session).get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail="Financial claim not found.")
    job_id = enqueue_verify_financial_claim(claim_id)
    data = FinancialJobResponse(entity_id=claim_id, job_id=job_id, status="queued")
    return ResponseEnvelope(data=data.model_dump(), meta=_meta(request))


@router.get("/financial-claims/{claim_id}/verification")
async def get_verification(
    claim_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    repo = FinancialRepository(session)
    if await repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail="Financial claim not found.")
    verification = await repo.get_verification(claim_id)
    if verification is None:
        raise HTTPException(status_code=404, detail="Claim verification not found.")
    return ResponseEnvelope(data=_verification(verification).model_dump(), meta=_meta(request))


@router.patch("/financial-claims/{claim_id}/review")
async def review_claim(
    claim_id: uuid.UUID,
    payload: FinancialClaimReviewRequest,
    request: Request,
    session: SessionDep,
    _principal: ReviewerDep,
) -> ResponseEnvelope:
    repo = FinancialRepository(session)
    claim = await repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Financial claim not found.")
    if payload.review_status not in {"pending", "approved", "rejected", "edited", "uncertain"}:
        raise HTTPException(status_code=422, detail="Unsupported review status.")
    updated = await repo.apply_claim_review(
        claim,
        review_status=payload.review_status,
        comment=payload.comment,
        reviewer_id=payload.reviewer_id,
        canonical_metric_name=payload.canonical_metric_name,
        reported_value=(
            Decimal(str(payload.reported_value)) if payload.reported_value is not None else None
        ),
        reported_unit=payload.reported_unit,
        comparison_basis=payload.comparison_basis,
    )
    await session.commit()
    return ResponseEnvelope(data=_claim(updated).model_dump(), meta=_meta(request))


@router.post(
    "/comparisons/{comparison_id}/financial-verification",
    status_code=status.HTTP_202_ACCEPTED,
)
async def verify_comparison_financials(
    comparison_id: uuid.UUID,
    request: Request,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    job_id = enqueue_verify_comparison_financials(comparison_id)
    data = FinancialJobResponse(entity_id=comparison_id, job_id=job_id, status="queued")
    return ResponseEnvelope(data=data.model_dump(), meta=_meta(request))


@router.get("/comparisons/{comparison_id}/financial-claims")
async def list_comparison_claims(
    comparison_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
    canonical_metric: str | None = None,
    filing_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ResponseEnvelope:
    claims = await FinancialRepository(session).list_claims(
        filing_id=filing_id,
        comparison_id=comparison_id,
        canonical_metric=canonical_metric,
        limit=limit,
        offset=offset,
    )
    return ResponseEnvelope(
        data=[_claim(claim).model_dump() for claim in claims],
        meta=_meta(request, {"limit": limit, "offset": offset}),
    )


@router.get("/comparisons/{comparison_id}/financial-verifications")
async def list_comparison_verifications(
    comparison_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
    verification_status: str | None = None,
    min_confidence: Decimal | None = None,
) -> ResponseEnvelope:
    verifications = await FinancialRepository(session).list_verifications(
        comparison_id=comparison_id,
        verification_status=verification_status,
        min_confidence=min_confidence,
    )
    return ResponseEnvelope(
        data=[_verification(verification).model_dump() for verification in verifications],
        meta=_meta(request),
    )


def _claim(claim: object) -> FinancialClaimResponse:
    return FinancialClaimResponse(
        id=claim.id,
        filing_id=claim.filing_id,
        comparison_id=claim.comparison_id,
        disclosure_change_id=claim.disclosure_change_id,
        source_section_id=claim.source_section_id,
        source_passage_id=claim.source_passage_id,
        claim_text=claim.claim_text,
        canonical_metric_name=claim.canonical_metric_name,
        claim_type=claim.claim_type,
        direction=claim.direction,
        reported_value=claim.reported_value,
        reported_unit=claim.reported_unit,
        reported_change=claim.reported_change,
        reported_change_unit=claim.reported_change_unit,
        comparison_basis=claim.comparison_basis,
        comparison_text=claim.comparison_text,
        qualifiers=claim.qualifiers,
        extraction_confidence=claim.extraction_confidence,
        extraction_method=claim.extraction_method,
        original_model_output=claim.original_model_output,
        model_name=claim.model_name,
        model_version=claim.model_version,
        prompt_version=claim.prompt_version,
        review_status=claim.review_status,
        review_comment=claim.review_comment,
        reviewer_edits=claim.reviewer_edits,
    )


def _candidate(candidate: object) -> ClaimFactCandidateResponse:
    return ClaimFactCandidateResponse(
        id=candidate.id,
        financial_claim_id=candidate.financial_claim_id,
        xbrl_fact_id=candidate.xbrl_fact_id,
        candidate_role=candidate.candidate_role,
        concept_priority=candidate.concept_priority,
        concept_match_score=candidate.concept_match_score,
        period_match_score=candidate.period_match_score,
        unit_match_score=candidate.unit_match_score,
        accession_match_score=candidate.accession_match_score,
        frame_match_score=candidate.frame_match_score,
        combined_score=candidate.combined_score,
        selection_status=candidate.selection_status,
        rejection_reason=candidate.rejection_reason,
    )


def _verification(verification: object) -> ClaimVerificationResponse:
    return ClaimVerificationResponse(
        id=verification.id,
        financial_claim_id=verification.financial_claim_id,
        current_xbrl_fact_id=verification.current_xbrl_fact_id,
        comparison_xbrl_fact_id=verification.comparison_xbrl_fact_id,
        verification_status=verification.verification_status,
        current_value=verification.current_value,
        comparison_value=verification.comparison_value,
        absolute_change=verification.absolute_change,
        percentage_change=verification.percentage_change,
        percentage_point_change=verification.percentage_point_change,
        reported_change=verification.reported_change,
        reported_vs_calculated_difference=verification.reported_vs_calculated_difference,
        calculation_type=verification.calculation_type,
        formula=verification.formula,
        calculation_inputs=verification.calculation_inputs,
        calculation_output=verification.calculation_output,
        tolerance_used=verification.tolerance_used,
        verification_reason=verification.verification_reason,
        confidence=verification.confidence,
        verification_version=verification.verification_version,
    )


def _meta(request: Request, pagination: dict[str, object] | None = None) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", None),
        pagination=pagination,
    )
