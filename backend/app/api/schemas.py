from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class ResponseMeta(BaseModel):
    request_id: str | None = None
    pagination: dict[str, Any] | None = None


class ResponseEnvelope(BaseModel):
    data: Any
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
    error: dict[str, Any] | None = None


class ProcessingJobResponse(BaseModel):
    filing_id: uuid.UUID
    job_id: str
    status: str


class ProcessingStageResponse(BaseModel):
    stage_name: str
    status: str
    attempt_count: int
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    metrics: dict[str, Any]


class ProcessingStatusResponse(BaseModel):
    filing_id: uuid.UUID
    ingestion_status: str
    current_stage: str | None
    completed_stages: list[str]
    failed_stages: list[ProcessingStageResponse]
    stages: list[ProcessingStageResponse]


class SectionSummaryResponse(BaseModel):
    id: uuid.UUID
    filing_id: uuid.UUID
    section_type: str
    part_number: str | None
    item_number: str | None
    section_title: str
    section_order: int
    token_count: int
    source_anchor: str | None
    native_element_id: str | None
    dom_path: str | None
    text_hash: str
    parser_version: str | None


class SectionDetailResponse(SectionSummaryResponse):
    raw_text: str
    normalized_text: str
    metadata: dict[str, Any]


class TableSummaryResponse(BaseModel):
    id: uuid.UUID
    filing_id: uuid.UUID
    filing_section_id: uuid.UUID | None
    table_index: int
    caption: str | None
    normalized_json: dict[str, Any]
    content_hash: str
    source_anchor: str | None
    extraction_version: str


class ChunkResponse(BaseModel):
    id: uuid.UUID
    filing_section_id: uuid.UUID
    chunk_index: int
    text: str
    token_count: int
    start_offset: int
    end_offset: int
    source_reference: str
    content_hash: str | None
    parser_version: str | None
    chunker_version: str | None
    embedding_model: str | None
    embedded: bool
    metadata: dict[str, Any]


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1)
    company_id: uuid.UUID | None = None
    filing_ids: list[uuid.UUID] | None = None
    section_types: list[str] | None = None
    part_numbers: list[str] | None = None
    item_numbers: list[str] | None = None
    report_period_from: date | None = None
    report_period_to: date | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    candidate_k: int = Field(default=40, ge=1, le=200)
    use_reranker: bool = True
    min_dense_similarity: float | None = Field(default=None, ge=-1, le=1)


class RetrievalResultResponse(BaseModel):
    chunk_id: uuid.UUID
    filing_id: uuid.UUID
    section_id: uuid.UUID
    company_id: uuid.UUID
    text: str
    dense_score: float | None = None
    lexical_score: float | None = None
    fusion_score: float | None = None
    reranker_score: float | None = None
    final_score: float
    source: dict[str, Any]

