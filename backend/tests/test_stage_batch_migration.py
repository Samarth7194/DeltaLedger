"""Offline integrity checks of migration 0007_stage_batches (no database)."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from app.db.models import AnalysisStageBatch

BACKEND = Path(__file__).resolve().parents[1]
REVISION = "0007_stage_batches"
PARENT = "0006_phase6_workflow"


def _config(buffer: io.StringIO | None = None) -> Config:
    config = Config(str(BACKEND / "alembic.ini"), output_buffer=buffer)
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _sql(direction: str, span: str) -> str:
    buffer = io.StringIO()
    config = _config(buffer)
    (command.upgrade if direction == "up" else command.downgrade)(config, span, sql=True)
    return buffer.getvalue()


def test_there_is_exactly_one_head_and_it_chains_from_the_previous_revision() -> None:
    script = ScriptDirectory.from_config(_config())

    assert script.get_heads() == [REVISION]
    revision = script.get_revision(REVISION)
    assert revision.down_revision == PARENT
    assert len(REVISION) <= 32  # fits alembic_version.version_num


def test_upgrade_only_creates_the_new_table_and_its_index() -> None:
    sql = _sql("up", f"{PARENT}:{REVISION}")

    statements = re.findall(r"^(CREATE|DROP|ALTER|INSERT|UPDATE|DELETE)\b[^\n]*", sql, re.MULTILINE)
    assert "CREATE TABLE analysis_stage_batches" in sql
    assert "CREATE INDEX ix_analysis_stage_batches_run_stage_status" in sql
    for forbidden in ("DROP TABLE", "DROP COLUMN", "ALTER TABLE", "DELETE FROM", "TRUNCATE"):
        assert forbidden not in sql, f"unexpected {forbidden} in upgrade"
    # Only the version bookkeeping UPDATE besides the two CREATEs.
    assert sorted(set(statements)) == ["CREATE", "UPDATE"]
    assert f"version_num='{REVISION}'" in sql


def test_downgrade_only_drops_what_upgrade_created() -> None:
    sql = _sql("down", f"{REVISION}:{PARENT}")

    assert "DROP INDEX ix_analysis_stage_batches_run_stage_status" in sql
    assert "DROP TABLE analysis_stage_batches" in sql
    dropped = re.findall(r"DROP (?:TABLE|INDEX) ([a-z_]+)", sql)
    assert sorted(dropped) == [
        "analysis_stage_batches",
        "ix_analysis_stage_batches_run_stage_status",
    ]
    assert f"version_num='{PARENT}'" in sql


def test_upgrade_ddl_has_the_expected_constraints_foreign_key_and_defaults() -> None:
    sql = _sql("up", f"{PARENT}:{REVISION}")

    assert (
        "FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs (id) ON DELETE CASCADE" in sql
    )
    assert "UNIQUE (analysis_run_id, stage, batch_index)" in sql
    assert "CHECK (status IN ('pending', 'processing', 'completed', 'failed'))" in sql
    assert "CHECK (batch_index >= 1)" in sql
    assert "status VARCHAR(16) DEFAULT 'pending' NOT NULL" in sql
    assert "item_results JSONB DEFAULT '{}'::jsonb NOT NULL" in sql
    # Usage columns are nullable on purpose: NULL means "provider reported none".
    for column in ("actual_input_tokens", "actual_output_tokens", "actual_total_tokens"):
        assert re.search(rf"\b{column} BIGINT,", sql)


def test_migration_columns_match_the_orm_model_exactly() -> None:
    sql = _sql("up", f"{PARENT}:{REVISION}")
    table_body = sql.split("CREATE TABLE analysis_stage_batches (", 1)[1].split("\n);", 1)[0]
    migration_columns = {
        line.split()[0]
        for line in table_body.splitlines()
        if line.strip() and not line.strip().startswith(("CONSTRAINT", "PRIMARY", "FOREIGN"))
    }

    model_columns = {column.name for column in AnalysisStageBatch.__table__.columns}
    assert migration_columns == model_columns

    model_nullable = {c.name for c in AnalysisStageBatch.__table__.columns if c.nullable}
    for column in AnalysisStageBatch.__table__.columns:
        pattern = rf"^\s+{column.name} [A-Z0-9()\s.']+?(?: DEFAULT [^,\n]+?)?( NOT NULL)?,?\s*$"
        match = re.search(pattern, table_body, re.MULTILINE)
        assert match, column.name
        assert (match.group(1) is None) == (column.name in model_nullable), column.name


def test_model_indexes_and_unique_constraints_match_the_migration() -> None:
    table = AnalysisStageBatch.__table__
    index_names = {index.name for index in table.indexes}
    assert index_names == {"ix_analysis_stage_batches_run_stage_status"}
    unique = {c.name for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"}
    assert unique == {"uq_analysis_stage_batch_index"}
    foreign_keys = {fk.column.table.name: fk.ondelete for fk in table.foreign_keys}
    assert foreign_keys == {"analysis_runs": "CASCADE"}


@pytest.mark.parametrize("name", ["0007_stage_batches.py"])
def test_the_migration_file_contains_no_data_modifying_statements(name: str) -> None:
    source = (BACKEND / "alembic" / "versions" / name).read_text(encoding="utf-8")

    for forbidden in ("op.execute", "op.drop_column", "op.alter_column", "op.rename_table"):
        assert forbidden not in source
