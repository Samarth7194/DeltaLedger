from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UuidPrimaryKeyMixin

CONTRADICTION_TYPES = (
    "direction_contradiction",
    "magnitude_overstatement",
    "magnitude_understatement",
    "unsupported_qualitative_claim",
    "narrative_cross_section_inconsistency",
    "temporal_narrative_inconsistency",
    "numerical_claim_contradiction",
)

FINDING_STATUSES = ("candidate", "confirmed_for_review", "insufficient_evidence", "dismissed")
SEVERITIES = ("low", "medium", "high", "critical")
DETECTION_METHODS = ("deterministic", "rule_based", "model", "hybrid")
REVIEW_STATUSES = ("pending", "approved", "rejected", "edited", "uncertain")
EVIDENCE_TYPES = (
    "narrative_passage",
    "previous_passage",
    "current_passage",
    "xbrl_fact",
    "financial_claim",
    "claim_verification",
    "disclosure_change",
    "filing_table",
    "derived_metric",
)
EVIDENCE_ROLES = ("primary", "supporting", "comparison", "conflicting")


def _sql_tuple(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


class ContradictionFinding(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contradiction_findings"
    __table_args__ = (
        Index("ix_contradictions_company_type", "company_id", "contradiction_type"),
        Index("ix_contradictions_comparison_severity", "comparison_id", "severity"),
        Index("ix_contradictions_review_status", "review_status"),
        Index("ix_contradictions_confidence", "confidence"),
        Index("uq_contradictions_fingerprint", "finding_fingerprint", unique=True),
        CheckConstraint(
            "contradiction_type IN " + _sql_tuple(CONTRADICTION_TYPES),
            name="contradiction_findings_type",
        ),
        CheckConstraint("status IN " + _sql_tuple(FINDING_STATUSES), name="contradiction_status"),
        CheckConstraint("severity IN " + _sql_tuple(SEVERITIES), name="contradiction_severity"),
        CheckConstraint(
            "detection_method IN " + _sql_tuple(DETECTION_METHODS),
            name="contradiction_detection_method",
        ),
        CheckConstraint(
            "review_status IN " + _sql_tuple(REVIEW_STATUSES),
            name="contradiction_review_status",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    comparison_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_comparisons.id", ondelete="CASCADE")
    )
    financial_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_claims.id", ondelete="SET NULL")
    )
    claim_verification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claim_verifications.id", ondelete="SET NULL")
    )
    disclosure_change_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("disclosure_changes.id", ondelete="SET NULL")
    )
    contradiction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="candidate", server_default="candidate", nullable=False
    )
    risk_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    narrative_claim: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative_direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    measured_direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reported_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    calculated_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    calculated_change: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    difference: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    qualifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    finding_title: Mapped[str] = mapped_column(String(255), nullable=False)
    finding_summary: Mapped[str] = mapped_column(Text, nullable=False)
    finding_explanation: Mapped[str] = mapped_column(Text, nullable=False)
    limitations: Mapped[list[dict[str, object]] | list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    deterministic_evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    supporting_evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    severity_components: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    confidence_components: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    detection_method: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_model_output: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    original_system_finding: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    finding_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_edits: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )

    evidence = relationship("ContradictionEvidence", cascade="all, delete-orphan")


class ContradictionEvidence(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "contradiction_evidence"
    __table_args__ = (
        Index("ix_contradiction_evidence_finding", "contradiction_finding_id"),
        CheckConstraint(
            "evidence_type IN " + _sql_tuple(EVIDENCE_TYPES),
            name="contradiction_evidence_type",
        ),
        CheckConstraint(
            "evidence_role IN " + _sql_tuple(EVIDENCE_ROLES),
            name="contradiction_evidence_role",
        ),
    )

    contradiction_finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contradiction_findings.id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_type: Mapped[str] = mapped_column(String(48), nullable=False)
    filing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filings.id", ondelete="SET NULL")
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_sections.id", ondelete="SET NULL")
    )
    passage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("passage_units.id", ondelete="SET NULL")
    )
    xbrl_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("xbrl_facts.id", ondelete="SET NULL")
    )
    financial_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("financial_claims.id", ondelete="SET NULL")
    )
    claim_verification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claim_verifications.id", ondelete="SET NULL")
    )
    disclosure_change_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("disclosure_changes.id", ondelete="SET NULL")
    )
    derived_metric_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("derived_financial_metrics.id", ondelete="SET NULL")
    )
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_anchor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    evidence_role: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}", nullable=False
    )
