from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UuidPrimaryKeyMixin


class FilingComparison(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "filing_comparisons"
    __table_args__ = (
        CheckConstraint(
            "current_filing_id <> comparison_filing_id",
            name="filing_comparison_distinct_filings",
        ),
        UniqueConstraint(
            "current_filing_id",
            "comparison_filing_id",
            "comparison_version",
            name="uq_comparison_pair_version",
        ),
        Index(
            "ix_comparisons_company_pair",
            "company_id",
            "current_filing_id",
            "comparison_filing_id",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    current_filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filings.id"), nullable=False
    )
    comparison_filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filings.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", server_default="queued")
    comparison_version: Mapped[str] = mapped_column(String(64), nullable=False)
    matching_model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matching_model_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    change_model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    change_model_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_metrics: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )

    section_matches = relationship("SectionMatch", cascade="all, delete-orphan")
    disclosure_changes = relationship("DisclosureChange", cascade="all, delete-orphan")


class SectionMatch(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "section_matches"
    __table_args__ = (
        UniqueConstraint(
            "comparison_id",
            "current_section_id",
            "previous_section_id",
            name="uq_section_match_pair",
        ),
        Index("ix_section_matches_comparison", "comparison_id"),
    )

    comparison_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_comparisons.id", ondelete="CASCADE"), nullable=False
    )
    current_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_sections.id", ondelete="CASCADE"), nullable=True
    )
    previous_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_sections.id", ondelete="CASCADE"), nullable=True
    )
    match_type: Mapped[str] = mapped_column(String(32), nullable=False)
    heading_similarity: Mapped[float | None] = mapped_column(nullable=True)
    dense_similarity: Mapped[float | None] = mapped_column(nullable=True)
    lexical_similarity: Mapped[float | None] = mapped_column(nullable=True)
    reranker_score: Mapped[float | None] = mapped_column(nullable=True)
    structural_score: Mapped[float | None] = mapped_column(nullable=True)
    combined_score: Mapped[float] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    match_reason: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    review_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    passage_matches = relationship("PassageMatch", cascade="all, delete-orphan")


class PassageUnit(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "passage_units"
    __table_args__ = (
        UniqueConstraint(
            "filing_section_id",
            "unit_type",
            "unit_index",
            "segmentation_version",
            name="uq_passage_unit_version",
        ),
        Index("ix_passage_units_section", "filing_section_id", "unit_index"),
    )

    filing_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_sections.id", ondelete="CASCADE"), nullable=False
    )
    unit_type: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_index: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_char_start: Mapped[int] = mapped_column(nullable=False)
    raw_char_end: Mapped[int] = mapped_column(nullable=False)
    normalized_char_start: Mapped[int] = mapped_column(nullable=False)
    normalized_char_end: Mapped[int] = mapped_column(nullable=False)
    source_anchor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_element_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    segmentation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}", nullable=False
    )


class PassageMatch(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "passage_matches"
    __table_args__ = (
        UniqueConstraint(
            "section_match_id",
            "current_passage_id",
            "previous_passage_id",
            name="uq_passage_match_pair",
        ),
        Index("ix_passage_matches_section_match", "section_match_id"),
    )

    section_match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("section_matches.id", ondelete="CASCADE"), nullable=False
    )
    current_passage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passage_units.id", ondelete="CASCADE"), nullable=True
    )
    previous_passage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passage_units.id", ondelete="CASCADE"), nullable=True
    )
    alignment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    dense_similarity: Mapped[float | None] = mapped_column(nullable=True)
    lexical_similarity: Mapped[float | None] = mapped_column(nullable=True)
    reranker_score: Mapped[float | None] = mapped_column(nullable=True)
    sequence_score: Mapped[float | None] = mapped_column(nullable=True)
    combined_score: Mapped[float | None] = mapped_column(nullable=True)
    confidence: Mapped[float] = mapped_column(nullable=False)
    alignment_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )


class DisclosureChange(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "disclosure_changes"
    __table_args__ = (
        Index("ix_disclosure_changes_type", "comparison_id", "change_type"),
        Index("ix_disclosure_changes_risk", "comparison_id", "risk_category"),
        Index("ix_disclosure_changes_materiality", "comparison_id", "materiality_score"),
    )

    comparison_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_comparisons.id", ondelete="CASCADE"), nullable=False
    )
    section_match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("section_matches.id", ondelete="CASCADE"), nullable=False
    )
    passage_match_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passage_matches.id", ondelete="CASCADE"), nullable=True
    )
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_category: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_spans: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    change_summary: Mapped[str] = mapped_column(Text, nullable=False)
    change_explanation: Mapped[str] = mapped_column(Text, nullable=False)
    materiality_score: Mapped[float] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    detection_method: Mapped[str] = mapped_column(String(32), nullable=False)
    supporting_evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    materiality_components: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    original_model_output: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_edits: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
