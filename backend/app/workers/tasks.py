from __future__ import annotations

import uuid

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.filing_comparison_service import FilingComparisonService
from app.services.filing_processing_service import FilingProcessingService
from app.services.financial_verification_service import FinancialVerificationService

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


def enqueue_process_comparison(comparison_id: uuid.UUID) -> str:
    message = process_comparison_task.send(str(comparison_id))
    return message.message_id


def enqueue_extract_financial_claims(filing_id: uuid.UUID) -> str:
    message = extract_financial_claims_task.send(str(filing_id))
    return message.message_id


def enqueue_verify_financial_claim(claim_id: uuid.UUID) -> str:
    message = verify_financial_claim_task.send(str(claim_id))
    return message.message_id


def enqueue_verify_comparison_financials(comparison_id: uuid.UUID) -> str:
    message = verify_comparison_financials_task.send(str(comparison_id))
    return message.message_id


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def process_filing_task(filing_id: str) -> None:
    import asyncio

    asyncio.run(_process_filing(uuid.UUID(filing_id)))


async def _process_filing(filing_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FilingProcessingService(session, get_settings())
        await service.process_filing(filing_id)


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def process_comparison_task(comparison_id: str) -> None:
    import asyncio

    asyncio.run(_process_comparison(uuid.UUID(comparison_id)))


async def _process_comparison(comparison_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FilingComparisonService(session, get_settings())
        await service.process_comparison(comparison_id)


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def extract_financial_claims_task(filing_id: str) -> None:
    import asyncio

    asyncio.run(_extract_financial_claims(uuid.UUID(filing_id)))


async def _extract_financial_claims(filing_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FinancialVerificationService(session, get_settings())
        await service.extract_claims_for_filing(filing_id)


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def verify_financial_claim_task(claim_id: str) -> None:
    import asyncio

    asyncio.run(_verify_financial_claim(uuid.UUID(claim_id)))


async def _verify_financial_claim(claim_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FinancialVerificationService(session, get_settings())
        await service.verify_claim(claim_id)


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def verify_comparison_financials_task(comparison_id: str) -> None:
    import asyncio

    asyncio.run(_verify_comparison_financials(uuid.UUID(comparison_id)))


async def _verify_comparison_financials(comparison_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FinancialVerificationService(session, get_settings())
        await service.verify_claims_for_comparison(comparison_id)


def main() -> None:
    import dramatiq.cli

    dramatiq.cli.main(["dramatiq", "app.workers.tasks"])


if __name__ == "__main__":
    main()
