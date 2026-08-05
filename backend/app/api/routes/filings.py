from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ChunkResponse,
    ProcessingJobResponse,
    ProcessingStageResponse,
    ProcessingStatusResponse,
    ResponseEnvelope,
    ResponseMeta,
    SectionDetailResponse,
    SectionSummaryResponse,
    TableSummaryResponse,
)
from app.db.session import get_session
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.filing_repository import FilingRepository
from app.repositories.processing_repository import ProcessingRepository
from app.repositories.section_repository import SectionRepository
from app.workers.tasks import enqueue_process_filing

router = APIRouter(prefix="/filings")
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/{filing_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def process_filing(filing_id: uuid.UUID, request: Request) -> ResponseEnvelope:
    job_id = enqueue_process_filing(filing_id)
    data = ProcessingJobResponse(filing_id=filing_id, job_id=job_id, status="queued")
    return ResponseEnvelope(
        data=data.model_dump(),
        meta=_meta(request),
    )


@router.get("/{filing_id}/processing-status")
async def processing_status(
    filing_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    filing = await FilingRepository(session).get(filing_id)
    if filing is None:
        raise HTTPException(status_code=404, detail="Filing not found.")
    stages = await ProcessingRepository(session).list_stages(filing_id)
    stage_responses = [_stage_response(stage) for stage in stages]
    running = next((stage.stage_name for stage in stages if stage.status == "running"), None)
    data = ProcessingStatusResponse(
        filing_id=filing_id,
        ingestion_status=filing.ingestion_status,
        current_stage=running,
        completed_stages=[stage.stage_name for stage in stages if stage.status == "completed"],
        failed_stages=[_stage_response(stage) for stage in stages if stage.status == "failed"],
        stages=stage_responses,
    )
    return ResponseEnvelope(data=data.model_dump(), meta=_meta(request))


@router.get("/{filing_id}/sections")
async def list_sections(
    filing_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    sections = await SectionRepository(session).list_sections(filing_id)
    return ResponseEnvelope(
        data=[_section_summary(section).model_dump() for section in sections],
        meta=_meta(request),
    )


@router.get("/{filing_id}/sections/{section_id}")
async def get_section(
    filing_id: uuid.UUID,
    section_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    section = await SectionRepository(session).get_section(filing_id, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found.")
    data = SectionDetailResponse(
        **_section_summary(section).model_dump(),
        raw_text=section.raw_text,
        normalized_text=section.normalized_text,
        metadata=section.metadata_,
    )
    return ResponseEnvelope(data=data.model_dump(), meta=_meta(request))


@router.get("/{filing_id}/tables")
async def list_tables(
    filing_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> ResponseEnvelope:
    tables = await SectionRepository(session).list_tables(filing_id)
    data = [
        TableSummaryResponse(
            id=table.id,
            filing_id=table.filing_id,
            filing_section_id=table.filing_section_id,
            table_index=table.table_index,
            caption=table.caption,
            normalized_json=table.normalized_json,
            content_hash=table.content_hash,
            source_anchor=table.source_anchor,
            extraction_version=table.extraction_version,
        ).model_dump()
        for table in tables
    ]
    return ResponseEnvelope(data=data, meta=_meta(request))


@router.get("/{filing_id}/chunks")
async def list_chunks(
    filing_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ResponseEnvelope:
    chunks = await ChunkRepository(session).list_chunks(filing_id, limit=limit, offset=offset)
    data = [
        ChunkResponse(
            id=chunk.id,
            filing_section_id=chunk.filing_section_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            token_count=chunk.token_count,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            source_reference=chunk.source_reference,
            content_hash=chunk.content_hash,
            parser_version=chunk.parser_version,
            chunker_version=chunk.chunker_version,
            embedding_model=chunk.embedding_model,
            embedded=chunk.embedding is not None,
            metadata=chunk.metadata_,
        ).model_dump()
        for chunk in chunks
    ]
    return ResponseEnvelope(
        data=data,
        meta=_meta(request, pagination={"limit": limit, "offset": offset}),
    )


def _meta(request: Request, pagination: dict[str, object] | None = None) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", None),
        pagination=pagination,
    )


def _stage_response(stage: object) -> ProcessingStageResponse:
    return ProcessingStageResponse(
        stage_name=stage.stage_name,
        status=stage.status,
        attempt_count=stage.attempt_count,
        duration_ms=stage.duration_ms,
        error_code=stage.error_code,
        error_message=stage.error_message,
        metrics=stage.metrics,
    )


def _section_summary(section: object) -> SectionSummaryResponse:
    return SectionSummaryResponse(
        id=section.id,
        filing_id=section.filing_id,
        section_type=section.section_type,
        part_number=section.part_number,
        item_number=section.item_number,
        section_title=section.section_title,
        section_order=section.section_order,
        token_count=section.token_count,
        source_anchor=section.source_anchor,
        native_element_id=section.native_element_id,
        dom_path=section.dom_path,
        text_hash=section.text_hash,
        parser_version=section.parser_version,
    )
