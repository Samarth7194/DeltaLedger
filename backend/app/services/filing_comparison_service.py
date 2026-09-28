from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.batching import BatchingConfig, BatchItem, item_request_id, plan_batches
from app.ai.embeddings import create_embedding_service
from app.ai.inference import UsageTotals, collect_usage
from app.ai.openai_compatible import ProviderRequestError
from app.ai.reranker import create_reranker
from app.ai.semantic_change import ChangeClassificationResult, create_change_classifier
from app.core.config import Settings
from app.core.exceptions import DeltaLedgerError
from app.db.models import DisclosureChange, Filing, FilingChunk, FilingComparison, FilingSection
from app.db.models.workflow import BATCH_STAGE_DISCLOSURE_COMPARISON
from app.db.session import AsyncSessionLocal
from app.db.session import held_advisory_lock as _default_held_advisory_lock
from app.repositories.comparison_repository import ComparisonRepository, advisory_lock_key
from app.repositories.filing_repository import FilingRepository
from app.repositories.section_repository import SectionRepository
from app.repositories.stage_batch_repository import (
    ProviderErrorInfo,
    StageBatchRepository,
    StageBatchState,
    safe_error_message,
)
from app.services.batch_logging import describe_attempt, log_batch_event
from app.services.comparison_fingerprint import matching_fingerprint
from app.services.disclosure_change_service import (
    ClassificationCandidate,
    DisclosureChangeCallStats,
    DisclosureChangeService,
    FrozenFailures,
)
from app.services.passage_alignment_service import PassageAlignmentService
from app.services.passage_segmentation_service import PassageSegmentationService
from app.services.section_matching_service import SectionMatchingService

logger = logging.getLogger(__name__)
_STAGE_LABEL = "Disclosure classification"


