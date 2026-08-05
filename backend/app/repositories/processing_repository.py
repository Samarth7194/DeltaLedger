from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FilingProcessingStage


class ProcessingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_stages(self, filing_id: uuid.UUID) -> list[FilingProcessingStage]:
        stmt = (
            select(FilingProcessingStage)
            .where(FilingProcessingStage.filing_id == filing_id)
            .order_by(FilingProcessingStage.created_at)
        )
        return list((await self.session.scalars(stmt)).all())

    async def try_acquire_filing_lock(self, filing_id: uuid.UUID) -> bool:
        lock_key = advisory_lock_key(filing_id)
        return bool(await self.session.scalar(select(func.pg_try_advisory_lock(lock_key))))

    async def release_filing_lock(self, filing_id: uuid.UUID) -> bool:
        lock_key = advisory_lock_key(filing_id)
        return bool(await self.session.scalar(select(func.pg_advisory_unlock(lock_key))))

    async def start_stage(self, filing_id: uuid.UUID, stage_name: str) -> float:
        stage = await self._get_or_create(filing_id, stage_name)
        stage.status = "running"
        stage.started_at = datetime.now(UTC)
        stage.completed_at = None
        stage.error_code = None
        stage.error_message = None
        stage.attempt_count += 1
        return time.perf_counter()

    async def complete_stage(
        self,
        filing_id: uuid.UUID,
        stage_name: str,
        started_at_monotonic: float,
        metrics: dict[str, object] | None = None,
    ) -> None:
        stage = await self._get_or_create(filing_id, stage_name)
        stage.status = "completed"
        stage.completed_at = datetime.now(UTC)
        stage.duration_ms = int((time.perf_counter() - started_at_monotonic) * 1000)
        stage.metrics = metrics or {}

    async def fail_stage(
        self,
        filing_id: uuid.UUID,
        stage_name: str,
        started_at_monotonic: float,
        error: Exception,
    ) -> None:
        stage = await self._get_or_create(filing_id, stage_name)
        stage.status = "failed"
        stage.completed_at = datetime.now(UTC)
        stage.duration_ms = int((time.perf_counter() - started_at_monotonic) * 1000)
        stage.error_code = error.__class__.__name__
        stage.error_message = str(error)

    async def _get_or_create(self, filing_id: uuid.UUID, stage_name: str) -> FilingProcessingStage:
        stmt = select(FilingProcessingStage).where(
            FilingProcessingStage.filing_id == filing_id,
            FilingProcessingStage.stage_name == stage_name,
        )
        stage = await self.session.scalar(stmt)
        if stage is None:
            stage = FilingProcessingStage(filing_id=filing_id, stage_name=stage_name)
            self.session.add(stage)
            await self.session.flush()
        return stage


def advisory_lock_key(filing_id: uuid.UUID) -> int:
    return filing_id.int % (2**63 - 1)
