from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ChangeReviewRequest,
    ComparisonCreateRequest,
    ComparisonCreateResponse,
    ComparisonSummaryResponse,
    DisclosureChangeResponse,
    PassageMatchResponse,
    ResponseEnvelope,
    ResponseMeta,
    SectionMatchResponse,
)
from app.core.auth import AuthPrincipal, require_role
from app.core.config import get_settings
from app.db.session import get_session
from app.repositories.comparison_repository import ComparisonRepository
from app.services.filing_comparison_service import FilingComparisonError, FilingComparisonService
from app.workers.tasks import enqueue_process_comparison

router = APIRouter(prefix="/comparisons")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AnalystDep = Annotated[AuthPrincipal, Depends(require_role("analyst"))]
ReviewerDep = Annotated[AuthPrincipal, Depends(require_role("reviewer"))]


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_comparison(
    payload: ComparisonCreateRequest,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    service = FilingComparisonService(session, get_settings())
    try:
        result = await service.create_comparison(
            current_filing_id=payload.current_filing_id,
            comparison_filing_id=payload.comparison_filing_id,
        )
    except FilingComparisonError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    job_id = enqueue_process_comparison(result.comparison_id)
    data = ComparisonCreateResponse(
        comparison_id=result.comparison_id,
        status=result.status,
        job_id=job_id,
    )
    return ResponseEnvelope(data=data.model_dump(), meta=_meta(request))


@router.get("")
async def list_comparisons(
    request: Request,
    session: SessionDep,
    company_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    current_filing_id: uuid.UUID | None = None,
    comparison_filing_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ResponseEnvelope:
    repo = ComparisonRepository(session)
    comparisons = await repo.list_comparisons(
        company_id=company_id,
        status=status_filter,
        current_filing_id=current_filing_id,
        comparison_filing_id=comparison_filing_id,
        limit=limit,
        offset=offset,
    )
    data = [await _comparison_summary(repo, comparison) for comparison in comparisons]
    return ResponseEnvelope(
        data=[item.model_dump() for item in data],
        meta=_meta(request, {"limit": limit, "offset": offset}),
    )


@router.get("/{comparison_id}")
async def get_comparison(
    comparison_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    repo = ComparisonRepository(session)
    comparison = await repo.get_comparison(comparison_id)
    if comparison is None:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    data = await _comparison_summary(repo, comparison)
    return ResponseEnvelope(data=data.model_dump(), meta=_meta(request))


@router.get("/{comparison_id}/section-matches")
async def list_section_matches(
    comparison_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    repo = ComparisonRepository(session)
    await _require_comparison(repo, comparison_id)
    matches = await repo.list_section_matches(comparison_id)
    return ResponseEnvelope(
        data=[_section_match(match).model_dump() for match in matches],
        meta=_meta(request),
    )


@router.get("/{comparison_id}/passage-matches")
async def list_passage_matches(
    comparison_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    repo = ComparisonRepository(session)
    await _require_comparison(repo, comparison_id)
    matches = await repo.list_passage_matches(comparison_id)
    return ResponseEnvelope(
        data=[_passage_match(match).model_dump() for match in matches],
        meta=_meta(request),
    )


@router.get("/{comparison_id}/changes")
async def list_changes(
    comparison_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    change_type: str | None = None,
    risk_category: str | None = None,
    min_materiality: float | None = Query(default=None, ge=0.0, le=1.0),
    review_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ResponseEnvelope:
    repo = ComparisonRepository(session)
    await _require_comparison(repo, comparison_id)
    changes = await repo.list_changes(
        comparison_id,
        change_type=change_type,
        risk_category=risk_category,
        min_materiality=min_materiality,
        review_status=review_status,
        limit=limit,
        offset=offset,
    )
    return ResponseEnvelope(
        data=[_change(change).model_dump() for change in changes],
        meta=_meta(request, {"limit": limit, "offset": offset}),
    )


@router.get("/{comparison_id}/changes/{change_id}")
async def get_change(
    comparison_id: uuid.UUID,
    change_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    repo = ComparisonRepository(session)
    change = await repo.get_change(comparison_id, change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found.")
    return ResponseEnvelope(data=_change(change).model_dump(), meta=_meta(request))


@router.patch("/{comparison_id}/changes/{change_id}/review")
async def review_change(
    comparison_id: uuid.UUID,
    change_id: uuid.UUID,
    payload: ChangeReviewRequest,
    request: Request,
    session: SessionDep,
    _principal: ReviewerDep,
) -> ResponseEnvelope:
    repo = ComparisonRepository(session)
    change = await repo.get_change(comparison_id, change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found.")
    if payload.review_status not in {"approved", "rejected", "edited", "uncertain", "pending"}:
        raise HTTPException(status_code=422, detail="Unsupported review status.")
    updated = await repo.apply_review(
        change,
        review_status=payload.review_status,
        comment=payload.comment,
        reviewer_id=payload.reviewer_id,
        change_type=payload.change_type,
        risk_category=payload.risk_category,
        summary=payload.summary,
    )
    await session.commit()
    return ResponseEnvelope(data=_change(updated).model_dump(), meta=_meta(request))


async def _require_comparison(repo: ComparisonRepository, comparison_id: uuid.UUID) -> None:
    if await repo.get_comparison(comparison_id) is None:
        raise HTTPException(status_code=404, detail="Comparison not found.")


async def _comparison_summary(
    repo: ComparisonRepository,
    comparison: object,
) -> ComparisonSummaryResponse:
    return ComparisonSummaryResponse(
        id=comparison.id,
        company_id=comparison.company_id,
        current_filing_id=comparison.current_filing_id,
        comparison_filing_id=comparison.comparison_filing_id,
        status=comparison.status,
        comparison_version=comparison.comparison_version,
        processing_metrics=comparison.processing_metrics,
        summary_counts=await repo.summarize_changes(comparison.id),
    )


def _section_match(match: object) -> SectionMatchResponse:
    return SectionMatchResponse(
        id=match.id,
        comparison_id=match.comparison_id,
        current_section_id=match.current_section_id,
        previous_section_id=match.previous_section_id,
        match_type=match.match_type,
        heading_similarity=match.heading_similarity,
        dense_similarity=match.dense_similarity,
        lexical_similarity=match.lexical_similarity,
        reranker_score=match.reranker_score,
        structural_score=match.structural_score,
        combined_score=match.combined_score,
        confidence=match.confidence,
        match_reason=match.match_reason,
        review_status=match.review_status,
    )


def _passage_match(match: object) -> PassageMatchResponse:
    return PassageMatchResponse(
        id=match.id,
        section_match_id=match.section_match_id,
        current_passage_id=match.current_passage_id,
        previous_passage_id=match.previous_passage_id,
        alignment_type=match.alignment_type,
        dense_similarity=match.dense_similarity,
        lexical_similarity=match.lexical_similarity,
        reranker_score=match.reranker_score,
        sequence_score=match.sequence_score,
        combined_score=match.combined_score,
        confidence=match.confidence,
        alignment_metadata=match.alignment_metadata,
    )


def _change(change: object) -> DisclosureChangeResponse:
    return DisclosureChangeResponse(
        id=change.id,
        comparison_id=change.comparison_id,
        section_match_id=change.section_match_id,
        passage_match_id=change.passage_match_id,
        change_type=change.change_type,
        risk_category=change.risk_category,
        previous_text=change.previous_text,
        current_text=change.current_text,
        changed_spans=change.changed_spans,
        change_summary=change.change_summary,
        change_explanation=change.change_explanation,
        materiality_score=change.materiality_score,
        confidence=change.confidence,
        detection_method=change.detection_method,
        supporting_evidence=change.supporting_evidence,
        materiality_components=change.materiality_components,
        original_model_output=change.original_model_output,
        model_name=change.model_name,
        model_version=change.model_version,
        prompt_version=change.prompt_version,
        review_status=change.review_status,
        review_comment=change.review_comment,
        reviewer_edits=change.reviewer_edits,
    )


def _meta(request: Request, pagination: dict[str, object] | None = None) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", None),
        pagination=pagination,
    )
