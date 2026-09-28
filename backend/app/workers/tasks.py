from __future__ import annotations

import uuid

import dramatiq
import structlog
from dramatiq.brokers.redis import RedisBroker

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.runtime_report import log_runtime_config
from app.db.session import AsyncSessionLocal, held_advisory_lock
from app.repositories.workflow_repository import advisory_lock_key
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


class _RuntimeConfigLogger(dramatiq.Middleware):
    """Logs the (credential-free) runtime configuration once when a worker
    process boots - the counterpart of the API's startup log, so the two
    `config_fingerprint` values can be compared."""

    def after_worker_boot(self, broker, worker) -> None:
        configure_logging(settings.log_level, json_logs=settings.log_json)
        log_runtime_config(settings, "worker", structlog.get_logger("deltaledger.startup"))


broker.add_middleware(_RuntimeConfigLogger())
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


@dramatiq.actor(max_retries=3, time_limit=int(settings.worker_default_time_limit_seconds * 1000))
def process_filing_task(filing_id: str) -> None:
    run_worker_coroutine(_process_filing(uuid.UUID(filing_id)))


async def _process_filing(filing_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FilingProcessingService(session, get_settings())
        await service.process_filing(filing_id)


@dramatiq.actor(max_retries=3, time_limit=int(settings.worker_default_time_limit_seconds * 1000))
def process_comparison_task(comparison_id: str) -> None:
    run_worker_coroutine(_process_comparison(uuid.UUID(comparison_id)))


async def _process_comparison(comparison_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FilingComparisonService(session, get_settings())
        await service.process_comparison(comparison_id)


@dramatiq.actor(max_retries=3, time_limit=int(settings.worker_default_time_limit_seconds * 1000))
def extract_financial_claims_task(filing_id: str) -> None:
    run_worker_coroutine(_extract_financial_claims(uuid.UUID(filing_id)))


async def _extract_financial_claims(filing_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FinancialVerificationService(session, get_settings())
        await service.extract_claims_for_filing(filing_id)


@dramatiq.actor(max_retries=3, time_limit=int(settings.worker_default_time_limit_seconds * 1000))
def verify_financial_claim_task(claim_id: str) -> None:
    run_worker_coroutine(_verify_financial_claim(uuid.UUID(claim_id)))


async def _verify_financial_claim(claim_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FinancialVerificationService(session, get_settings())
        await service.verify_claim(claim_id)


@dramatiq.actor(max_retries=3, time_limit=int(settings.worker_default_time_limit_seconds * 1000))
def verify_comparison_financials_task(comparison_id: str) -> None:
    run_worker_coroutine(_verify_comparison_financials(uuid.UUID(comparison_id)))


async def _verify_comparison_financials(comparison_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = FinancialVerificationService(session, get_settings())
        await service.verify_claims_for_comparison(comparison_id)


@dramatiq.actor(max_retries=3, time_limit=int(settings.worker_default_time_limit_seconds * 1000))
def analyze_contradictions_for_comparison(comparison_id: str) -> None:
    run_worker_coroutine(_analyze_contradictions_for_comparison(uuid.UUID(comparison_id)))


async def _analyze_contradictions_for_comparison(comparison_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = ContradictionAnalysisService(session, get_settings())
        await service.analyze_comparison(comparison_id)


@dramatiq.actor(
    max_retries=1, time_limit=int(settings.analysis_workflow_time_limit_seconds * 1000)
)
def run_analysis_workflow_task(analysis_run_id: str) -> None:
    run_worker_coroutine(_run_analysis_workflow(uuid.UUID(analysis_run_id)))


async def _run_analysis_workflow(analysis_run_id: uuid.UUID) -> None:
    # The run lock lives on its own dedicated connection (see
    # held_advisory_lock) precisely so that AnalysisWorkflowService is free
    # to close and reopen `session` around long BGE/Gemini work without
    # silently dropping this lock.
    async with held_advisory_lock(advisory_lock_key(analysis_run_id)) as acquired:
        if not acquired:
            return
        async with AsyncSessionLocal() as session:
            service = AnalysisWorkflowService(session, get_settings())
            await service.run_analysis(analysis_run_id)


@dramatiq.actor(
    max_retries=1, time_limit=int(settings.analysis_workflow_time_limit_seconds * 1000)
)
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
    async with held_advisory_lock(advisory_lock_key(analysis_run_id)) as acquired:
        if not acquired:
            return
        async with AsyncSessionLocal() as session:
            service = AnalysisWorkflowService(session, get_settings())
            await service.resume_analysis(analysis_run_id, review_request_id)


def main() -> None:
    import dramatiq.cli

    dramatiq.cli.main(["dramatiq", "app.workers.tasks"])


if __name__ == "__main__":
    main()
