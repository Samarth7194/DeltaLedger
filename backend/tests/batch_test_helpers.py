"""In-memory stand-ins for the database side of the stage-batch ledger, so the
real StageBatchRepository logic (plan sync, status transitions) runs in unit
tests without a database."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.db.models import AnalysisStageBatch


class _ScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class InMemoryBatchSession:
    """Just enough of AsyncSession for StageBatchRepository. Several sessions
    can share one `store`, like separate connections to one database."""

    def __init__(self, store: list[AnalysisStageBatch] | None = None) -> None:
        self.store: list[AnalysisStageBatch] = store if store is not None else []
        self.commit_count = 0

    async def __aenter__(self) -> InMemoryBatchSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def scalars(self, statement) -> _ScalarResult:
        params = statement.compile().params
        run_id = next(v for k, v in params.items() if k.startswith("analysis_run_id"))
        stage = next(v for k, v in params.items() if k.startswith("stage"))
        return _ScalarResult(
            [
                row
                for row in self.store
                if row.analysis_run_id == run_id and row.stage == stage
            ]
        )

    async def execute(self, statement):
        """Column-projection selects (stage_progress): rows as tuples in the
        selected column order, filtered to the statement's analysis run."""
        params = statement.compile().params
        run_id = next(v for k, v in params.items() if k.startswith("analysis_run_id"))
        names = [column.key for column in statement.selected_columns]
        rows = sorted(
            (row for row in self.store if row.analysis_run_id == run_id),
            key=lambda row: (row.stage, row.batch_index),
        )
        return [tuple(getattr(row, name) for name in names) for row in rows]

    def add(self, row: AnalysisStageBatch) -> None:
        if row.id is None:
            row.id = uuid.uuid4()
        self.store.append(row)

    async def flush(self) -> None:
        return None

    async def delete(self, row: AnalysisStageBatch) -> None:
        self.store.remove(row)

    async def get(self, _model, batch_id: uuid.UUID):
        return next((row for row in self.store if row.id == batch_id), None)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        return None


def batch_rows(store: list[AnalysisStageBatch], stage: str) -> list[SimpleNamespace]:
    """Snapshot of a stage's rows in batch order, for easy assertions."""
    rows = sorted((row for row in store if row.stage == stage), key=lambda r: r.batch_index)
    return [
        SimpleNamespace(
            index=row.batch_index,
            total=row.total_batches,
            status=row.status,
            input_hash=row.input_hash,
            item_ids=list(row.item_ids),
            retry_count=row.retry_count,
            provider_calls=row.provider_call_count,
            error_category=row.last_error_category,
            error_message=row.last_error_message,
            provider_error_type=row.last_provider_error_type,
            retry_after=row.last_retry_after_seconds,
            provider_error_at=row.last_provider_error_at,
            actual_input=row.actual_input_tokens,
            actual_output=row.actual_output_tokens,
            actual_total=row.actual_total_tokens,
            successful=row.successful_items,
            zero_result=row.zero_result_items,
            requires_review=row.requires_review_items,
            item_results=dict(row.item_results or {}),
        )
        for row in rows
    ]
