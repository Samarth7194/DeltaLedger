from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UuidPrimaryKeyMixin

ANALYSIS_STATUSES = (
    "queued",
    "validating",
    "preparing_filings",
    "processing_filings",
    "comparing_disclosures",
    "extracting_claims",
    "verifying_claims",
    "analyzing_contradictions",
    "validating_evidence",
    "awaiting_human_review",
    "generating_report",
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
)
WORKFLOW_EVENT_TYPES = (
    "workflow_started",
    "node_started",
    "node_completed",
    "node_skipped",
    "node_retry",
    "node_failed",
    "workflow_interrupted",
    "workflow_resumed",
    "review_requested",
    "review_completed",
    "report_generated",
    "workflow_completed",
    "workflow_cancelled",
)
REVIEW_TYPES = (
    "contradiction_review",
    "ambiguous_financial_evidence",
    "incomplete_evidence",
    "final_analysis_review",
)
WORKFLOW_REVIEW_STATUSES = (
    "pending",
    "approved",
    "rejected",
    "partially_approved",
    "needs_changes",
    "uncertain",
)
REPORT_STATUSES = ("draft", "finalized")


def _sql_tuple(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


class AnalysisRun(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "current_filing_id <> comparison_filing_id",
            name="analysis_distinct_filings",
        ),
        CheckConstraint("status IN " + _sql_tuple(ANALYSIS_STATUSES), name="analysis_status"),
        UniqueConstraint(
            "current_filing_id",
            "comparison_filing_id",
            "workflow_version",
            name="uq_analysis_pair_workflow_version",
        ),
        UniqueConstraint("checkpoint_thread_id", name="uq_analysis_checkpoint_thread"),
        Index("ix_analysis_runs_company_created", "company_id", "created_at"),
        Index("ix_analysis_runs_status", "status"),
        Index(
            "ix_analysis_runs_filing_pair",
            "current_filing_id",
            "comparison_filing_id",
        ),
        Index("ix_analysis_runs_checkpoint_thread", "checkpoint_thread_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    current_filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filings.id", ondelete="CASCADE"), nullable=False
    )
    comparison_filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filings.id", ondelete="CASCADE"), nullable=False
    )
    comparison_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_comparisons.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(48), default="queued", server_default="queued", nullable=False
    )
    current_node: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workflow_version: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    review_gate_reason: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_node: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    processing_metrics: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    input_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )


class AnalysisWorkflowEvent(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "analysis_workflow_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN " + _sql_tuple(WORKFLOW_EVENT_TYPES),
            name="analysis_workflow_event_type",
        ),
        Index("ix_analysis_events_run_created", "analysis_run_id", "created_at"),
        Index("ix_analysis_events_node", "analysis_run_id", "node_name"),
    )

    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    node_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AnalysisReviewRequest(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis_review_requests"
    __table_args__ = (
        CheckConstraint("review_type IN " + _sql_tuple(REVIEW_TYPES), name="analysis_review_type"),
        CheckConstraint(
            "status IN " + _sql_tuple(WORKFLOW_REVIEW_STATUSES),
            name="analysis_review_status",
        ),
        Index("ix_analysis_review_run_status", "analysis_run_id", "status"),
    )

    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    review_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    finding_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    claim_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    verification_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    resume_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AnalysisReport(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis_reports"
    __table_args__ = (
        CheckConstraint("status IN " + _sql_tuple(REPORT_STATUSES), name="analysis_report_status"),
        UniqueConstraint("analysis_run_id", name="uq_analysis_reports_run"),
    )

    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    report_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False
    )
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    comparison_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    disclosure_change_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    financial_verification_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    contradiction_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    high_priority_findings: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    limitations: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    evidence_manifest: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    report_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    generator_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generator_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
