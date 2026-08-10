from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_phase5_contradict"
down_revision = "0004_phase4_financial"
branch_labels = None
depends_on = None


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


def upgrade() -> None:
    op.create_table(
        "contradiction_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comparison_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("financial_claim_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claim_verification_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disclosure_change_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contradiction_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="candidate", nullable=False),
        sa.Column("risk_category", sa.String(length=64), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 4), nullable=False),
        sa.Column("narrative_claim", sa.Text(), nullable=True),
        sa.Column("narrative_direction", sa.String(length=32), nullable=True),
        sa.Column("measured_direction", sa.String(length=32), nullable=True),
        sa.Column("reported_value", sa.Numeric(28, 6), nullable=True),
        sa.Column("calculated_value", sa.Numeric(28, 6), nullable=True),
        sa.Column("calculated_change", sa.Numeric(28, 6), nullable=True),
        sa.Column("difference", sa.Numeric(28, 6), nullable=True),
        sa.Column("qualifier", sa.String(length=128), nullable=True),
        sa.Column("finding_title", sa.String(length=255), nullable=False),
        sa.Column("finding_summary", sa.Text(), nullable=False),
        sa.Column("finding_explanation", sa.Text(), nullable=False),
        sa.Column(
            "limitations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "deterministic_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "supporting_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "severity_components",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "confidence_components",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("detection_method", sa.String(length=32), nullable=False),
        sa.Column(
            "rule_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("original_model_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "original_system_finding",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("finding_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("review_status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewer_edits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comparison_id"], ["filing_comparisons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["financial_claim_id"], ["financial_claims.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["claim_verification_id"], ["claim_verifications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["disclosure_change_id"], ["disclosure_changes.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "contradiction_type IN " + _sql_tuple(CONTRADICTION_TYPES),
            name="ck_contradiction_findings_type",
        ),
        sa.CheckConstraint(
            "status IN " + _sql_tuple(FINDING_STATUSES),
            name="ck_contradiction_findings_status",
        ),
        sa.CheckConstraint(
            "severity IN " + _sql_tuple(SEVERITIES),
            name="ck_contradiction_findings_severity",
        ),
        sa.CheckConstraint(
            "detection_method IN " + _sql_tuple(DETECTION_METHODS),
            name="ck_contradiction_findings_detection_method",
        ),
        sa.CheckConstraint(
            "review_status IN " + _sql_tuple(REVIEW_STATUSES),
            name="ck_contradiction_findings_review_status",
        ),
    )
    op.create_index("ix_contradictions_company_type", "contradiction_findings", ["company_id", "contradiction_type"])
    op.create_index("ix_contradictions_comparison_severity", "contradiction_findings", ["comparison_id", "severity"])
    op.create_index("ix_contradictions_review_status", "contradiction_findings", ["review_status"])
    op.create_index("ix_contradictions_confidence", "contradiction_findings", ["confidence"])
    op.create_index("uq_contradictions_fingerprint", "contradiction_findings", ["finding_fingerprint"], unique=True)

    op.create_table(
        "contradiction_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("contradiction_finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_type", sa.String(length=48), nullable=False),
        sa.Column("filing_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("passage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("xbrl_fact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("financial_claim_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claim_verification_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("disclosure_change_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("derived_metric_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("source_anchor", sa.String(length=512), nullable=True),
        sa.Column("evidence_role", sa.String(length=32), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["contradiction_finding_id"],
            ["contradiction_findings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["section_id"], ["filing_sections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["passage_id"], ["passage_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["xbrl_fact_id"], ["xbrl_facts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["financial_claim_id"], ["financial_claims.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["claim_verification_id"], ["claim_verifications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["disclosure_change_id"], ["disclosure_changes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["derived_metric_id"], ["derived_financial_metrics.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "evidence_type IN " + _sql_tuple(EVIDENCE_TYPES),
            name="ck_contradiction_evidence_type",
        ),
        sa.CheckConstraint(
            "evidence_role IN " + _sql_tuple(EVIDENCE_ROLES),
            name="ck_contradiction_evidence_role",
        ),
    )
    op.create_index("ix_contradiction_evidence_finding", "contradiction_evidence", ["contradiction_finding_id"])


def downgrade() -> None:
    op.drop_index("ix_contradiction_evidence_finding", table_name="contradiction_evidence")
    op.drop_table("contradiction_evidence")
    op.drop_index("uq_contradictions_fingerprint", table_name="contradiction_findings")
    op.drop_index("ix_contradictions_confidence", table_name="contradiction_findings")
    op.drop_index("ix_contradictions_review_status", table_name="contradiction_findings")
    op.drop_index("ix_contradictions_comparison_severity", table_name="contradiction_findings")
    op.drop_index("ix_contradictions_company_type", table_name="contradiction_findings")
    op.drop_table("contradiction_findings")


def _sql_tuple(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"
