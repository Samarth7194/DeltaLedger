from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.db.models import AuditEvent, Filing


@pytest.mark.parametrize(
    "model,index_name,columns",
    [
        (AuditEvent, "ix_audit_actor_created", "actor_id, created_at DESC"),
        (AuditEvent, "ix_audit_event_created", "event_type, created_at DESC"),
        (Filing, "ix_filings_company_form_period", "company_id, form_type, report_period DESC"),
    ],
)
def test_model_index_sort_order_matches_initial_migration(model, index_name, columns) -> None:
    index = next(index for index in model.__table__.indexes if index.name == index_name)

    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert ddl == f"CREATE INDEX {index_name} ON {model.__tablename__} ({columns})"
