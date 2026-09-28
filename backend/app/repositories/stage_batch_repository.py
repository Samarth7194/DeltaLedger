from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.batching import (
    OUTCOME_REQUIRES_REVIEW,
    OUTCOME_SUCCESS,
    OUTCOME_ZERO_RESULT,
    PlannedBatch,
    batch_identity_hash,
)
from app.ai.inference import UsageTotals
from app.db.models import AnalysisStageBatch

_MAX_ERROR_MESSAGE_CHARS = 500
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(api[_-]?key|token|secret)\s*[=:]\s*\S+", re.IGNORECASE),
)

# Provider/transport failures where running the same work again later can
# succeed. Anything else (a rejected request, a code bug) needs a human.
RETRYABLE_ERROR_TYPES = frozenset(
    {
        "rate_limited",
        "rate_limited_short_term",
        "quota_exhausted_daily",
        "resource_exhausted",
        "timeout",
        "network_error",
        "server_error",
        "InterfaceError",
        "OperationalError",
        "ConnectionError",
        "ConnectionResetError",
    }
)


def is_retryable_error_type(error_type: str | None) -> bool:
    return error_type in RETRYABLE_ERROR_TYPES


@dataclass(frozen=True)
class StageBatchState:
    """Plain snapshot of one batch row.

    The shared session is closed/reopened around long provider calls, which
    detaches ORM objects, so callers hold these (ids and values) instead.
    """

    id: uuid.UUID
    stage: str
    batch_index: int
    total_batches: int
    status: str
    input_hash: str
    item_count: int
    estimated_input_tokens: int
    provider_call_count: int
    retry_count: int
    item_results: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderErrorInfo:
    """Safe, non-secret facts about the last provider failure."""

    error_type: str
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class PartProgress:
    index: int
    status: str
    item_count: int
    estimated_input_tokens: int
    actual_input_tokens: int | None
    actual_output_tokens: int | None
    actual_total_tokens: int | None
    provider_calls: int
    retry_count: int
    successful_items: int
    zero_result_items: int
    requires_review_items: int
    last_provider_error_type: str | None
    last_retry_after_seconds: float | None
    last_provider_error_at: datetime | None


@dataclass(frozen=True)
class StageProgress:
    """Real progress of one batched stage: counts of batches, never a
    time-based estimate."""

    stage: str
    total: int
    completed: int
    processing: int
    failed: int
    pending: int
    provider_calls: int
    retries: int
    estimated_input_tokens: int = 0
    actual_input_tokens: int | None = None
    actual_output_tokens: int | None = None
    actual_total_tokens: int | None = None
    successful_items: int = 0
    zero_result_items: int = 0
    requires_review_items: int = 0
    last_provider_error_type: str | None = None
    last_retry_after_seconds: float | None = None
    last_provider_error_at: datetime | None = None
    parts: tuple[PartProgress, ...] = ()

    @property
    def status(self) -> str:
        if self.total and self.completed == self.total:
            return "completed"
        if self.failed:
            return "failed"
        if self.processing or self.completed:
            return "processing"
        return "pending"

    @property
    def current_batch(self) -> int | None:
        """1-based index of the part being worked on (or that last failed),
        i.e. the first incomplete one."""
        if not self.total or self.completed == self.total:
            return None
        return self.completed + 1


def safe_error_message(exc: BaseException) -> str:
    """Short, secret-scrubbed description of an error, safe to persist and
    expose. Never includes request bodies/prompts (exceptions here don't carry
    them) and redacts anything credential-shaped defensively."""
    text = f"{exc.__class__.__name__}: {exc}"
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text[:_MAX_ERROR_MESSAGE_CHARS]


def count_outcomes(item_results: Mapping[str, object]) -> tuple[int, int, int]:
    """(successful, zero_result, requires_review) over item outcome records."""
    successful = zero_result = requires_review = 0
    for record in item_results.values():
        status = record.get("status") if isinstance(record, dict) else None
        if status == OUTCOME_SUCCESS:
            successful += 1
        elif status == OUTCOME_ZERO_RESULT:
            zero_result += 1
        elif status == OUTCOME_REQUIRES_REVIEW:
            requires_review += 1
    return successful, zero_result, requires_review


class StageBatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sync_plan(
        self,
        analysis_run_id: uuid.UUID,
        stage: str,
        plan: Sequence[PlannedBatch],
        *,
        model_name: str | None,
        prompt_version: str | None,
        context_hash: str = "",
    ) -> list[StageBatchState]:
        """Reconcile the persisted batches of (run, stage) with `plan`.

        A row whose identity hash still matches keeps its status and results -
        that is what lets a resumed run skip completed batches. A row whose
        identity differs (different items or item content, or a different
        model/prompt version/context) is reset to pending with its results
        cleared, since its recorded completion no longer applies. Rows past the
        end of the new plan are removed. Idempotent: syncing the same plan
        twice changes nothing.
        """
        existing = {
            row.batch_index: row
            for row in (
                await self.session.scalars(
                    select(AnalysisStageBatch).where(
                        AnalysisStageBatch.analysis_run_id == analysis_run_id,
                        AnalysisStageBatch.stage == stage,
                    )
                )
            ).all()
        }
        total = len(plan)
        states: list[StageBatchState] = []
        for planned in plan:
            input_hash = batch_identity_hash(
                stage=stage,
                model_name=model_name,
                prompt_version=prompt_version,
                item_identities=planned.identities,
                context_hash=context_hash,
            )
            row = existing.get(planned.index)
            if row is None:
                row = AnalysisStageBatch(
                    analysis_run_id=analysis_run_id,
                    stage=stage,
                    batch_index=planned.index,
                    status="pending",
                    provider_call_count=0,
                    retry_count=0,
                    item_results={},
                    successful_items=0,
                    zero_result_items=0,
                    requires_review_items=0,
                )
                self.session.add(row)
            elif row.input_hash != input_hash:
                _reset(row)
            row.total_batches = total
            row.input_hash = input_hash
            row.item_ids = planned.identities
            row.item_count = planned.item_count
            row.estimated_input_tokens = planned.estimated_input_tokens
            row.model_name = model_name
            row.prompt_version = prompt_version
            await self.session.flush()
            states.append(_state(row))
        for index, row in existing.items():
            if index > total:
                await self.session.delete(row)
        return states

    async def mark_processing(self, batch_id: uuid.UUID) -> None:
        row = await self._require(batch_id)
        # A batch that was already processing (interrupted) or failed is being
        # attempted again, which is what retry_count counts.
        if row.status in ("processing", "failed"):
            row.retry_count += 1
        row.status = "processing"
        row.started_at = datetime.now(UTC)
        await self.session.flush()

    async def mark_completed(
        self,
        batch_id: uuid.UUID,
        *,
        provider_calls: int = 0,
        item_results: Mapping[str, object] | None = None,
        usage: UsageTotals | None = None,
    ) -> None:
        """Mark the batch completed and record its results in the same flush.

        Callers commit this together with the stage's own outputs, so a batch
        is never `completed` without its results, nor are results committed
        for a batch that still looks unfinished.
        """
        row = await self._require(batch_id)
        self._apply_results(row, item_results, usage)
        row.status = "completed"
        row.completed_at = datetime.now(UTC)
        row.provider_call_count += provider_calls
        row.last_error_category = None
        row.last_error_message = None
        await self.session.flush()

    async def mark_failed(
        self,
        batch_id: uuid.UUID,
        *,
        error_category: str,
        error_message: str,
        provider_calls: int = 0,
        provider_error: ProviderErrorInfo | None = None,
        item_results: Mapping[str, object] | None = None,
        usage: UsageTotals | None = None,
    ) -> None:
        """Record a failed attempt. Items that did resolve before the failure
        are kept in `item_results` so the retry does not redo them."""
        row = await self._require(batch_id)
        self._apply_results(row, item_results, usage)
        row.status = "failed"
        row.provider_call_count += provider_calls
        row.last_error_category = error_category[:64]
        row.last_error_message = error_message[:_MAX_ERROR_MESSAGE_CHARS]
        if provider_error is not None:
            row.last_provider_error_type = provider_error.error_type[:48]
            row.last_retry_after_seconds = provider_error.retry_after_seconds
            row.last_provider_error_at = datetime.now(UTC)
        await self.session.flush()

    async def list_batches(self, analysis_run_id: uuid.UUID, stage: str) -> list[StageBatchState]:
        rows = await self.session.scalars(
            select(AnalysisStageBatch)
            .where(
                AnalysisStageBatch.analysis_run_id == analysis_run_id,
                AnalysisStageBatch.stage == stage,
            )
            .order_by(AnalysisStageBatch.batch_index)
        )
        return [_state(row) for row in rows.all()]

    async def stage_progress(self, analysis_run_id: uuid.UUID) -> dict[str, StageProgress]:
        # Only the small progress columns: never item_results or item ids.
        rows = await self.session.execute(
            select(*(getattr(AnalysisStageBatch, name) for name in _PART_COLUMNS))
            .where(AnalysisStageBatch.analysis_run_id == analysis_run_id)
            .order_by(AnalysisStageBatch.stage, AnalysisStageBatch.batch_index)
        )
        by_stage: dict[str, list[dict[str, object]]] = {}
        for values in rows:
            record = dict(zip(_PART_COLUMNS, values, strict=True))
            by_stage.setdefault(str(record["stage"]), []).append(record)
        return {stage: _aggregate(stage, records) for stage, records in by_stage.items()}

    def _apply_results(
        self,
        row: AnalysisStageBatch,
        item_results: Mapping[str, object] | None,
        usage: UsageTotals | None,
    ) -> None:
        if item_results:
            merged = {**(row.item_results or {}), **item_results}
            # Reassign (not mutate) so the JSONB change is tracked.
            row.item_results = merged
            (
                row.successful_items,
                row.zero_result_items,
                row.requires_review_items,
            ) = count_outcomes(merged)
        if usage is not None:
            row.actual_input_tokens = _add(row.actual_input_tokens, usage.input_tokens)
            row.actual_output_tokens = _add(row.actual_output_tokens, usage.output_tokens)
            row.actual_total_tokens = _add(row.actual_total_tokens, usage.resolved_total())

    async def _require(self, batch_id: uuid.UUID) -> AnalysisStageBatch:
        # session.get() re-attaches the row if the shared session was closed
        # since the batch was planned (closing detaches ORM objects).
        row = await self.session.get(AnalysisStageBatch, batch_id)
        if row is None:
            raise LookupError(f"Analysis stage batch not found: {batch_id}")
        return row


