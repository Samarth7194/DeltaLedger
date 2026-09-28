from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.ai.batching import (
    OUTCOME_REQUIRES_REVIEW,
    OUTCOME_SUCCESS,
    canonical_hash,
    item_request_id,
)
from app.ai.inference import UsageTotals
from app.ai.openai_compatible import StructuredOutputError
from app.ai.semantic_change import (
    ChangeClassificationRequest,
    ChangeClassificationResult,
    ChangeClassifierProvider,
    change_request_tokens,
)
from app.core.config import Settings
from app.db.models import DisclosureChange, FilingSection, PassageMatch, PassageUnit, SectionMatch
from app.services.comparison_utils import clamp, deterministic_signals, lexical_similarity

# A passage the classifier could not produce usable structured output for
# after exhausting its repair attempts. Distinct from every real
# ChangeType so it can never be confused with an actual classification;
# the DB column is a plain (unconstrained) string, so this needs no
# schema migration.
UNCLASSIFIABLE_CHANGE_TYPE = "requires_review"
MODEL_OUTPUT_FAILED_DETECTION_METHOD = "model_output_failed"
DETERMINISTIC_DETECTION_METHOD = "deterministic"
CACHED_DETECTION_METHOD = "hybrid_cached"

ALLOWED_CHANGE_LABELS = ["added", "removed", "strengthened", "weakened", "no_material_change"]

# Keyed by (previous_text, current_text); maps a passage-text pair to a
# previously obtained classification so it never needs a second Gemini
# call, whether the duplicate came from earlier in the same run (repeated
# boilerplate) or from a prior attempt of the same comparison (resume).
ResultCache = dict[tuple[str | None, str | None], ChangeClassificationResult]
# Keyed the same way; maps a passage-text pair to the stored output of a
# prior *failed* classification (a requires_review placeholder).
FrozenFailures = dict[tuple[str | None, str | None], dict[str, object]]

logger = logging.getLogger(__name__)


