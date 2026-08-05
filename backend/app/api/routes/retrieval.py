from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import create_embedding_service
from app.ai.reranker import create_reranker
from app.api.schemas import (
    ResponseEnvelope,
    ResponseMeta,
    RetrievalRequest,
    RetrievalResultResponse,
)
from app.core.config import get_settings
from app.db.session import get_session
from app.repositories.chunk_repository import ChunkRepository
from app.services.retrieval_service import HybridSearchRequest, RetrievalService

router = APIRouter(prefix="/retrieval")
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/search")
async def hybrid_search(
    request: RetrievalRequest,
    http_request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    service = _service(session)
    results = await service.hybrid_search(_to_service_request(request))
    return ResponseEnvelope(
        data=[_hybrid_result(result).model_dump() for result in results],
        meta=_meta(http_request),
    )


@router.post("/dense-search")
async def dense_search(
    request: RetrievalRequest,
    http_request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    service = _service(session)
    results = await service.dense_search(_to_service_request(request))
    return ResponseEnvelope(
        data=[
            RetrievalResultResponse(
                chunk_id=result.chunk_id,
                filing_id=result.filing_id,
                section_id=result.section_id,
                company_id=result.company_id,
                text=result.text,
                dense_score=result.score,
                final_score=result.score,
                source=result.source_metadata,
            ).model_dump()
            for result in results
        ],
        meta=_meta(http_request),
    )


@router.post("/lexical-search")
async def lexical_search(
    request: RetrievalRequest,
    http_request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    service = _service(session)
    results = await service.lexical_search(_to_service_request(request))
    return ResponseEnvelope(
        data=[
            RetrievalResultResponse(
                chunk_id=result.chunk_id,
                filing_id=result.filing_id,
                section_id=result.section_id,
                company_id=result.company_id,
                text=result.text,
                lexical_score=result.score,
                final_score=result.score,
                source=result.source_metadata,
            ).model_dump()
            for result in results
        ],
        meta=_meta(http_request),
    )


def _meta(request: Request) -> ResponseMeta:
    return ResponseMeta(request_id=getattr(request.state, "request_id", None))


def _service(session: AsyncSession) -> RetrievalService:
    settings = get_settings()
    return RetrievalService(
        chunks=ChunkRepository(session),
        embeddings=create_embedding_service(settings),
        reranker=create_reranker(settings),
        reranker_candidate_limit=settings.reranker_candidate_limit,
    )


def _to_service_request(request: RetrievalRequest) -> HybridSearchRequest:
    return HybridSearchRequest(**request.model_dump())


def _hybrid_result(result: object) -> RetrievalResultResponse:
    return RetrievalResultResponse(
        chunk_id=result.chunk_id,
        filing_id=result.filing_id,
        section_id=result.section_id,
        company_id=result.company_id,
        text=result.text,
        dense_score=result.dense_score,
        lexical_score=result.lexical_score,
        fusion_score=result.fusion_score,
        reranker_score=result.reranker_score,
        final_score=result.final_score,
        source=result.source,
    )