_PART_COLUMNS = (
    "stage",
    "batch_index",
    "status",
    "item_count",
    "estimated_input_tokens",
    "actual_input_tokens",
    "actual_output_tokens",
    "actual_total_tokens",
    "provider_call_count",
    "retry_count",
    "successful_items",
    "zero_result_items",
    "requires_review_items",
    "last_provider_error_type",
    "last_retry_after_seconds",
    "last_provider_error_at",
)

_EPOCH = datetime.min.replace(tzinfo=UTC)


def _aggregate(stage: str, records: list[dict[str, object]]) -> StageProgress:
    parts = tuple(
        PartProgress(
            index=int(r["batch_index"]),
            status=str(r["status"]),
            item_count=int(r["item_count"]),
            estimated_input_tokens=int(r["estimated_input_tokens"]),
            actual_input_tokens=r["actual_input_tokens"],
            actual_output_tokens=r["actual_output_tokens"],
            actual_total_tokens=r["actual_total_tokens"],
            provider_calls=int(r["provider_call_count"]),
            retry_count=int(r["retry_count"]),
            successful_items=int(r["successful_items"]),
            zero_result_items=int(r["zero_result_items"]),
            requires_review_items=int(r["requires_review_items"]),
            last_provider_error_type=r["last_provider_error_type"],
            last_retry_after_seconds=r["last_retry_after_seconds"],
            last_provider_error_at=r["last_provider_error_at"],
        )
        for r in records
    )
    by_status: dict[str, int] = {}
    for part in parts:
        by_status[part.status] = by_status.get(part.status, 0) + 1
    # The failure worth surfacing is the most recent one on a part that is
    # still failing (not one a later retry already recovered from).
    failing = [p for p in parts if p.status == "failed" and p.last_provider_error_type]
    latest = max(failing, key=lambda p: p.last_provider_error_at or _EPOCH, default=None)
    return StageProgress(
        stage=stage,
        total=len(parts),
        completed=by_status.get("completed", 0),
        processing=by_status.get("processing", 0),
        failed=by_status.get("failed", 0),
        pending=by_status.get("pending", 0),
        provider_calls=sum(p.provider_calls for p in parts),
        retries=sum(p.retry_count for p in parts),
        estimated_input_tokens=sum(p.estimated_input_tokens for p in parts),
        actual_input_tokens=_sum_known(p.actual_input_tokens for p in parts),
        actual_output_tokens=_sum_known(p.actual_output_tokens for p in parts),
        actual_total_tokens=_sum_known(p.actual_total_tokens for p in parts),
        successful_items=sum(p.successful_items for p in parts),
        zero_result_items=sum(p.zero_result_items for p in parts),
        requires_review_items=sum(p.requires_review_items for p in parts),
        last_provider_error_type=latest.last_provider_error_type if latest else None,
        last_retry_after_seconds=latest.last_retry_after_seconds if latest else None,
        last_provider_error_at=latest.last_provider_error_at if latest else None,
        parts=parts,
    )


def _sum_known(values: Iterable[int | None]) -> int | None:
    """Sum of the non-null values, or None when none were reported."""
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _add(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return value if current is None else current + value


def _reset(row: AnalysisStageBatch) -> None:
    row.status = "pending"
    row.provider_call_count = 0
    row.retry_count = 0
    row.started_at = None
    row.completed_at = None
    row.last_error_category = None
    row.last_error_message = None
    row.item_results = {}
    row.successful_items = 0
    row.zero_result_items = 0
    row.requires_review_items = 0
    row.actual_input_tokens = None
    row.actual_output_tokens = None
    row.actual_total_tokens = None
    row.last_provider_error_type = None
    row.last_retry_after_seconds = None
    row.last_provider_error_at = None


def _state(row: AnalysisStageBatch) -> StageBatchState:
    return StageBatchState(
        id=row.id,
        stage=row.stage,
        batch_index=row.batch_index,
        total_batches=row.total_batches,
        status=row.status,
        input_hash=row.input_hash,
        item_count=row.item_count,
        estimated_input_tokens=row.estimated_input_tokens,
        provider_call_count=row.provider_call_count,
        retry_count=row.retry_count,
        item_results=dict(row.item_results or {}),
    )