def _add_optional(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return value if current is None else current + value


class DisclosureChangeCallStats:
    """Visibility into why a comparison made as many/few Gemini calls as it
    did -- surfaced in FilingComparisonService's persisted metrics."""

    def __init__(self) -> None:
        self.candidate_pairs = 0
        self.deterministic_skips = 0
        self.cache_reuses = 0
        # Provider requests actually sent (a multi-item request counts once).
        self.gemini_calls = 0
        self.repair_fallbacks = 0
        # Multi-item requests sent, items answered by them, and items that
        # then needed their own individual request.
        self.batch_calls = 0
        self.batched_items = 0
        self.item_retries = 0
        # Durable batches: how many were skipped as already completed, and
        # how many were actually executed in this attempt.
        self.batches_total = 0
        self.batches_skipped = 0
        self.batches_executed = 0
        # Completed batches whose durable item records were missing and had to
        # be rebuilt (should stay 0; non-zero flags a data-integrity repair).
        self.completed_batch_repairs = 0
        # Provider-reported token usage across all batches; None = unreported.
        self.actual_input_tokens: int | None = None
        self.actual_output_tokens: int | None = None
        self.actual_total_tokens: int | None = None

    def add_usage(self, usage: UsageTotals | None) -> None:
        if usage is None:
            return
        self.actual_input_tokens = _add_optional(self.actual_input_tokens, usage.input_tokens)
        self.actual_output_tokens = _add_optional(self.actual_output_tokens, usage.output_tokens)
        self.actual_total_tokens = _add_optional(self.actual_total_tokens, usage.resolved_total())


@dataclass
class ClassificationCandidate:
    """Everything needed to classify one passage pair, prepared without any
    provider call. `identity` is stable across runs (it is built from the
    persisted passage ids, not from per-run match ids), so it is what batch
    identity and resume are keyed on."""

    identity: str
    request_id: str
    # Hash of the canonical input content (texts, signals, section metadata).
    # Already part of `identity`; kept for callers that need it on its own.
    content_hash: str
    comparison_id: object
    section_match: SectionMatch
    passage_match: PassageMatch
    current_passage: PassageUnit | None
    previous_passage: PassageUnit | None
    current_section: FilingSection | None
    previous_section: FilingSection | None
    previous_text: str | None
    current_text: str | None
    signals: dict[str, object]
    evidence: dict[str, object]
    # None when the pair is resolved locally (no model call needed).
    request: ChangeClassificationRequest | None
    estimated_tokens: int = 0

    @property
    def needs_model(self) -> bool:
        return self.request is not None

    @property
    def cache_key(self) -> tuple[str | None, str | None]:
        return (self.previous_text, self.current_text)


@dataclass
class ClassificationOutcome:
    """Result of classifying a group of candidates.

    `changes` holds every candidate that was resolved, in input order, even
    when `error` is set: a provider failure part-way through must not throw
    away the items that already succeeded. `error` is the failure that
    stopped the rest (None when everything resolved).
    """

    changes: list[tuple[ClassificationCandidate, DisclosureChange]] = field(default_factory=list)
    error: Exception | None = None
    # Durable per-item outcome records for the candidates that needed the
    # model, keyed by candidate identity (which embeds the content hash). They
    # are stored with the batch so its results survive independently of the
    # disclosure_changes rows.
    records: dict[str, dict[str, object]] = field(default_factory=dict)


class DisclosureChangeService:
    def __init__(
        self,
        settings: Settings,
        classifier: ChangeClassifierProvider,
    ) -> None:
        self.settings = settings
        self.classifier = classifier

    @property
    def supports_multi_item_requests(self) -> bool:
        return self.settings.ai_batch_multi_item_requests and hasattr(
            self.classifier, "classify_batch"
        )

    @property
    def batch_prompt_version(self) -> str:
        """Prompt version that identifies a batch's results: the multi-item
        prompt when multi-item requests are in use, else the per-item one."""
        if self.supports_multi_item_requests:
            return str(self.classifier.batch_prompt_version)
        return self.classifier.prompt_version

    @property
    def reusable_prompt_versions(self) -> tuple[str, ...]:
        """Prompt versions whose stored results may be reused as-is (per-item
        and multi-item prompts classify the same schema)."""
        versions = [self.classifier.prompt_version]
        batch_version = getattr(self.classifier, "batch_prompt_version", None)
        if batch_version and batch_version not in versions:
            versions.append(batch_version)
        return tuple(versions)

    @property
    def batch_context_hash(self) -> str:
        """Fingerprint of request content shared by every item: the allowed
        labels, the response schema, and (when the classifier provides it) the
        actual system-prompt text. A change to any of them invalidates
        completed batches even if nobody bumped a version string."""
        return canonical_hash(
            {
                "allowed_labels": ALLOWED_CHANGE_LABELS,
                "result_schema": ChangeClassificationResult.model_json_schema(),
                "prompt_fingerprint": getattr(self.classifier, "prompt_fingerprint", ""),
            }
        )

    @property
    def batch_fixed_overhead_tokens(self) -> int:
        return int(getattr(self.classifier, "batch_fixed_overhead_tokens", 0))

    def prepare_candidate(
        self,
        *,
        comparison_id,
        section_match: SectionMatch,
        passage_match: PassageMatch,
        current_passage: PassageUnit | None,
        previous_passage: PassageUnit | None,
        current_section: FilingSection | None,
        previous_section: FilingSection | None,
        stats: DisclosureChangeCallStats | None = None,
    ) -> ClassificationCandidate:
        previous_text = previous_passage.text if previous_passage else None
        current_text = current_passage.text if current_passage else None
        signals = deterministic_signals(previous_text, current_text)
        evidence = evidence_payload(
            current_passage=current_passage,
            previous_passage=previous_passage,
            current_section=current_section,
            previous_section=previous_section,
        )
        if stats is not None:
            stats.candidate_pairs += 1
        section_metadata = _section_metadata(current_section, previous_section)
        content_hash = canonical_hash(
            {
                "previous": previous_text,
                "current": current_text,
                "signals": signals,
                "section": section_metadata,
            }
        )
        # Ids alone are not enough: the same passage ids can carry different
        # text (re-ingest/re-segmentation), and a batch completed for the old
        # text must not be reused. The content hash makes identity
        # content-sensitive without storing any text.
        identity = (
            f"{previous_passage.id if previous_passage else '-'}"
            f"|{current_passage.id if current_passage else '-'}"
            f"|{content_hash}"
        )
        # Deterministic pre-filter: passages that are identical after
        # normalization (whitespace/case/year-token noise) cannot possibly
        # carry a semantic change worth an LLM call -- classify them
        # locally instead. Only applies to genuinely matched pairs (not
        # added/removed, where one side is None).
        deterministic = (
            previous_text is not None
            and current_text is not None
            and bool(signals.get("normalized_equal"))
        )
        request = None
        estimated_tokens = 0
        if deterministic:
            if stats is not None:
                stats.deterministic_skips += 1
            logger.info(
                "deterministic skip: section_match=%s passage_match=%s "
                "(text unchanged, no model call)",
                section_match.id,
                passage_match.id,
            )
        else:
            request = ChangeClassificationRequest(
                previous_text=previous_text,
                current_text=current_text,
                deterministic_signals=signals,
                section_metadata=section_metadata,
                allowed_labels=list(ALLOWED_CHANGE_LABELS),
            )
            estimated_tokens = change_request_tokens(request)
        return ClassificationCandidate(
            identity=identity,
            request_id=item_request_id(identity),
            content_hash=content_hash,
            comparison_id=comparison_id,
            section_match=section_match,
            passage_match=passage_match,
            current_passage=current_passage,
            previous_passage=previous_passage,
            current_section=current_section,
            previous_section=previous_section,
            previous_text=previous_text,
            current_text=current_text,
            signals=signals,
            evidence=evidence,
            request=request,
            estimated_tokens=estimated_tokens,
        )

    async def detect_change(
        self,
        *,
        comparison_id,
        section_match: SectionMatch,
        passage_match: PassageMatch,
        current_passage: PassageUnit | None,
        previous_passage: PassageUnit | None,
        current_section: FilingSection | None,
        previous_section: FilingSection | None,
        known_results: ResultCache | None = None,
        stats: DisclosureChangeCallStats | None = None,
    ) -> DisclosureChange | None:
        candidate = self.prepare_candidate(
            comparison_id=comparison_id,
            section_match=section_match,
            passage_match=passage_match,
            current_passage=current_passage,
            previous_passage=previous_passage,
            current_section=current_section,
            previous_section=previous_section,
            stats=stats,
        )
        outcome = await self.classify_candidates(
            [candidate], known_results=known_results, stats=stats
        )
        if outcome.error is not None:
            raise outcome.error
        return outcome.changes[0][1] if outcome.changes else None

    async def classify_candidates(
        self,
        candidates: Sequence[ClassificationCandidate],
        *,
        known_results: ResultCache | None = None,
        stats: DisclosureChangeCallStats | None = None,
        frozen_failures: FrozenFailures | None = None,
    ) -> ClassificationOutcome:
        """Resolve every candidate: deterministic locally, then from the reuse
        cache, and only the rest through the provider - as one multi-item
        request when the classifier supports it (and more than one item is
        left), otherwise one request per item.

        `frozen_failures` are prior requires_review outcomes to carry over
        as-is instead of asking the provider again; pass it only for work
        that must not be redone (a batch already marked completed).

        Each item is validated and, if unusable, retried on its own; an item
        that stays unusable becomes a `requires_review` placeholder without
        touching its neighbours. A provider-level failure stops the remaining
        provider work but keeps everything already resolved (see
        ClassificationOutcome).
        """
        resolved: dict[str, DisclosureChange] = {}
        records: dict[str, dict[str, object]] = {}
        pending: list[ClassificationCandidate] = []
        for candidate in candidates:
            if not candidate.needs_model:
                resolved[candidate.identity] = self._deterministic_no_change(
                    comparison_id=candidate.comparison_id,
                    section_match=candidate.section_match,
                    passage_match=candidate.passage_match,
                    previous_text=candidate.previous_text,
                    current_text=candidate.current_text,
                    evidence=candidate.evidence,
                    signals=candidate.signals,
                    current_section=candidate.current_section,
                    previous_section=candidate.previous_section,
                )
                continue
            cached = known_results.get(candidate.cache_key) if known_results is not None else None
            if cached is not None:
                if stats is not None:
                    stats.cache_reuses += 1
                logger.info(
                    "cache reuse: section_match=%s passage_match=%s "
                    "(previously classified this run/attempt)",
                    candidate.section_match.id,
                    candidate.passage_match.id,
                )
                resolved[candidate.identity] = self._build_change(
                    candidate, cached, CACHED_DETECTION_METHOD, self.classifier.prompt_version
                )
                records[candidate.identity] = _success_record(cached)
            elif frozen_failures is not None and candidate.cache_key in frozen_failures:
                if stats is not None:
                    stats.cache_reuses += 1
                resolved[candidate.identity] = self._structured_output_failed(
                    comparison_id=candidate.comparison_id,
                    section_match=candidate.section_match,
                    passage_match=candidate.passage_match,
                    previous_text=candidate.previous_text,
                    current_text=candidate.current_text,
                    evidence=candidate.evidence,
                    error_name=str(frozen_failures[candidate.cache_key].get("error", "")),
                    error_message=str(frozen_failures[candidate.cache_key].get("message", "")),
                )
                records[candidate.identity] = _review_record(
                    str(frozen_failures[candidate.cache_key].get("error", "")),
                    str(frozen_failures[candidate.cache_key].get("message", "")),
                )
            else:
                pending.append(candidate)

        error = await self._classify_pending(pending, resolved, records, known_results, stats)
        return ClassificationOutcome(
            changes=[(c, resolved[c.identity]) for c in candidates if c.identity in resolved],
            error=error,
            records={
                c.identity: records[c.identity]
                for c in candidates
                if c.needs_model and c.identity in records
            },
        )

    def overlay_from_records(
        self,
        candidates: Sequence[ClassificationCandidate],
        item_results: Mapping[str, object],
        *,
        include_failures: bool,
    ) -> tuple[ResultCache, FrozenFailures]:
        """Rebuild reusable results from a batch's own durable item records.

        Records are looked up by candidate identity, which embeds the content
        hash, so a record written for different content simply never matches.
        `include_failures` carries `requires_review` outcomes over as final
        (only right for a batch already marked completed).
        """
        results: ResultCache = {}
        failures: FrozenFailures = {}
        for candidate in candidates:
            record = item_results.get(candidate.identity)
            if not isinstance(record, dict):
                continue
            if record.get("status") == OUTCOME_SUCCESS:
                try:
                    results[candidate.cache_key] = ChangeClassificationResult.model_validate(
                        record.get("result")
                    )
                except Exception:
                    continue  # unreadable record: treat as absent, reclassify
            elif include_failures and record.get("status") == OUTCOME_REQUIRES_REVIEW:
                failures[candidate.cache_key] = {
                    "error": record.get("error", ""),
                    "message": record.get("message", ""),
                }
        return results, failures

    async def _classify_pending(
        self,
        pending: list[ClassificationCandidate],
        resolved: dict[str, DisclosureChange],
        records: dict[str, dict[str, object]],
        known_results: ResultCache | None,
        stats: DisclosureChangeCallStats | None,
    ) -> Exception | None:
        if not pending:
            return None
        # Identical text pairs (repeated boilerplate) only need one request.
        representatives: dict[tuple[str | None, str | None], ClassificationCandidate] = {}
        for candidate in pending:
            representatives.setdefault(candidate.cache_key, candidate)
        unique = list(representatives.values())
        results: dict[tuple[str | None, str | None], ChangeClassificationResult] = {}
        failures: dict[tuple[str | None, str | None], StructuredOutputError] = {}
        prompt_versions: dict[tuple[str | None, str | None], str] = {}
        error: Exception | None = None

        remaining = unique
        if len(unique) > 1 and self.supports_multi_item_requests:
            logger.info("Gemini batch call: %d items", len(unique))
            if stats is not None:
                stats.gemini_calls += 1
                stats.batch_calls += 1
            try:
                outcomes = await self.classifier.classify_batch(  # type: ignore[attr-defined]
                    [(c.request_id, c.request) for c in unique]
                )
            except Exception as exc:
                outcomes = {}
                error = exc
            if error is None:
                for candidate in unique:
                    result = outcomes.get(candidate.request_id)
                    if result is not None:
                        results[candidate.cache_key] = result
                        prompt_versions[candidate.cache_key] = self.batch_prompt_version
                        if stats is not None:
                            stats.batched_items += 1
                remaining = [c for c in unique if c.cache_key not in results]
                if stats is not None:
                    stats.item_retries += len(remaining)
            else:
                remaining = []

        for candidate in remaining:
            try:
                logger.info(
                    "Gemini call: section_match=%s passage_match=%s",
                    candidate.section_match.id,
                    candidate.passage_match.id,
                )
                result = await self.classifier.classify(candidate.request)
                if stats is not None:
                    stats.gemini_calls += 1
                results[candidate.cache_key] = result
                prompt_versions[candidate.cache_key] = self.classifier.prompt_version
            except StructuredOutputError as exc:
                if stats is not None:
                    stats.gemini_calls += 1
                    stats.repair_fallbacks += 1
                failures[candidate.cache_key] = exc
            except Exception as exc:
                error = exc
                break

        for key, result in results.items():
            if known_results is not None:
                known_results[key] = result
        for candidate in pending:
            key = candidate.cache_key
            is_duplicate = representatives[key] is not candidate
            if key in results:
                if is_duplicate and stats is not None:
                    stats.cache_reuses += 1
                resolved[candidate.identity] = self._build_change(
                    candidate,
                    results[key],
                    CACHED_DETECTION_METHOD if is_duplicate else "hybrid",
                    prompt_versions[key],
                )
                records[candidate.identity] = _success_record(results[key])
            elif key in failures:
                resolved[candidate.identity] = self._structured_output_failed(
                    comparison_id=candidate.comparison_id,
                    section_match=candidate.section_match,
                    passage_match=candidate.passage_match,
                    previous_text=candidate.previous_text,
                    current_text=candidate.current_text,
                    evidence=candidate.evidence,
                    error_name=failures[key].__class__.__name__,
                    error_message=str(failures[key]),
                )
                records[candidate.identity] = _review_record(
                    failures[key].__class__.__name__, str(failures[key])
                )
        return error

    def _build_change(
        self,
        candidate: ClassificationCandidate,
        result: ChangeClassificationResult,
        detection_method: str,
        prompt_version: str,
    ) -> DisclosureChange:
        components = build_materiality_components(
            self.settings,
            result.change_type,
            result.risk_category,
            candidate.signals,
            candidate.current_section or candidate.previous_section,
            candidate.previous_text,
            candidate.current_text,
            result.confidence,
        )
        validate_evidence(result.change_type, candidate.evidence)
        return DisclosureChange(
            comparison_id=candidate.comparison_id,
            section_match_id=candidate.section_match.id,
            passage_match_id=candidate.passage_match.id,
            change_type=result.change_type,
            risk_category=result.risk_category,
            previous_text=candidate.previous_text,
            current_text=candidate.current_text,
            changed_spans=result.changed_spans,
            change_summary=result.summary,
            change_explanation=result.explanation,
            materiality_score=float(components["materiality_score"]),
            confidence=result.confidence,
            detection_method=detection_method,
            supporting_evidence=candidate.evidence,
            materiality_components=components,
            original_model_output=result.model_dump(),
            model_name=self.classifier.model_name,
            model_version=self.classifier.model_version,
            prompt_version=prompt_version,
        )

    def _structured_output_failed(
        self,
        *,
        comparison_id,
        section_match: SectionMatch,
        passage_match: PassageMatch,
        previous_text: str | None,
        current_text: str | None,
        evidence: dict[str, object],
        error_name: str,
        error_message: str,
    ) -> DisclosureChange:
        # The provider returned HTTP 200 but never produced a schema-valid
        # response even after the bounded repair attempt inside
        # chat_json(). This one passage cannot be classified -- that must
        # not fail the rest of the comparison. Record a clearly-marked,
        # analyst-reviewable placeholder instead of fabricating a
        # change_type/risk_category/materiality judgment the model never
        # actually gave us.
        return DisclosureChange(
            comparison_id=comparison_id,
            section_match_id=section_match.id,
            passage_match_id=passage_match.id,
            change_type=UNCLASSIFIABLE_CHANGE_TYPE,
            risk_category="other",
            previous_text=previous_text,
            current_text=current_text,
            changed_spans=[],
            change_summary="Automated classification failed; requires analyst review.",
            change_explanation=(
                "The AI classifier did not return usable structured output for "
                "this passage after exhausting its repair attempts, so no "
                "automated change type, risk category, or materiality judgment "
                f"could be made. Provider error: {error_message}"
            ),
            materiality_score=1.0,
            confidence=0.0,
            detection_method=MODEL_OUTPUT_FAILED_DETECTION_METHOD,
            supporting_evidence=evidence,
            materiality_components={
                "fallback": True,
                "reason": "structured_output_failed",
            },
            original_model_output={
                "error": error_name,
                "message": error_message,
            },
            model_name=self.classifier.model_name,
            model_version=self.classifier.model_version,
            prompt_version=self.classifier.prompt_version,
            review_status="uncertain",
        )

    def _deterministic_no_change(
        self,
        *,
        comparison_id,
        section_match: SectionMatch,
        passage_match: PassageMatch,
        previous_text: str,
        current_text: str,
        evidence: dict[str, object],
        signals: dict[str, object],
        current_section: FilingSection | None,
        previous_section: FilingSection | None,
    ) -> DisclosureChange:
        # Text is identical after normalization (case/whitespace/year-token
        # noise only) -- there is no semantic change to classify, so no
        # provider call is warranted. exact_equal vs. normalized-only-equal
        # is noted for transparency but doesn't change the outcome.
        validate_evidence("no_material_change", evidence)
        components = build_materiality_components(
            self.settings,
            "no_material_change",
            "other",
            signals,
            current_section or previous_section,
            previous_text,
            current_text,
            1.0,
        )
        return DisclosureChange(
            comparison_id=comparison_id,
            section_match_id=section_match.id,
            passage_match_id=passage_match.id,
            change_type="no_material_change",
            risk_category="other",
            previous_text=previous_text,
            current_text=current_text,
            changed_spans=[],
            change_summary="No material change: passage text is unchanged.",
            change_explanation=(
                "Determined locally without a model call: the current and "
                "previous passage text are identical"
                + (" after normalization" if not signals.get("exact_equal") else "")
                + "."
            ),
            materiality_score=float(components["materiality_score"]),
            confidence=1.0,
            detection_method=DETERMINISTIC_DETECTION_METHOD,
            supporting_evidence=evidence,
            materiality_components=components,
            original_model_output={},
            model_name=self.classifier.model_name,
            model_version=self.classifier.model_version,
            prompt_version=self.classifier.prompt_version,
        )


def _success_record(result: ChangeClassificationResult) -> dict[str, object]:
    return {
        "status": OUTCOME_SUCCESS,
        # inference_metadata (token counts, response ids) is bookkeeping, not
        # part of the reusable result.
        "result": result.model_dump(exclude={"inference_metadata"}),
    }


def _review_record(error_name: str, message: str) -> dict[str, object]:
    return {
        "status": OUTCOME_REQUIRES_REVIEW,
        "error": error_name,
        "message": message[:500],
    }


def build_materiality_components(
    settings: Settings,
    change_type: str,
    risk_category: str,
    signals: dict[str, object],
    section: FilingSection | None,
    previous_text: str | None,
    current_text: str | None,
    confidence: float,
) -> dict[str, float]:
    novelty = (
        1.0
        if change_type in {"added", "removed"}
        else 1.0 - lexical_similarity(previous_text or "", current_text or "")
    )
    risk_weight = {
        "liquidity": 0.85,
        "revenue_guidance": 0.75,
        "litigation": 0.8,
        "other": 0.35,
    }[risk_category]
    uncertainty = (
        1.0
        if any(
            signals.get(key)
            for key in ("uncertainty_added", "conditional_added", "negation_added")
        )
        else 0.25
    )
    section_importance = (
        0.85
        if section and section.canonical_section_type in {"mda", "risk_factors"}
        else 0.5
    )
    numeric = 1.0 if signals.get("numeric_changed") else 0.0
    score = clamp(
        settings.materiality_weight_novelty * novelty
        + settings.materiality_weight_risk * risk_weight
        + settings.materiality_weight_uncertainty * uncertainty
        + settings.materiality_weight_section * section_importance
        + settings.materiality_weight_numeric * numeric
    )
    return {
        "novelty": round(novelty, 4),
        "risk_weight": risk_weight,
        "uncertainty_shift": uncertainty,
        "section_importance": section_importance,
        "numeric_change": numeric,
        "model_confidence": confidence,
        "materiality_score": score,
    }


def evidence_payload(
    *,
    current_passage: PassageUnit | None,
    previous_passage: PassageUnit | None,
    current_section: FilingSection | None,
    previous_section: FilingSection | None,
) -> dict[str, object]:
    return {
        "previous": _evidence(previous_passage, previous_section),
        "current": _evidence(current_passage, current_section),
    }


def validate_evidence(change_type: str, evidence: dict[str, object]) -> None:
    previous = evidence.get("previous")
    current = evidence.get("current")
    if change_type == "added" and current is None:
        raise ValueError("Added findings require current evidence.")
    if change_type == "removed" and previous is None:
        raise ValueError("Removed findings require previous evidence.")
    if change_type not in {"added", "removed"} and (previous is None or current is None):
        raise ValueError("Matched findings require previous and current evidence.")


def _evidence(
    passage: PassageUnit | None,
    section: FilingSection | None,
) -> dict[str, object] | None:
    if passage is None or section is None:
        return None
    return {
        "filing_id": str(section.filing_id),
        "section_id": str(section.id),
        "passage_id": str(passage.id),
        "part_number": section.part_number,
        "item_number": section.item_number,
        "source_anchor": passage.source_anchor,
        "raw_char_start": passage.raw_char_start,
        "raw_char_end": passage.raw_char_end,
        "content_hash": passage.content_hash,
    }


def _section_metadata(
    current_section: FilingSection | None,
    previous_section: FilingSection | None,
) -> dict[str, object]:
    section = current_section or previous_section
    if section is None:
        return {}
    return {
        "section_type": section.section_type,
        "canonical_section_type": section.canonical_section_type,
        "part_number": section.part_number,
        "item_number": section.item_number,
        "section_title": section.section_title,
    }
