from __future__ import annotations

import uuid

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.filing_processing_service import FilingProcessingService

settings = get_settings()
broker = RedisBroker(
    url=settings.redis_url,
    socket_connect_timeout=settings.redis_connect_timeout_seconds,
    socket_timeout=settings.redis_socket_timeout_seconds,
    retry_on_timeout=True,
)
dramatiq.set_broker(broker)


def enqueue_process_filing(filing_id: uuid.UUID) -> str:
    message = process_filing_task.send(str(filing_id))
    return message.message_id


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def process_filing_task(filing_id: str) -> None:
    import asyncio

    asyncio.run(_process_filing(uuid.UUID(filing_id)))


async def _process_filing(filing_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FilingProcessingService(session, get_settings())
        await service.process_filing(filing_id)


def main() -> None:
    import dramatiq.cli

    dramatiq.cli.main(["dramatiq", "app.workers.tasks"])


if __name__ == "__main__":
    main()
