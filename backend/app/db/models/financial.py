from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UuidPrimaryKeyMixin


class FinancialMetricDefinition(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "financial_metric_definitions"
    __table_args__ = (Index("uq_financial_metric_canonical_name", "canonical_name", unique=True),)

    canonical_name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(32), nullable=False)
    period_behavior: Mapped[str] = mapped_column(String(32), nullable=False)
    preferred_unit_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class FinancialMetricConcept(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "financial_metric_concepts"
    __table_args__ = (
        Index("ix_financial_metric_concepts_metric", "metric_definition_id", "priority"),
        Index("ix_financial_metric_concepts_concept", "taxonomy", "concept"),
    )

    metric_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("financial_metric_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    taxonomy: Mapped[str] = mapped_column(String(64), nullable=False)
    concept: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    period_behavior: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class FinancialClaim(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "financial_claims"
    __table_args__ = (
        Index("ix_financial_claims_filing_metric", "filing_id", "canonical_metric_name"),
        Index("ix_financial_claims_comparison", "comparison_id"),
        Index("ix_financial_claims_source_passage", "source_passage_id"),
    )

    filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filings.id", ondelete="CASCADE"), nullable=False
    )
    comparison_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_comparisons.id", ondelete="CASCADE")
    )
    disclosure_change_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("disclosure_changes.id", ondelete="SET NULL")
    )
    source_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_sections.id", ondelete="CASCADE"), nullable=False
    )
    source_passage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passage_units.id", ondelete="SET NULL")
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_metric_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metric_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_metric_definitions.id", ondelete="SET NULL")
    )
    claim_type: Mapped[str] = mapped_column(String(48), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reported_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    reported_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reported_change: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    reported_change_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comparison_basis: Mapped[str | None] = mapped_column(String(48), nullable=True)
    comparison_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualifiers: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    extraction_confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
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


class ClaimFactCandidate(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "claim_fact_candidates"
    __table_args__ = (
        Index("ix_claim_fact_candidates_claim_role", "financial_claim_id", "candidate_role"),
        Index("ix_claim_fact_candidates_fact", "xbrl_fact_id"),
    )

    financial_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_claims.id", ondelete="CASCADE"), nullable=False
    )
    xbrl_fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("xbrl_facts.id", ondelete="CASCADE"), nullable=False
    )
    candidate_role: Mapped[str] = mapped_column(String(32), nullable=False)
    concept_priority: Mapped[int] = mapped_column(Integer, nullable=False)
    concept_match_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    period_match_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    unit_match_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    accession_match_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    frame_match_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    combined_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    selection_status: Mapped[str] = mapped_column(String(32), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ClaimVerification(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_verifications"
    __table_args__ = (
        Index(
            "uq_claim_verifications_claim_version",
            "financial_claim_id",
            "verification_version",
            unique=True,
        ),
        Index("ix_claim_verifications_status", "verification_status"),
    )

    financial_claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_claims.id", ondelete="CASCADE"), nullable=False
    )
    current_xbrl_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("xbrl_facts.id", ondelete="SET NULL")
    )
    comparison_xbrl_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("xbrl_facts.id", ondelete="SET NULL")
    )
    verification_status: Mapped[str] = mapped_column(String(48), nullable=False)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    comparison_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    absolute_change: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    percentage_change: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    percentage_point_change: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    reported_change: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    reported_vs_calculated_difference: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 6), nullable=True
    )
    calculation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    calculation_inputs: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    calculation_output: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    tolerance_used: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    verification_reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    verification_version: Mapped[str] = mapped_column(String(64), nullable=False)


class DerivedFinancialMetric(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "derived_financial_metrics"
    __table_args__ = (
        Index("ix_derived_metrics_filing_metric", "filing_id", "metric_definition_id"),
        Index("ix_derived_metrics_period", "filing_id", "period_start", "period_end"),
        Index(
            "uq_derived_metrics_filing_metric_period_version",
            "filing_id",
            "metric_definition_id",
            "period_start",
            "period_end",
            "calculation_version",
            unique=True,
        ),
    )

    metric_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("financial_metric_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filings.id", ondelete="CASCADE"), nullable=False
    )
    calculation_status: Mapped[str] = mapped_column(String(48), nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    input_fact_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    calculation_inputs_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    calculated_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    period_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    assumptions: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