class FilingComparisonError(DeltaLedgerError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ComparisonCreateResult:
    comparison_id: uuid.UUID
    status: str
    created: bool


class FilingComparisonService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        comparisons: ComparisonRepository | None = None,
        filings: FilingRepository | None = None,
        sections: SectionRepository | None = None,
        segmenter: PassageSegmentationService | None = None,
        matcher: SectionMatchingService | None = None,
        aligner: PassageAlignmentService | None = None,
        change_detector: DisclosureChangeService | None = None,
        session_factory: Callable[[], AsyncSession] | None = None,
        comparisons_factory: Callable[[AsyncSession], ComparisonRepository] | None = None,
        lock_factory: Callable[[int], AbstractAsyncContextManager[bool]] | None = None,
        batches: StageBatchRepository | None = None,
        batches_factory: Callable[[AsyncSession], StageBatchRepository] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self._batches_factory = batches_factory or StageBatchRepository
        self.batches = batches or self._batches_factory(session)
        self.comparisons = comparisons or ComparisonRepository(session)
        self.filings = filings or FilingRepository(session)
        self.sections = sections or SectionRepository(session)
        embeddings = create_embedding_service(settings)
        reranker = create_reranker(settings)
        self.segmenter = segmenter or PassageSegmentationService(settings)
        self.matcher = matcher or SectionMatchingService(settings, embeddings, reranker)
        self.aligner = aligner or PassageAlignmentService(settings, embeddings, reranker)
        self.change_detector = change_detector or DisclosureChangeService(
            settings, create_change_classifier(settings)
        )
        # Used only to recover from a dead `self.session` connection (see
        # _process_comparison_locked's exception handler) - never for the
        # normal per-stage work, which stays on `self.session`.
        self._session_factory = session_factory or AsyncSessionLocal
        self._comparisons_factory = comparisons_factory or ComparisonRepository
        # A separate, dedicated-connection lock (see held_advisory_lock) by
        # default; injectable so tests can avoid touching a real database.
        self._lock_factory = lock_factory or _default_held_advisory_lock

    async def create_comparison(
        self,
        *,
        current_filing_id: uuid.UUID,
        comparison_filing_id: uuid.UUID,
    ) -> ComparisonCreateResult:
        current, previous = await self.validate_pair(current_filing_id, comparison_filing_id)
        existing = await self.comparisons.get_existing_comparison(
            current_filing_id=current.id,
            comparison_filing_id=previous.id,
            comparison_version=self.settings.comparison_version,
        )
        comparison = await self.comparisons.create_comparison(
            company_id=current.company_id,
            current_filing_id=current.id,
            comparison_filing_id=previous.id,
            comparison_version=self.settings.comparison_version,
        )
        await self.session.commit()
        return ComparisonCreateResult(
            comparison_id=comparison.id,
            status=comparison.status,
            created=existing is None,
        )

    async def validate_pair(
        self,
        current_filing_id: uuid.UUID,
        comparison_filing_id: uuid.UUID,
    ) -> tuple[Filing, Filing]:
        if current_filing_id == comparison_filing_id:
            raise FilingComparisonError(
                "same_filing",
                "Current and comparison filings must differ.",
            )
        current = await self.filings.get(current_filing_id)
        previous = await self.filings.get(comparison_filing_id)
        if current is None or previous is None:
            raise FilingComparisonError("filing_not_found", "Both filings must exist.")
        if current.company_id != previous.company_id:
            raise FilingComparisonError(
                "different_companies",
                "Filings must belong to the same company.",
            )
        if current.form_type != "10-Q" or previous.form_type != "10-Q":
            raise FilingComparisonError(
                "unsupported_form",
                "Phase 3 comparison supports 10-Q only.",
            )
        current_period = _period(current)
        previous_period = _period(previous)
        if current_period == previous_period:
            raise FilingComparisonError("same_period", "Filing periods must be different.")
        if current_period <= previous_period:
            raise FilingComparisonError(
                "invalid_period_order",
                "Current filing period must be later than comparison filing period.",
            )
        if not await self._has_parsed_content(
            current.id
        ) or not await self._has_parsed_content(previous.id):
            raise FilingComparisonError(
                "missing_parsed_content",
                "Both filings need parsed sections and chunks.",
            )
        return current, previous

    async def process_comparison(
        self,
        comparison_id: uuid.UUID,
        *,
        analysis_run_id: uuid.UUID | None = None,
    ) -> None:
        """`analysis_run_id`, when given, is the workflow run whose durable
        batch ledger records classification progress (see
        AnalysisStageBatch). Without it the comparison still runs in
        token-bounded batches, but no progress is persisted."""
        # The comparison lock lives on its own dedicated connection,
        # independent of `self.session`: _process_comparison_locked closes
        # and reopens `self.session` around each BGE/Gemini call below, and
        # a session-level advisory lock held on that same connection would
        # be silently dropped the first time that happens.
        async with self._lock_factory(advisory_lock_key(comparison_id)) as acquired:
            if not acquired:
                return
            await self._process_comparison_locked(comparison_id, analysis_run_id)

    async def _process_comparison_locked(
        self,
        comparison_id: uuid.UUID,
        analysis_run_id: uuid.UUID | None = None,
    ) -> None:
        comparison = await self.comparisons.get_comparison(comparison_id)
        if comparison is None:
            raise FilingComparisonError("comparison_not_found", "Comparison not found.")
        if comparison.status == "completed":
            return
        # Seed the reuse cache from whatever this comparison already
        # classified successfully in a prior attempt (e.g. a crash/retry
        # partway through). Must happen before anything below deletes and
        # recreates section/passage matches (which cascades away their
        # DisclosureChange rows) -- this is the only chance to capture them.
        known_results: dict[
            tuple[str | None, str | None], ChangeClassificationResult
        ] = {}
        for previous_text, current_text, original_output in (
            await self.comparisons.list_reusable_change_results(
                comparison.id,
                model_name=self.change_detector.classifier.model_name,
                prompt_version=self.change_detector.classifier.prompt_version,
                additional_prompt_versions=self.change_detector.reusable_prompt_versions,
            )
        ):
            try:
                known_results[(previous_text, current_text)] = (
                    ChangeClassificationResult.model_validate(original_output)
                )
            except Exception:
                # Malformed/legacy stored output must never block reuse of
                # everything else -- just skip this one entry and let it be
                # reclassified normally.
                continue
        # Passages a prior attempt could not classify (requires_review
        # placeholders). Only a *completed* batch treats these as final; a
        # batch that is being retried gets to try them again.
        prior_failures: FrozenFailures = {
            (previous_text, current_text): output
            for previous_text, current_text, output in (
                await self.comparisons.list_failed_change_placeholders(
                    comparison.id,
                    model_name=self.change_detector.classifier.model_name,
                )
            )
        }
        stats = DisclosureChangeCallStats()
        try:
            await self.comparisons.set_status(comparison, "matching_sections")
            current_sections = await self.sections.get_sections_with_chunks(
                comparison.current_filing_id
            )
            previous_sections = await self.sections.get_sections_with_chunks(
                comparison.comparison_filing_id
            )
            await self._segment_sections(current_sections + previous_sections)
            # Everything match_sections needs (sections, their eagerly-loaded
            # chunks, segmented passages) is already loaded in memory and
            # match_sections never touches the database - commit AND close
            # now so this read-only transaction is durable and the physical
            # connection is actually returned to the pool before the
            # (possibly long) CPU-bound BGE work below, instead of held open
            # (and idle) across it. expire_on_commit=False, plus only ever
            # reading already-loaded plain columns afterwards, keeps the
            # loaded objects safely usable once detached.
            await self.session.commit()
            await self.session.close()
            section_by_id = {
                section.id: section for section in current_sections + previous_sections
            }
            fingerprint = matching_fingerprint(
                settings=self.settings,
                comparison=comparison,
                embedding_model_name=self.matcher.embeddings.model_name,
                embedding_model_version=self.matcher.embeddings.model_version,
                current_sections=current_sections,
                previous_sections=previous_sections,
            )
            matching_started = time.perf_counter()
            reused = await self._load_reusable_matching(comparison.id, fingerprint)
            if reused is not None:
                stored_section_matches, all_passage_matches = reused
                matching_reused = True
                logger.info(
                    "comparison %s: reusing persisted matching (%d section matches, "
                    "%d passage matches); inputs, models and config unchanged",
                    comparison.id,
                    len(stored_section_matches),
                    len(all_passage_matches),
                )
            else:
                matching_reused = False
                stored_section_matches, all_passage_matches = await self._recompute_matching(
                    comparison,
                    fingerprint,
                    current_sections,
                    previous_sections,
                )
            matching_seconds = round(time.perf_counter() - matching_started, 2)

            # Re-fetch again: the loop's per-section close() above detached
            # `comparison` (possibly more than once).
            comparison = await self._require_comparison(comparison.id)
            await self.comparisons.set_status(comparison, "detecting_changes")
            passages = {
                passage.id: passage
                for section in current_sections + previous_sections
                for passage in await self._passages(section.id)
            }
            # detect_change only calls the Gemini classifier and never
            # touches the database (verified: it reads only already-loaded
            # plain columns off `passages`/`section_by_id`) - commit and
            # close before the classification loop's Gemini calls instead of
            # holding this connection open (and idle, for potentially
            # several minutes of paced/backed-off requests) across them.
            await self.session.commit()
            await self.session.close()
            logger.info(
                "comparison %s: starting classification of %d candidate pairs "
                "(known_results seeded with %d prior result(s))",
                comparison.id,
                len(all_passage_matches),
                len(known_results),
            )
            candidates = [
                self.change_detector.prepare_candidate(
                    comparison_id=comparison.id,
                    section_match=section_match,
                    passage_match=passage_match,
                    current_passage=passages.get(passage_match.current_passage_id),
                    previous_passage=passages.get(passage_match.previous_passage_id),
                    current_section=section_by_id.get(section_match.current_section_id),
                    previous_section=section_by_id.get(section_match.previous_section_id),
                    stats=stats,
                )
                for section_match in stored_section_matches
                for passage_match in all_passage_matches
                if passage_match.section_match_id == section_match.id
            ]
            # A fixed order that does not depend on how the matches were loaded
            # (fresh computation vs. reused rows come back in arbitrary DB
            # order): batches are planned over this order, so it must be the
            # same on every run for completed parts to line up.
            candidates.sort(key=_candidate_order_key)
            changes: list[DisclosureChange] = await self._classify_in_batches(
                comparison_id=comparison.id,
                analysis_run_id=analysis_run_id,
                candidates=candidates,
                known_results=known_results,
                prior_failures=prior_failures,
                stats=stats,
            )
            # Re-fetch once more: the batch loop's close() calls above
            # detached `comparison` again.
            comparison = await self._require_comparison(comparison.id)
            metrics = {
                "sections_matched": len(
                    [
                        match
                        for match in stored_section_matches
                        if match.match_type
                        not in {"unmatched_current", "unmatched_previous"}
                    ]
                ),
                "unmatched_sections": len(
                    [
                        match
                        for match in stored_section_matches
                        if match.match_type.startswith("unmatched")
                    ]
                ),
                "passage_matches": len(all_passage_matches),
                "matching_fingerprint": fingerprint,
                "matching_section_match_count": len(stored_section_matches),
                "matching_passage_match_count": len(all_passage_matches),
                # True when the persisted BGE matching/alignment was reused
                # instead of recomputed (inputs, models and config unchanged).
                "matching_reused": matching_reused,
                "matching_seconds": matching_seconds,
                "findings_generated": len(changes),
                # Actual Gemini requests made, not just candidate passage
                # pairs -- see candidate_pairs/deterministic_skips/
                # cache_reuses below for why these can differ substantially.
                "model_calls": stats.gemini_calls,
                "classification_candidate_pairs": stats.candidate_pairs,
                "classification_deterministic_skips": stats.deterministic_skips,
                "classification_cache_reuses": stats.cache_reuses,
                "classification_gemini_calls": stats.gemini_calls,
                "classification_repair_fallbacks": stats.repair_fallbacks,
                "classification_batches_total": stats.batches_total,
                "classification_batches_skipped": stats.batches_skipped,
                "classification_batches_executed": stats.batches_executed,
                "classification_batch_calls": stats.batch_calls,
                "classification_batched_items": stats.batched_items,
                "classification_item_retries": stats.item_retries,
                "classification_completed_batch_repairs": stats.completed_batch_repairs,
                # Provider-reported usage; None when the provider reported none.
                "classification_actual_input_tokens": stats.actual_input_tokens,
                "classification_actual_output_tokens": stats.actual_output_tokens,
                "classification_actual_total_tokens": stats.actual_total_tokens,
            }
            comparison.matching_model_name = self.matcher.embeddings.model_name
            comparison.matching_model_version = self.matcher.embeddings.model_version
            comparison.change_model_name = self.change_detector.classifier.model_name
            comparison.change_model_version = self.change_detector.classifier.model_version
            await self.comparisons.set_status(comparison, "completed", metrics=metrics)
            await self.session.commit()
        except Exception as exc:
            try:
                await self.session.rollback()
            except Exception:
                # self.session's connection is dead (e.g. it went idle across
                # a long provider retry/backoff and Neon dropped it). It must
                # not be reused from here - that would just raise the same
                # InterfaceError again - so fall back to a brand new
                # session/connection to record the failure. Best-effort only:
                # the original exception below matters more than this
                # bookkeeping, so a failure here is swallowed too.
                try:
                    async with self._session_factory() as recovery_session:
                        recovery_comparisons = self._comparisons_factory(recovery_session)
                        recovered = await recovery_comparisons.get_comparison(comparison_id)
                        if recovered is not None:
                            await recovery_comparisons.set_status(
                                recovered,
                                "failed",
                                error_code=exc.__class__.__name__,
                                error_message=str(exc),
                            )
                            await recovery_session.commit()
                except Exception:
                    pass
            else:
                comparison = await self.comparisons.get_comparison(comparison_id)
                if comparison is not None:
                    await self.comparisons.set_status(
                        comparison,
                        "failed",
                        error_code=exc.__class__.__name__,
                        error_message=str(exc),
                    )
                    await self.session.commit()
            raise

    async def _load_reusable_matching(
        self,
        comparison_id: uuid.UUID,
        fingerprint: str,
    ):
        """Persisted (section matches, passage matches) if they are complete
        for exactly `fingerprint`, else None (recompute).

        Trusts nothing but a matching fingerprint recorded together with the
        counts of what was persisted, and re-verifies those counts against the
        database, so a partially written or wiped set is never reused.
        """
        comparison = await self._require_comparison(comparison_id)
        state = getattr(comparison, "processing_metrics", None) or {}
        if state.get("matching_fingerprint") != fingerprint:
            await self.session.commit()
            await self.session.close()
            return None
        section_matches = await self.comparisons.list_section_matches(comparison_id)
        passage_matches = await self.comparisons.list_passage_matches(comparison_id)
        await self.session.commit()
        await self.session.close()
        if len(section_matches) != state.get("matching_section_match_count") or len(
            passage_matches
        ) != state.get("matching_passage_match_count"):
            logger.warning(
                "comparison %s: persisted matching does not match its recorded counts; "
                "recomputing",
                comparison_id,
            )
            return None
        return section_matches, passage_matches

    async def _recompute_matching(
        self,
        comparison: FilingComparison,
        fingerprint: str,
        current_sections: list[FilingSection],
        previous_sections: list[FilingSection],
    ):
        """BGE section matching + passage alignment, persisted incrementally.

        The old "complete" marker is cleared in the same transaction that wipes
        the old matches, and the new one is written only after every section
        is aligned - so the marker is present exactly when the matches are
        complete.
        """
        section_matches = await self.matcher.match_sections(
            comparison_id=comparison.id,
            current_sections=current_sections,
            previous_sections=previous_sections,
        )
        comparison = await self._require_comparison(comparison.id)
        await self.comparisons.set_matching_state(comparison, fingerprint=None)
        stored_section_matches = await self.comparisons.replace_section_matches(
            comparison.id, section_matches
        )
        # Commit here so the section-matching result is durable and the
        # transaction/connection isn't held open across the much longer
        # passage-alignment and Gemini classification stages below.
        await self.session.commit()

        # `comparison` was detached by the close() above; re-fetch it
        # (the session reconnected transparently on the writes just
        # above) before mutating it again, so this status update is
        # tracked by the session and actually persisted rather than
        # silently discarded on a stale detached object.
        comparison = await self._require_comparison(comparison.id)
        await self.comparisons.set_status(comparison, "aligning_passages")
        await self.session.commit()
        all_passage_matches = []
        for section_match in stored_section_matches:
            current_passages = await self._passages(section_match.current_section_id)
            previous_passages = await self._passages(section_match.previous_section_id)
            # Commit and close the connection that loaded this section's
            # passages before running BGE alignment on them below - same
            # reasoning as the section-matching stage above.
            await self.session.commit()
            await self.session.close()
            matches = await self.aligner.align_passages(
                section_match_id=section_match.id,
                current_passages=current_passages,
                previous_passages=previous_passages,
            )
            all_passage_matches.extend(
                await self.comparisons.replace_passage_matches(section_match.id, matches)
            )
            # Commit per section match: incremental persistence, and no
            # transaction spans the next section's BGE alignment.
            await self.session.commit()
        comparison = await self._require_comparison(comparison.id)
        await self.comparisons.set_matching_state(
            comparison,
            fingerprint=fingerprint,
            section_match_count=len(stored_section_matches),
            passage_match_count=len(all_passage_matches),
        )
        await self.session.commit()
        return stored_section_matches, all_passage_matches

    async def _classify_in_batches(
        self,
        *,
        comparison_id: uuid.UUID,
        analysis_run_id: uuid.UUID | None,
        candidates: list[ClassificationCandidate],
        known_results,
        prior_failures: FrozenFailures,
        stats: DisclosureChangeCallStats,
    ) -> list[DisclosureChange]:
        """Classify `candidates` as durable, token-bounded batches.

        Deterministic pairs are resolved and stored first (no provider work,
        nothing to resume). The pairs that need the model are planned into
        batches from their estimated token cost, and each batch is stored
        and marked complete in one transaction - so on a retry, batches
        already completed are found in the ledger and never sent to the
        provider again (their results come from the reuse cache seeded
        before the comparison re-run wipes its rows).
        """
        stored: list[DisclosureChange] = []
        detector = self.change_detector

        local = [candidate for candidate in candidates if not candidate.needs_model]
        if local:
            outcome = await detector.classify_candidates(
                local, known_results=known_results, stats=stats
            )
            for candidate, change in outcome.changes:
                stored.append(
                    await self.comparisons.upsert_change_for_passage_match(
                        candidate.passage_match.id, change
                    )
                )
            await self.session.commit()
            await self.session.close()

        model_candidates = [candidate for candidate in candidates if candidate.needs_model]
        seen: set[str] = set()
        for candidate in model_candidates:
            # Identity is built from the passage pair; it should already be
            # unique, but a repeated pair must not silently collapse into one
            # batch item.
            if candidate.identity in seen:
                candidate.identity = f"{candidate.identity}#{candidate.passage_match.id}"
                candidate.request_id = item_request_id(candidate.identity)
            seen.add(candidate.identity)
        by_identity = {candidate.identity: candidate for candidate in model_candidates}

        plan = plan_batches(
            [BatchItem(c.identity, c.estimated_tokens) for c in model_candidates],
            BatchingConfig.from_settings(self.settings),
            fixed_overhead_tokens=(
                detector.batch_fixed_overhead_tokens if detector.supports_multi_item_requests else 0
            ),
        )
        stats.batches_total = len(plan)
        states: list[StageBatchState | None]
        if analysis_run_id is not None and plan:
            states = list(
                await self.batches.sync_plan(
                    analysis_run_id,
                    BATCH_STAGE_DISCLOSURE_COMPARISON,
                    plan,
                    model_name=detector.classifier.model_name,
                    prompt_version=detector.batch_prompt_version,
                    context_hash=detector.batch_context_hash,
                )
            )
        else:
            states = [None] * len(plan)
        await self.session.commit()
        await self.session.close()

        for planned, state in zip(plan, states, strict=True):
            group = [by_identity[identity] for identity in planned.identities]
            already_completed = state is not None and state.status == "completed"
            calls_before = stats.gemini_calls
            if already_completed:
                log_batch_event(
                    logger,
                    stage_label=_STAGE_LABEL,
                    index=planned.index,
                    total=planned.total,
                    event="skipped (already completed; results restored without provider calls)",
                    scope=f"comparison {comparison_id}",
                )
            else:
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
                    estimated_input_tokens=planned.estimated_input_tokens,
                    oversized_single_item=True if planned.oversized else None,
                )
            if state is not None and not already_completed:
                await self.batches.mark_processing(state.id)
                await self.session.commit()
                await self.session.close()
            frozen_failures = None
            missing_records = False
            if state is not None:
                # The batch's own durable records first: they hold its results
                # even if the disclosure_changes rows were wiped since (a
                # comparison re-run cascades them away).
                overlay_results, overlay_failures = detector.overlay_from_records(
                    group, state.item_results, include_failures=already_completed
                )
                if known_results is not None:
                    known_results.update(overlay_results)
                missing_records = already_completed and any(
                    candidate.identity not in state.item_results for candidate in group
                )
                if already_completed:
                    # A completed batch is final, including its items the
                    # model could not classify; a batch being (re)tried gets
                    # another chance at those.
                    frozen_failures = {**prior_failures, **overlay_failures}
            outcome = None
            usage = None
            try:
                with collect_usage() as usage:
                    outcome = await detector.classify_candidates(
                        group,
                        known_results=known_results,
                        stats=stats,
                        frozen_failures=frozen_failures,
                    )
                # Store whatever resolved - even on a provider failure the
                # items that succeeded are kept and reused by the retry.
                for candidate, change in outcome.changes:
                    stored.append(
                        await self.comparisons.upsert_change_for_passage_match(
                            candidate.passage_match.id, change
                        )
                    )
                if outcome.error is not None:
                    await self.session.commit()
                    raise outcome.error
                provider_calls = stats.gemini_calls - calls_before
                if state is not None and (not already_completed or missing_records):
                    # One transaction: the changes above, the batch's durable
                    # item records and its `completed` mark commit together.
                    await self.batches.mark_completed(
                        state.id,
                        provider_calls=provider_calls,
                        item_results=outcome.records,
                        usage=usage,
                    )
                if missing_records:
                    stats.completed_batch_repairs += 1
                stats.add_usage(usage)
                if not already_completed:
                    log_batch_event(
                        logger,
                        stage_label=_STAGE_LABEL,
                        index=planned.index,
                        total=planned.total,
                        event="completed",
                        scope=f"comparison {comparison_id}",
                        provider_calls=provider_calls,
                        actual_input_tokens=usage.input_tokens if usage else None,
                        actual_output_tokens=usage.output_tokens if usage else None,
                        actual_total_tokens=usage.resolved_total() if usage else None,
                        items_needing_review=(
                            sum(
                                1
                                for r in outcome.records.values()
                                if r.get("status") == "requires_review"
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
                    state,
                    exc,
                    stats.gemini_calls - calls_before,
                    records=outcome.records if outcome is not None else None,
                    usage=usage,
                )
                raise
            if already_completed and stats.gemini_calls == calls_before:
                stats.batches_skipped += 1
            else:
                stats.batches_executed += 1
        return stored

    async def _record_batch_failure(
        self,
        state: StageBatchState | None,
        exc: Exception,
        provider_calls: int,
        *,
        records: dict[str, dict[str, object]] | None = None,
        usage: UsageTotals | None = None,
    ) -> None:
        """Record why a batch stopped, on its own connection: `self.session`
        may be mid-transaction or dead. Best-effort - the original error is
        what matters and is re-raised by the caller regardless."""
        if state is None:
            return
        try:
            # Release any row locks this session still holds (e.g. an
            # uncommitted batch update) so the write below on a separate
            # connection cannot block on them.
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

    async def _require_comparison(self, comparison_id: uuid.UUID) -> FilingComparison:
        comparison = await self.comparisons.get_comparison(comparison_id)
        if comparison is None:
            raise FilingComparisonError(
                "comparison_not_found", "Comparison disappeared during processing."
            )
        return comparison

    async def _segment_sections(self, sections: list[FilingSection]) -> None:
        for section in sections:
            units = self.segmenter.segment_section(section)
            await self.comparisons.get_or_create_passages(
                section.id,
                units,
                segmentation_version=self.settings.passage_segmentation_version,
            )
        await self.session.flush()

    async def _passages(self, section_id: uuid.UUID | None):
        if section_id is None:
            return []
        return await self.comparisons.list_passages_for_section(
            section_id,
            segmentation_version=self.settings.passage_segmentation_version,
        )

    async def _has_parsed_content(self, filing_id: uuid.UUID) -> bool:
        section_count = await self.session.scalar(
            select(func.count())
            .select_from(FilingSection)
            .where(FilingSection.filing_id == filing_id)
        )
        chunk_count = await self.session.scalar(
            select(func.count())
            .select_from(FilingChunk)
            .join(FilingSection)
            .where(FilingSection.filing_id == filing_id)
        )
        return bool(section_count and chunk_count)


_UNORDERED = 10**9


def _order_of(obj: object, attribute: str) -> int:
    value = getattr(obj, attribute, None) if obj is not None else None
    return value if isinstance(value, int) else _UNORDERED


def _candidate_order_key(candidate: ClassificationCandidate) -> tuple:
    """Document order (section, then passage position), with the content-based
    identity as the final tiebreak, so the order never depends on database
    row order."""
    return (
        _order_of(candidate.current_section, "section_order"),
        _order_of(candidate.previous_section, "section_order"),
        _order_of(candidate.current_passage, "unit_index"),
        _order_of(candidate.previous_passage, "unit_index"),
        candidate.identity,
    )


def _period(filing: Filing) -> date:
    return filing.report_period or filing.filing_date
