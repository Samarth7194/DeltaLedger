"""Worker heartbeat/lease on analysis_runs, for stale-run recovery.

Adds last_heartbeat_at, touched whenever a node starts/finishes and whenever a
stage-batch is marked processing/completed/failed. A run is "stale" (see
app/services/stale_run_recovery.py) when it sits in a non-terminal,
non-awaiting-review status with a heartbeat older than
STALE_RUN_HEARTBEAT_THRESHOLD_SECONDS and its advisory lock is not currently
held - that combination means the worker that was processing it died without
reaching its own failure handler.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_stale_run_recovery"
down_revision = "0007_stage_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_analysis_runs_status_heartbeat",
        "analysis_runs",
        ["status", "last_heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_status_heartbeat", table_name="analysis_runs")
    op.drop_column("analysis_runs", "last_heartbeat_at")
