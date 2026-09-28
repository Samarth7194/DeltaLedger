from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.batching import (
    OUTCOME_REQUIRES_REVIEW,
    OUTCOME_SUCCESS,
    OUTCOME_ZERO_RESULT,
    BatchingConfig,
    BatchItem,
    canonical_hash,
    item_request_id,
    plan_batches,
)
from app.ai.financial_claims import (
    ClaimBatchItem,
    ClaimExtractionResponse,
    FinancialClaimExtraction,
    claim_item_tokens,
)
from app.ai.inference import UsageTotals, collect_usage
from app.ai.openai_compatible import ProviderRequestError, StructuredOutputError
from app.core.config import Settings
from app.db.models.workflow import BATCH_STAGE_FINANCIAL_CLAIMS
from app.db.session import AsyncSessionLocal
from app.db.session import held_advisory_lock as _default_held_advisory_lock
from app.repositories.comparison_repository import ComparisonRepository
from app.repositories.financial_repository import FinancialRepository, advisory_lock_key
from app.repositories.stage_batch_repository import (
    ProviderErrorInfo,
    StageBatchRepository,
    StageBatchState,
    count_outcomes,
    safe_error_message,
)
from app.services.batch_logging import describe_attempt, log_batch_event
from app.services.financial_claim_extraction_service import FinancialClaimExtractionService

logger = logging.getLogger(__name__)
_STAGE_LABEL = "Claim extraction"

# Outcomes that need no further model work when a batch is retried. A
# requires_review item is retried: it never got a usable analysis.
_FINAL_OUTCOMES = (OUTCOME_SUCCESS, OUTCOME_ZERO_RESULT)


@dataclass
class _ClaimWorkItem:
    """One passage side of one disclosure change whose claims are extracted.

    `identity` is stable across runs and content-sensitive (persisted section
    and passage ids plus a hash of the canonical input content), so it is what
    a batch's identity is built from.
    """

    identity: str
    request_id: str
    text: str
    filing_id: uuid.UUID
    section_id: uuid.UUID
    passage_id: uuid.UUID | None
    change_id: uuid.UUID
    comparison_id: uuid.UUID | None
    section_metadata: dict[str, object]
    estimated_tokens: int = 0


@dataclass
class ClaimExtractionStats:
    items_total: int = 0
    deterministic_items: int = 0
    model_items: int = 0
    claims: int = 0
    provider_calls: int = 0
    # Item accounting over the batched (model) items. "requires_review" means
    # the model never produced a usable analysis for the passage - distinct
    # from "zero_result", where it analysed the passage and found no claims.
    successful_items: int = 0
    zero_result_items: int = 0
    requires_review_items: int = 0
    batches_total: int = 0
    batches_skipped: int = 0
    batches_executed: int = 0
    actual_input_tokens: int | None = None
    actual_output_tokens: int | None = None
    actual_total_tokens: int | None = None

    def add_usage(self, usage: UsageTotals | None) -> None:
        if usage is None:
            return
        self.actual_input_tokens = _add_optional(self.actual_input_tokens, usage.input_tokens)
        self.actual_output_tokens = _add_optional(self.actual_output_tokens, usage.output_tokens)
        self.actual_total_tokens = _add_optional(self.actual_total_tokens, usage.resolved_total())

    def as_metrics(self) -> dict[str, int | None]:
        return {
            "claim_items_total": self.items_total,
            "claim_items_deterministic": self.deterministic_items,
            "claim_items_needing_model": self.model_items,
            "claims": self.claims,
            "claim_provider_calls": self.provider_calls,
            "claim_items_successful": self.successful_items,
            "claim_items_zero_result": self.zero_result_items,
            "claim_items_requires_review": self.requires_review_items,
            "claim_batches_total": self.batches_total,
            "claim_batches_skipped": self.batches_skipped,
            "claim_batches_executed": self.batches_executed,
            "claim_actual_input_tokens": self.actual_input_tokens,
            "claim_actual_output_tokens": self.actual_output_tokens,
            "claim_actual_total_tokens": self.actual_total_tokens,
            "status": 1,
        }


