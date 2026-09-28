from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_stage_batches"
down_revision = "0006_phase6_workflow"
branch_labels = None
depends_on = None


STAGE_BATCH_STATUSES = ("pending", "processing", "completed", "failed")


def upgrade() -> None:
    op.create_table(
        "analysis_stage_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(length=48), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("total_batches", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "item_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("provider_call_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column(
            "item_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("successful_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("zero_result_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("requires_review_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("actual_input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("actual_output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("actual_total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("last_provider_error_type", sa.String(length=48), nullable=True),
        sa.Column("last_retry_after_seconds", sa.Float(), nullable=True),
        sa.Column("last_provider_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN " + _sql_tuple(STAGE_BATCH_STATUSES),
            # The metadata's naming convention prefixes this with
            # ck_analysis_stage_batches_, matching the model's constraint name.
            name="analysis_stage_batch_status",
        ),
        sa.CheckConstraint("batch_index >= 1", name="analysis_stage_batch_index"),
        sa.UniqueConstraint(
            "analysis_run_id",
            "stage",
            "batch_index",
            name="uq_analysis_stage_batch_index",
        ),
    )
    op.create_index(
        "ix_analysis_stage_batches_run_stage_status",
        "analysis_stage_batches",
        ["analysis_run_id", "stage", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analysis_stage_batches_run_stage_status",
        table_name="analysis_stage_batches",
    )
    op.drop_table("analysis_stage_batches")


def _sql_tuple(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"
