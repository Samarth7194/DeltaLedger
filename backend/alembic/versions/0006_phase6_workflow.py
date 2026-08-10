from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_phase6_workflow"
down_revision = "0005_phase5_contradict"
branch_labels = None
depends_on = None


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


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_filing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comparison_filing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comparison_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=48), server_default="queued", nullable=False),
        sa.Column("current_node", sa.String(length=128), nullable=True),
        sa.Column("workflow_version", sa.String(length=64), nullable=False),
        sa.Column("graph_version", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_thread_id", sa.String(length=128), nullable=False),
        sa.Column("requires_human_review", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("review_gate_reason", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("failure_node", sa.String(length=128), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "processing_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comparison_filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comparison_id"], ["filing_comparisons.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "current_filing_id <> comparison_filing_id",
            name="ck_analysis_runs_distinct_filings",
        ),
        sa.CheckConstraint(
            "status IN " + _sql_tuple(ANALYSIS_STATUSES),
            name="ck_analysis_runs_status",
        ),
        sa.UniqueConstraint(
            "current_filing_id",
            "comparison_filing_id",
            "workflow_version",
            name="uq_analysis_pair_workflow_version",
        ),
        sa.UniqueConstraint("checkpoint_thread_id", name="uq_analysis_checkpoint_thread"),
    )
    op.create_index(
        "ix_analysis_runs_company_created",
        "analysis_runs",
        ["company_id", "created_at"],
    )
    op.create_index("ix_analysis_runs_status", "analysis_runs", ["status"])
    op.create_index(
        "ix_analysis_runs_filing_pair",
        "analysis_runs",
        ["current_filing_id", "comparison_filing_id"],
    )
    op.create_index("ix_analysis_runs_checkpoint_thread", "analysis_runs", ["checkpoint_thread_id"])

    op.create_table(
        "analysis_workflow_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("node_name", sa.String(length=128), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=True),
        sa.Column(
            "event_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "event_type IN " + _sql_tuple(WORKFLOW_EVENT_TYPES),
            name="ck_analysis_workflow_events_type",
        ),
    )
    op.create_index(
        "ix_analysis_events_run_created",
        "analysis_workflow_events",
        ["analysis_run_id", "created_at"],
    )
    op.create_index(
        "ix_analysis_events_node",
        "analysis_workflow_events",
        ["analysis_run_id", "node_name"],
    )

    op.create_table(
        "analysis_review_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "finding_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "claim_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "verification_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("review_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resume_token_hash", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "review_type IN " + _sql_tuple(REVIEW_TYPES),
            name="ck_analysis_review_requests_type",
        ),
        sa.CheckConstraint(
            "status IN " + _sql_tuple(WORKFLOW_REVIEW_STATUSES),
            name="ck_analysis_review_requests_status",
        ),
    )
    op.create_index(
        "ix_analysis_review_run_status",
        "analysis_review_requests",
        ["analysis_run_id", "status"],
    )

    op.create_table(
        "analysis_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column(
            "comparison_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "disclosure_change_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "financial_verification_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "contradiction_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "high_priority_findings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "limitations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "evidence_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "report_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("generator_name", sa.String(length=255), nullable=True),
        sa.Column("generator_version", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN " + _sql_tuple(REPORT_STATUSES),
            name="ck_analysis_reports_status",
        ),
        sa.UniqueConstraint("analysis_run_id", name="uq_analysis_reports_run"),
    )


def downgrade() -> None:
    op.drop_table("analysis_reports")
    op.drop_index("ix_analysis_review_run_status", table_name="analysis_review_requests")
    op.drop_table("analysis_review_requests")
    op.drop_index("ix_analysis_events_node", table_name="analysis_workflow_events")
    op.drop_index("ix_analysis_events_run_created", table_name="analysis_workflow_events")
    op.drop_table("analysis_workflow_events")
    op.drop_index("ix_analysis_runs_checkpoint_thread", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_filing_pair", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_status", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_company_created", table_name="analysis_runs")
    op.drop_table("analysis_runs")


def _sql_tuple(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"