class ClaimBatchExtractionService:
    """Financial-claim extraction for one comparison, as durable batches.

    Deterministic extraction (regex/registry, no provider) runs first for every
    passage and is not batched. Only passages it finds nothing in go to the
    model; those are planned into token-bounded batches, each stored and
    marked complete in one transaction, so a retry resumes at the first
    incomplete batch and a completed batch's claims (already persisted) are
    never requested again.

    Every batched item ends with an explicit durable outcome: `success` (claims
    stored), `zero_result` (analysed, none found) or `requires_review` (no
    usable analysis after repair/retry; nothing fabricated).
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        extraction: FinancialClaimExtractionService,
        *,
        session_factory: Callable[[], AsyncSession] | None = None,
        batches_factory: Callable[[AsyncSession], StageBatchRepository] | None = None,
        lock_factory: Callable[[int], AbstractAsyncContextManager[bool]] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.extraction = extraction
        self.financial = FinancialRepository(session)
        self.comparisons = ComparisonRepository(session)
        self._batches_factory = batches_factory or StageBatchRepository
        self.batches = self._batches_factory(session)
        self._session_factory = session_factory or AsyncSessionLocal
        self._lock_factory = lock_factory or _default_held_advisory_lock

    async def extract_for_comparison(
        self,
        comparison_id: uuid.UUID,
        *,
        analysis_run_id: uuid.UUID | None = None,
    ) -> dict[str, int | None]:
        # Dedicated-connection lock: this session is closed/reopened around
        # each provider call, which would silently drop a session-level lock.
        async with self._lock_factory(advisory_lock_key(comparison_id)) as acquired:
            if not acquired:
                return {"claims": 0, "status": 0}
            stats = await self._extract_locked(comparison_id, analysis_run_id)
        return stats.as_metrics()

    async def _extract_locked(
        self,
        comparison_id: uuid.UUID,
        analysis_run_id: uuid.UUID | None,
    ) -> ClaimExtractionStats:
        stats = ClaimExtractionStats()
        items = await self._collect_items(comparison_id)
        stats.items_total = len(items)
        allowed_metrics = [
            metric.canonical_name
            for metric in await self.financial.list_metric_definitions(active_only=True)
        ]

        model_items: list[_ClaimWorkItem] = []
        for item in items:
            deterministic = await self.extraction.deterministic_extract(item.text)
            if deterministic:
                stats.deterministic_items += 1
                stats.claims += await self._persist(item, deterministic)
            else:
                model_items.append(item)
        stats.model_items = len(model_items)
        await self.session.commit()
        await self.session.close()

        extractor = self.extraction.extractor
        multi = self.settings.ai_batch_multi_item_requests and hasattr(
            extractor, "extract_claims_batch"
        )
        for item in model_items:
            item.estimated_tokens = claim_item_tokens(item.text, item.section_metadata)
        plan = plan_batches(
            [BatchItem(item.identity, item.estimated_tokens) for item in model_items],
            BatchingConfig.from_settings(self.settings),
            fixed_overhead_tokens=(
                extractor.batch_fixed_overhead_tokens(allowed_metrics) if multi else 0
            ),
        )
        stats.batches_total = len(plan)
        by_identity = {item.identity: item for item in model_items}
        states: list[StageBatchState | None]
        if analysis_run_id is not None and plan:
            states = list(
                await self.batches.sync_plan(
                    analysis_run_id,
                    BATCH_STAGE_FINANCIAL_CLAIMS,
                    plan,
                    model_name=extractor.model_name,
                    prompt_version=(
                        extractor.batch_prompt_version if multi else extractor.prompt_version
                    ),
                    context_hash=_context_hash(extractor, allowed_metrics),
                )
            )
        else:
            states = [None] * len(plan)
        await self.session.commit()
        await self.session.close()

        for planned, state in zip(plan, states, strict=True):
            if state is not None and state.status == "completed":
                # Its claims were persisted in the same transaction that
                # marked it complete; nothing to request or redo.
                stats.batches_skipped += 1
                self._count(stats, state.item_results)
                log_batch_event(
                    logger,
                    stage_label=_STAGE_LABEL,
                    index=planned.index,
                    total=planned.total,
                    event="skipped (already completed)",
                    scope=f"comparison {comparison_id}",
                )
                continue
            group = [by_identity[identity] for identity in planned.identities]
            done = {
                identity
                for identity, record in (state.item_results if state else {}).items()
                if isinstance(record, dict) and record.get("status") in _FINAL_OUTCOMES
            }
            todo = [item for item in group if item.identity not in done]
            event, note = describe_attempt(
                state.status if state else None, state.retry_count if state else 0
            )
            log_batch_event(
                logger,
                stage_label=_STAGE_LABEL,
                index=planned.index,
                total=planned.total,
                event=f"{event} ({note})" if note else event,
                scope=f"comparison {comparison_id}",
                items=planned.item_count,
                items_still_to_do=len(todo) if len(todo) != planned.item_count else None,
                estimated_input_tokens=planned.estimated_input_tokens,
                oversized_single_item=True if planned.oversized else None,
            )
            if state is not None:
                await self.batches.mark_processing(state.id)
                await self.session.commit()
                await self.session.close()
            calls_before = stats.provider_calls
            records: dict[str, dict[str, object]] = {}
            usage: UsageTotals | None = None
            try:
                with collect_usage() as usage:
                    error = await self._run_batch(todo, allowed_metrics, multi, stats, records)
                if error is not None:
                    await self.session.commit()
                    raise error
                if state is not None:
                    # One transaction: this batch's claims (persisted by
                    # _run_batch), its item outcomes and its `completed` mark.
                    await self.batches.mark_completed(
                        state.id,
                        provider_calls=stats.provider_calls - calls_before,
                        item_results=records,
                        usage=usage,
                    )
                stats.add_usage(usage)
                log_batch_event(
                    logger,
                    stage_label=_STAGE_LABEL,
                    index=planned.index,
                    total=planned.total,
                    event="completed",
                    scope=f"comparison {comparison_id}",
                    provider_calls=stats.provider_calls - calls_before,
                    actual_input_tokens=usage.input_tokens if usage else None,
                    actual_output_tokens=usage.output_tokens if usage else None,
                    actual_total_tokens=usage.resolved_total() if usage else None,
                    items_needing_review=(
                        sum(
                            1
                            for r in records.values()
                            if r.get("status") == OUTCOME_REQUIRES_REVIEW
                        )
                        or None
                    ),
                )
                await self.session.commit()
                await self.session.close()
            except Exception as exc:
                log_batch_event(
                    logger,
                    stage_label=_STAGE_LABEL,
                    index=planned.index,
                    total=planned.total,
                    event="failed",
                    level=logging.WARNING,
                    scope=f"comparison {comparison_id}",
                    error=getattr(exc, "error_subtype", None) or exc.__class__.__name__,
                    retry_after_seconds=getattr(exc, "retry_after_seconds", None),
                    completed_parts_kept=planned.index - 1,
                )
                stats.add_usage(usage)
                await self._record_batch_failure(
                    state, exc, stats.provider_calls - calls_before, records, usage
                )
                raise
            self._count(stats, {**(state.item_results if state else {}), **records})
            stats.batches_executed += 1
        return stats

    @staticmethod
    def _count(stats: ClaimExtractionStats, item_results) -> None:
        successful, zero_result, requires_review = count_outcomes(item_results)
        stats.successful_items += successful
        stats.zero_result_items += zero_result
        stats.requires_review_items += requires_review

    async def _run_batch(
        self,
        group: list[_ClaimWorkItem],
        allowed_metrics: list[str],
        multi: bool,
        stats: ClaimExtractionStats,
        records: dict[str, dict[str, object]],
    ) -> Exception | None:
        """Extract every item of one batch and persist what resolved. Fills
        `records` with each item's outcome. Returns the provider-level error
        that stopped it early (after persisting the items done before it), or
        None."""
        extractor = self.extraction.extractor
        outcomes: dict[str, list[FinancialClaimExtraction] | None] = {}
        failed: dict[str, str] = {}
        error: Exception | None = None
        if multi and len(group) > 1:
            stats.provider_calls += 1
            try:
                outcomes = await extractor.extract_claims_batch(
                    [
                        ClaimBatchItem(
                            item_id=item.request_id,
                            text=item.text,
                            section_metadata=item.section_metadata,
                        )
                        for item in group
                    ],
                    allowed_metrics,
                )
            except Exception as exc:
                return exc
        for item in group:
            if outcomes.get(item.request_id) is not None:
                continue
            # Missing/invalid in the multi-item response (or per-item mode):
            # this item alone is requested again; neighbours are unaffected.
            try:
                stats.provider_calls += 1
                outcomes[item.request_id] = await extractor.extract_claims(
                    item.text, item.section_metadata, allowed_metrics
                )
            except StructuredOutputError as exc:
                # Never analysed. Not "no claims": nothing is fabricated, and
                # the fact is recorded durably below.
                failed[item.request_id] = safe_error_message(exc)
                outcomes[item.request_id] = None
            except Exception as exc:
                error = exc
                break
        for item in group:
            if item.request_id in failed:
                records[item.identity] = {
                    "status": OUTCOME_REQUIRES_REVIEW,
                    "error": "StructuredOutputError",
                    "message": failed[item.request_id],
                }
                continue
            extracted = outcomes.get(item.request_id)
            if extracted is None:
                continue  # not reached (provider error above)
            stored = await self._persist(item, extracted)
            stats.claims += stored
            records[item.identity] = {
                "status": OUTCOME_SUCCESS if extracted else OUTCOME_ZERO_RESULT,
                "claims": stored,
            }
        return error

    async def _persist(
        self,
        item: _ClaimWorkItem,
        extracted: list[FinancialClaimExtraction],
    ) -> int:
        stored = await self.extraction.persist_extractions(
            filing_id=item.filing_id,
            source_section_id=item.section_id,
            passage_id=item.passage_id,
            extracted=extracted,
            comparison_id=item.comparison_id,
            disclosure_change_id=item.change_id,
        )
        return len(stored)

    async def _collect_items(self, comparison_id: uuid.UUID) -> list[_ClaimWorkItem]:
        changes = await self.comparisons.list_changes(comparison_id, limit=1000)
        items: list[_ClaimWorkItem] = []
        seen: set[str] = set()
        for change in changes:
            for side in ("current", "previous"):
                evidence = change.supporting_evidence.get(side)
                text = change.current_text if side == "current" else change.previous_text
                if not isinstance(evidence, dict) or not text:
                    continue
                section_id = evidence.get("section_id")
                passage_id = evidence.get("passage_id")
                filing_id = evidence.get("filing_id")
                if not section_id or not filing_id:
                    continue
                section = await self.financial.get_section(uuid.UUID(str(section_id)))
                if section is None:
                    continue
                passage = (
                    await self.financial.get_passage(uuid.UUID(str(passage_id)))
                    if passage_id
                    else None
                )
                section_metadata = {
                    "section_type": section.section_type,
                    "section_title": section.section_title,
                }
                # Content-sensitive: the same ids with different text (or
                # section metadata) is a different item, so a batch completed
                # for the old content is never reused.
                content_hash = canonical_hash({"text": text, "section": section_metadata})
                identity = (
                    f"{section.id}|{passage.id if passage is not None else '-'}|{content_hash}"
                )
                if identity in seen:
                    continue
                seen.add(identity)
                items.append(
                    _ClaimWorkItem(
                        identity=identity,
                        request_id=item_request_id(identity),
                        text=text,
                        filing_id=uuid.UUID(str(filing_id)),
                        section_id=section.id,
                        passage_id=passage.id if passage is not None else None,
                        change_id=change.id,
                        comparison_id=change.comparison_id,
                        section_metadata=section_metadata,
                    )
                )
        return items

    async def _record_batch_failure(
        self,
        state: StageBatchState | None,
        exc: Exception,
        provider_calls: int,
        records: dict[str, dict[str, object]],
        usage: UsageTotals | None,
    ) -> None:
        if state is None:
            return
        try:
            await self.session.rollback()
        except Exception:
            pass
        try:
            async with self._session_factory() as recovery_session:
                await self._batches_factory(recovery_session).mark_failed(
                    state.id,
                    error_category=getattr(exc, "error_category", None) or exc.__class__.__name__,
                    error_message=safe_error_message(exc),
                    provider_calls=provider_calls,
                    provider_error=(
                        ProviderErrorInfo(
                            error_type=exc.error_subtype,
                            retry_after_seconds=exc.retry_after_seconds,
                        )
                        if isinstance(exc, ProviderRequestError)
                        else None
                    ),
                    item_results=records,
                    usage=usage,
                )
                await recovery_session.commit()
        except Exception:
            logger.warning("could not record failure of batch %s", state.id, exc_info=True)


def _context_hash(extractor, allowed_metrics: list[str]) -> str:
    """Fingerprint of request content shared by every item: the allowed
    metrics, the response schema and (when provided) the real prompt text."""
    return canonical_hash(
        {
            "allowed_metrics": allowed_metrics,
            "result_schema": ClaimExtractionResponse.model_json_schema(),
            "prompt_fingerprint": getattr(extractor, "prompt_fingerprint", ""),
        }
    )


def _add_optional(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return value if current is None else current + value
