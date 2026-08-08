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


class ComparisonCreateRequest(BaseModel):
    current_filing_id: uuid.UUID
    comparison_filing_id: uuid.UUID


class ComparisonCreateResponse(BaseModel):
    comparison_id: uuid.UUID
    status: str
    job_id: str


class ComparisonSummaryResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    current_filing_id: uuid.UUID
    comparison_filing_id: uuid.UUID
    status: str
    comparison_version: str
    processing_metrics: dict[str, Any]
    summary_counts: dict[str, int]


class SectionMatchResponse(BaseModel):
    id: uuid.UUID
    comparison_id: uuid.UUID
    current_section_id: uuid.UUID | None
    previous_section_id: uuid.UUID | None
    match_type: str
    heading_similarity: float | None
    dense_similarity: float | None
    lexical_similarity: float | None
    reranker_score: float | None
    structural_score: float | None
    combined_score: float
    confidence: float
    match_reason: dict[str, Any]
    review_status: str


class PassageMatchResponse(BaseModel):
    id: uuid.UUID
    section_match_id: uuid.UUID
    current_passage_id: uuid.UUID | None
    previous_passage_id: uuid.UUID | None
    alignment_type: str
    dense_similarity: float | None
    lexical_similarity: float | None
    reranker_score: float | None
    sequence_score: float | None
    combined_score: float | None
    confidence: float
    alignment_metadata: dict[str, Any]


class DisclosureChangeResponse(BaseModel):
    id: uuid.UUID
    comparison_id: uuid.UUID
    section_match_id: uuid.UUID
    passage_match_id: uuid.UUID | None
    change_type: str
    risk_category: str
    previous_text: str | None
    current_text: str | None
    changed_spans: list[dict[str, Any]]
    change_summary: str
    change_explanation: str
    materiality_score: float
    confidence: float
    detection_method: str
    supporting_evidence: dict[str, Any]
    materiality_components: dict[str, Any]
    original_model_output: dict[str, Any]
    model_name: str | None
    model_version: str | None
    prompt_version: str | None
    review_status: str
    review_comment: str | None
    reviewer_edits: dict[str, Any]


class ChangeReviewRequest(BaseModel):
    review_status: str
    comment: str | None = None
    reviewer_id: str | None = None
    change_type: str | None = None
    risk_category: str | None = None
    summary: str | None = None


class FinancialJobResponse(BaseModel):
    entity_id: uuid.UUID
    job_id: str
    status: str


class FinancialClaimResponse(BaseModel):
    id: uuid.UUID
    filing_id: uuid.UUID
    comparison_id: uuid.UUID | None
    disclosure_change_id: uuid.UUID | None
    source_section_id: uuid.UUID
    source_passage_id: uuid.UUID | None
    claim_text: str
    canonical_metric_name: str | None
    claim_type: str
    direction: str | None
    reported_value: Any | None
    reported_unit: str | None
    reported_change: Any | None
    reported_change_unit: str | None
    comparison_basis: str | None
    comparison_text: str | None
    qualifiers: dict[str, Any]
    extraction_confidence: Any
    extraction_method: str
    original_model_output: dict[str, Any]
    model_name: str | None
    model_version: str | None
    prompt_version: str | None
    review_status: str
    review_comment: str | None
    reviewer_edits: dict[str, Any]


class ClaimFactCandidateResponse(BaseModel):
    id: uuid.UUID
    financial_claim_id: uuid.UUID
    xbrl_fact_id: uuid.UUID
    candidate_role: str
    concept_priority: int
    concept_match_score: Any
    period_match_score: Any
    unit_match_score: Any
    accession_match_score: Any
    frame_match_score: Any
    combined_score: Any
    selection_status: str
    rejection_reason: str | None


class ClaimVerificationResponse(BaseModel):
    id: uuid.UUID
    financial_claim_id: uuid.UUID
    current_xbrl_fact_id: uuid.UUID | None
    comparison_xbrl_fact_id: uuid.UUID | None
    verification_status: str
    current_value: Any | None
    comparison_value: Any | None
    absolute_change: Any | None
    percentage_change: Any | None
    percentage_point_change: Any | None
    reported_change: Any | None
    reported_vs_calculated_difference: Any | None
    calculation_type: str
    formula: str
    calculation_inputs: dict[str, Any]
    calculation_output: dict[str, Any]
    tolerance_used: Any | None
    verification_reason: str
    confidence: Any
    verification_version: str


class FinancialClaimReviewRequest(BaseModel):
    review_status: str
    comment: str | None = None
    reviewer_id: str | None = None
    canonical_metric_name: str | None = None
    reported_value: Any | None = None
    reported_unit: str | None = None
    comparison_basis: str | None = None


class ClaimFactCandidateReviewRequest(BaseModel):
    reviewer_id: str | None = None
    comment: str | None = None
