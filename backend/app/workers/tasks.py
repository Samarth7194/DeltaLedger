from __future__ import annotations

import uuid

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.repositories.workflow_repository import WorkflowRepository
from app.services.analysis_workflow_service import AnalysisWorkflowService
from app.services.contradiction_analysis_service import ContradictionAnalysisService
from app.services.filing_comparison_service import FilingComparisonService
from app.services.filing_processing_service import FilingProcessingService
from app.services.financial_verification_service import FinancialVerificationService
from app.workers.async_runner import run_worker_coroutine

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


def enqueue_analyze_contradictions(comparison_id: uuid.UUID) -> str:
    message = analyze_contradictions_for_comparison.send(str(comparison_id))
    return message.message_id


def enqueue_run_analysis_workflow(analysis_run_id: uuid.UUID) -> str:
    message = run_analysis_workflow_task.send(str(analysis_run_id))
    return message.message_id


def enqueue_resume_analysis_workflow(
    analysis_run_id: uuid.UUID,
    review_request_id: uuid.UUID,
) -> str:
    message = resume_analysis_workflow_task.send(str(analysis_run_id), str(review_request_id))
    return message.message_id


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def process_filing_task(filing_id: str) -> None:
    run_worker_coroutine(_process_filing(uuid.UUID(filing_id)))


async def _process_filing(filing_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FilingProcessingService(session, get_settings())
        await service.process_filing(filing_id)


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def process_comparison_task(comparison_id: str) -> None:
    run_worker_coroutine(_process_comparison(uuid.UUID(comparison_id)))


async def _process_comparison(comparison_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FilingComparisonService(session, get_settings())
        await service.process_comparison(comparison_id)


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def extract_financial_claims_task(filing_id: str) -> None:
    run_worker_coroutine(_extract_financial_claims(uuid.UUID(filing_id)))


async def _extract_financial_claims(filing_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FinancialVerificationService(session, get_settings())
        await service.extract_claims_for_filing(filing_id)


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def verify_financial_claim_task(claim_id: str) -> None:
    run_worker_coroutine(_verify_financial_claim(uuid.UUID(claim_id)))


async def _verify_financial_claim(claim_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FinancialVerificationService(session, get_settings())
        await service.verify_claim(claim_id)


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def verify_comparison_financials_task(comparison_id: str) -> None:
    run_worker_coroutine(_verify_comparison_financials(uuid.UUID(comparison_id)))


async def _verify_comparison_financials(comparison_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FinancialVerificationService(session, get_settings())
        await service.verify_claims_for_comparison(comparison_id)


@dramatiq.actor(max_retries=3, time_limit=30 * 60 * 1000)
def analyze_contradictions_for_comparison(comparison_id: str) -> None:
    run_worker_coroutine(_analyze_contradictions_for_comparison(uuid.UUID(comparison_id)))


async def _analyze_contradictions_for_comparison(comparison_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = ContradictionAnalysisService(session, get_settings())
        await service.analyze_comparison(comparison_id)


@dramatiq.actor(max_retries=1, time_limit=60 * 60 * 1000)
def run_analysis_workflow_task(analysis_run_id: str) -> None:
    run_worker_coroutine(_run_analysis_workflow(uuid.UUID(analysis_run_id)))


async def _run_analysis_workflow(analysis_run_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        repo = WorkflowRepository(session)
        if not await repo.try_acquire_run_lock(analysis_run_id):
            return
        try:
            service = AnalysisWorkflowService(session, get_settings())
            await service.run_analysis(analysis_run_id)
        finally:
            await repo.release_run_lock(analysis_run_id)


@dramatiq.actor(max_retries=1, time_limit=60 * 60 * 1000)
def resume_analysis_workflow_task(analysis_run_id: str, review_request_id: str) -> None:
    run_worker_coroutine(
        _resume_analysis_workflow(
            uuid.UUID(analysis_run_id),
            uuid.UUID(review_request_id),
        )
    )


async def _resume_analysis_workflow(
    analysis_run_id: uuid.UUID,
    review_request_id: uuid.UUID,
) -> None:
    async with AsyncSessionLocal() as session:
        repo = WorkflowRepository(session)
        if not await repo.try_acquire_run_lock(analysis_run_id):
            return
        try:
            service = AnalysisWorkflowService(session, get_settings())
            await service.resume_analysis(analysis_run_id, review_request_id)
        finally:
            await repo.release_run_lock(analysis_run_id)


def main() -> None:
    import dramatiq.cli

    dramatiq.cli.main(["dramatiq", "app.workers.tasks"])


if __name__ == "__main__":
    main()
