"""Live evaluation of the configured generative provider against small labelled fixtures.

Runs the REAL provider (whatever ``CHANGE_CLASSIFIER_*`` / ``CLAIM_EXTRACTOR_*`` point at) on:

* disclosure-change classification - the 40 author-written Phase 3 fixtures, and
* financial-claim extraction - the 60 author-written Phase 4 sentences,

next to the deterministic baseline that the pipeline itself uses, on exactly the same inputs.
Raw predictions, model name, prompt version, timestamps and dataset versions are persisted to a
JSON file after every provider call, so a stopped run (daily quota, repeated provider errors, a
crash) keeps everything it already paid for and can be resumed without repeating those calls.

Nothing here tunes prompts, changes retry behaviour, or touches the database. Provider-level
failures use the production client's own classification (``ProviderRequestError`` subtypes): a daily
quota stops the whole run immediately; other failures stop it after a small number in a row, so the
evaluation never spends retries against a provider that is clearly refusing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.ai.batching import BatchingConfig, BatchItem, plan_batches
from app.ai.financial_claims import (
    ClaimBatchItem,
    ClaimExtractorProvider,
    FinancialClaimExtraction,
    claim_item_tokens,
)
from app.ai.inference import UsageTotals, collect_usage
from app.ai.openai_compatible import (
    QUOTA_EXHAUSTED_DAILY,
    ProviderRequestError,
    StructuredOutputError,
)
from app.ai.semantic_change import (
    ChangeClassificationRequest,
    ChangeClassificationResult,
    ChangeClassifierProvider,
    DeterministicFakeChangeClassifier,
    change_request_tokens,
)
from app.core.config import Settings
from app.db.models import FinancialMetricDefinition
from app.evaluation.datasets import (
    BACKEND_ROOT,
    EVALUATION_ROOT,
    TEST_FIXTURE_ROOT,
    load_json,
    load_manifest,
)
from app.evaluation.metrics import classification_report, metric, not_evaluated
from app.services.comparison_utils import deterministic_signals
from app.services.financial_claim_extraction_service import FinancialClaimExtractionService
from app.services.financial_metric_registry import FinancialMetricRegistry

RESULTS_SCHEMA_VERSION = "live-provider-eval-v1"
CHANGE_TASK = "disclosure_change"
CLAIM_TASK = "claim_extraction"
ALL_TASKS = (CHANGE_TASK, CLAIM_TASK)

CHANGE_LABELS = ["added", "removed", "strengthened", "weakened", "no_material_change"]
RISK_LABELS = ["liquidity", "revenue_guidance", "litigation", "other"]
NO_PREDICTION = "<no_prediction>"

# Claim-type gold exists only where the fixture category names one unambiguously. The
# period_resolution and ambiguous_or_error categories carry no claim-type label, so they are not
# scored on claim type (inferring one would be inventing a label).
CATEGORY_TO_CLAIM_TYPE = {
    "absolute_value": "absolute_value",
    "percentage_change": "percentage_change",
    "percentage_point_change": "percentage_point_change",
}

# Item statuses for the provider under evaluation.
STATUS_OK = "ok"
STATUS_INVALID = "invalid_output"  # provider answered, structured output unusable after repair
STATUS_PROVIDER_ERROR = "provider_error"
STATUS_NOT_RUN = "not_run"
DONE_STATUSES = frozenset({STATUS_OK, STATUS_INVALID})

_SAFE_INFERENCE_KEYS = (
    "provider",
    "provider_type",
    "model",
    "model_version",
    "prompt_version",
    "created_at",
    "latency_ms",
    "success",
    "parse_status",
    "retry_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "batch_size",
    "response_id",
)


class EvaluationConfigError(RuntimeError):
    """The requested live evaluation cannot be run as configured."""


@dataclass
class RunControl:
    """Stop conditions shared by every task in one run."""

    max_requests: int | None = None
    max_consecutive_provider_errors: int = 2
    requests_made: int = 0
    consecutive_errors: int = 0
    stop_reason: str | None = None

    def should_stop(self) -> bool:
        if self.stop_reason is not None:
            return True
        if self.max_requests is not None and self.requests_made >= self.max_requests:
            self.stop_reason = f"max_requests_reached ({self.max_requests})"
            return True
        return False

    def record_success(self) -> None:
        self.consecutive_errors = 0

    def record_provider_error(self, exc: ProviderRequestError) -> None:
        self.consecutive_errors += 1
        if exc.error_subtype == QUOTA_EXHAUSTED_DAILY:
            self.stop_reason = "daily_quota_exhausted"
        elif not exc.is_retryable:
            self.stop_reason = f"non_retryable_provider_error ({exc.error_subtype})"
        elif self.consecutive_errors >= self.max_consecutive_provider_errors:
            self.stop_reason = (
                f"{self.consecutive_errors}_consecutive_provider_errors ({exc.error_subtype})"
            )


# --------------------------------------------------------------------------------------
# Datasets and the deterministic baseline
# --------------------------------------------------------------------------------------


def load_change_examples() -> list[dict[str, Any]]:
    return list(load_json(TEST_FIXTURE_ROOT / "comparison" / "phase3_examples.json"))


def load_claim_examples() -> list[dict[str, Any]]:
    return list(load_json(TEST_FIXTURE_ROOT / "financial_claims" / "phase4_examples.json"))


def dataset_version(name: str) -> str:
    return load_manifest(EVALUATION_ROOT / "datasets" / name / "manifest.json").dataset_version


def build_change_request(example: dict[str, Any]) -> ChangeClassificationRequest:
    previous = example.get("previous_text")
    current = example.get("current_text")
    return ChangeClassificationRequest(
        previous_text=previous,
        current_text=current,
        deterministic_signals=deterministic_signals(previous, current),
        section_metadata={},
        allowed_labels=list(CHANGE_LABELS),
    )


class _SeedRepo:
    def __init__(self, definitions: list[FinancialMetricDefinition]) -> None:
        self.definitions = definitions

    async def list_metric_definitions(
        self, *, active_only: bool = True
    ) -> list[FinancialMetricDefinition]:
        return self.definitions


def load_seed_metric_definitions() -> list[FinancialMetricDefinition]:
    """The metric definitions migration 0004 seeds into ``financial_metric_definitions``.

    Read straight from the migration so the deterministic baseline sees exactly the aliases
    production sees, without a database.
    """
    path = BACKEND_ROOT / "alembic" / "versions" / "0004_phase4_financial.py"
    spec = importlib.util.spec_from_file_location("_seed_0004_phase4_financial", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise EvaluationConfigError(f"Cannot load metric seed from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [
        FinancialMetricDefinition(
            canonical_name=canonical,
            display_name=display,
            metric_type=metric_type,
            period_behavior=period_behavior,
            preferred_unit_category=unit_category,
            description=description,
            aliases=aliases,
            is_active=True,
        )
        for (
            _id,
            canonical,
            display,
            metric_type,
            period_behavior,
            unit_category,
            description,
            aliases,
        ) in module.METRICS
    ]


def build_deterministic_extractor(
    settings: Settings, definitions: list[FinancialMetricDefinition]
) -> FinancialClaimExtractionService:
    """The pipeline's own first-pass extractor (alias matching + number parsing)."""
    service = FinancialClaimExtractionService(None, settings, None)  # type: ignore[arg-type]
    registry = FinancialMetricRegistry(None, settings)  # type: ignore[arg-type]
    registry.repo = _SeedRepo(definitions)  # type: ignore[assignment]
    service.registry = registry
    return service


# --------------------------------------------------------------------------------------
# Results file
# --------------------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_inference(metadata: object) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {key: metadata[key] for key in _SAFE_INFERENCE_KEYS if key in metadata}


def save_results(results: dict[str, Any], path: Path) -> None:
    """Atomic write, so a crash mid-save can never corrupt an earlier good file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(results, indent=2, sort_keys=False), encoding="utf-8")
    os.replace(temporary, path)


def _git_revision() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BACKEND_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return completed.stdout.strip() or None


def _new_results(
    *,
    settings: Settings,
    tasks: tuple[str, ...],
    modes: dict[str, str],
    change_classifier: ChangeClassifierProvider | None,
    claim_extractor: ClaimExtractorProvider | None,
) -> dict[str, Any]:
    host = urlparse(settings.ai_provider_base_url).hostname
    return {
        "schema_version": RESULTS_SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "created_at": _now(),
        "finished_at": None,
        "status": "running",
        "stop_reason": None,
        "code_version": _git_revision(),
        "provider": {
            "provider": settings.change_classifier_provider,
            "base_url_host": host,
            "chat_delay_seconds": settings.ai_provider_chat_delay_seconds,
            "max_retries": settings.ai_provider_max_retries,
            "structured_output_repair_attempts": (
                settings.ai_provider_structured_output_repair_attempts
            ),
            "batch_max_items": settings.ai_batch_max_items,
            "batch_input_token_budget": settings.ai_batch_input_token_budget,
            "batch_token_safety_margin": settings.ai_batch_token_safety_margin,
        },
        "tasks_requested": list(tasks),
        "datasets": {
            CHANGE_TASK: {
                "name": "phase3_fixture",
                "version": dataset_version("phase3"),
                "provenance": "author-written fixture (tests/fixtures/comparison)",
            },
            CLAIM_TASK: {
                "name": "phase4_fixture",
                "version": dataset_version("phase4"),
                "provenance": "author-written fixture (tests/fixtures/financial_claims)",
            },
        },
        "tasks": {
            CHANGE_TASK: {
                "mode": modes.get(CHANGE_TASK),
                "model": getattr(change_classifier, "model_name", None),
                "prompt_version": (
                    getattr(change_classifier, "batch_prompt_version", None)
                    if modes.get(CHANGE_TASK) == "batch"
                    else getattr(change_classifier, "prompt_version", None)
                ),
                "items": {},
            },
            CLAIM_TASK: {
                "mode": modes.get(CLAIM_TASK),
                "model": getattr(claim_extractor, "model_name", None),
                "prompt_version": (
                    getattr(claim_extractor, "batch_prompt_version", None)
                    if modes.get(CLAIM_TASK) == "batch"
                    else getattr(claim_extractor, "prompt_version", None)
                ),
                "items": {},
            },
        },
        "usage": {
            "provider_chat_requests": 0,
            "requests_reporting_usage": 0,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "note": "Token counts are provider-reported and only summed where reported.",
        },
        "real_sec_claim_extraction": real_sec_claim_coverage(),
    }


def real_sec_claim_coverage() -> dict[str, Any]:
    """How much of the human-approved real-SEC benchmark can score claim extraction."""
    payload = load_json(EVALUATION_ROOT / "datasets" / "real_sec_v1" / "examples.json")
    examples = payload["examples"] if isinstance(payload, dict) else payload
    approved = [
        example
        for example in examples
        if example.get("task_type") == "financial_claim"
        and example.get("annotation_status") == "approved"
    ]
    with_text = [
        example
        for example in approved
        if (example.get("input_references") or {}).get("text")
        or (example.get("input_references") or {}).get("passage_text")
    ]
    return {
        "status": "not_evaluated",
        "approved_financial_claim_records": len(approved),
        "records_with_stored_input_text": len(with_text),
        "approved_records_all_tasks": sum(
            1 for example in examples if example.get("annotation_status") == "approved"
        ),
        "reason": (
            "The real-SEC benchmark stores identifiers and locators, not filing text, and only "
            f"{len(approved)} human-approved record(s) are financial-claim records; none stores "
            "the passage to extract from. Claim extraction is therefore scored on the "
            "author-written Phase 4 fixture instead."
        ),
    }


def _add_usage(results: dict[str, Any], totals: UsageTotals) -> None:
    usage = results["usage"]
    usage["provider_chat_requests"] += totals.requests
    usage["requests_reporting_usage"] += totals.requests_reporting_usage
    for source, key in (
        (totals.input_tokens, "input_tokens"),
        (totals.output_tokens, "output_tokens"),
        (totals.total_tokens, "total_tokens"),
    ):
        if source is not None:
            usage[key] = source if usage[key] is None else usage[key] + source


def _provider_record(
    *,
    status: str,
    via: str | None = None,
    prediction: object = None,
    inference: object = None,
    error: ProviderRequestError | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "via": via,
        "run_at": _now(),
        "prediction": prediction,
        "inference": _safe_inference(inference),
        "error_type": type(error).__name__ if error else None,
        "error_subtype": error.error_subtype if error else None,
        "error_status_code": error.status_code if error else None,
        "retry_after_seconds": error.retry_after_seconds if error else None,
    }


def _is_done(record: dict[str, Any]) -> bool:
    return record.get("gemini", {}).get("status") in DONE_STATUSES


# --------------------------------------------------------------------------------------
# Disclosure-change task
# --------------------------------------------------------------------------------------


def _change_prediction(result: ChangeClassificationResult) -> dict[str, Any]:
    return result.model_dump(exclude={"inference_metadata"})


async def _seed_change_items(
    results: dict[str, Any],
    examples: list[dict[str, Any]],
    baseline: DeterministicFakeChangeClassifier,
) -> None:
    items = results["tasks"][CHANGE_TASK]["items"]
    for example in examples:
        if example["id"] in items:
            continue
        request = build_change_request(example)
        outcome = await baseline.classify(request)
        items[example["id"]] = {
            "id": example["id"],
            "input": {
                "previous_text": example.get("previous_text"),
                "current_text": example.get("current_text"),
            },
            "expected": {
                "change_type": example["expected_change_type"],
                "risk_category": example["expected_risk_category"],
            },
            "baseline": _change_prediction(outcome),
            "gemini": _provider_record(status=STATUS_NOT_RUN),
        }


async def _run_change_task(
    results: dict[str, Any],
    examples: list[dict[str, Any]],
    classifier: ChangeClassifierProvider,
    *,
    mode: str,
    batching: BatchingConfig,
    control: RunControl,
    on_progress: Callable[[], None],
) -> None:
    items = results["tasks"][CHANGE_TASK]["items"]
    requests = {example["id"]: build_change_request(example) for example in examples}

    async def classify_single(item_id: str, via: str) -> None:
        if control.should_stop():
            return
        control.requests_made += 1
        try:
            with collect_usage() as totals:
                result = await classifier.classify(requests[item_id])
        except StructuredOutputError as exc:
            _add_usage(results, totals)
            items[item_id]["gemini"] = _provider_record(
                status=STATUS_INVALID, via=via, inference=exc.metadata.model_dump()
            )
            control.record_success()
            return
        except ProviderRequestError as exc:
            _add_usage(results, totals)
            items[item_id]["gemini"] = _provider_record(
                status=STATUS_PROVIDER_ERROR, via=via, error=exc
            )
            control.record_provider_error(exc)
            return
        _add_usage(results, totals)
        items[item_id]["gemini"] = _provider_record(
            status=STATUS_OK,
            via=via,
            prediction=_change_prediction(result),
            inference=result.inference_metadata,
        )
        control.record_success()

    if mode == "single" or not hasattr(classifier, "classify_batch"):
        for example in examples:
            if _is_done(items[example["id"]]):
                continue
            await classify_single(example["id"], "single")
            on_progress()
            if control.should_stop():
                return
        return

    planned = plan_batches(
        [
            BatchItem(
                identity=example["id"],
                estimated_tokens=change_request_tokens(requests[example["id"]]),
            )
            for example in examples
        ],
        batching,
        fixed_overhead_tokens=int(getattr(classifier, "batch_fixed_overhead_tokens", 0)),
    )
    for batch in planned:
        pending = [item_id for item_id in batch.identities if not _is_done(items[item_id])]
        if not pending:
            continue
        if control.should_stop():
            return
        control.requests_made += 1
        try:
            with collect_usage() as totals:
                outcomes = await classifier.classify_batch(  # type: ignore[attr-defined]
                    [(item_id, requests[item_id]) for item_id in pending]
                )
        except ProviderRequestError as exc:
            _add_usage(results, totals)
            for item_id in pending:
                items[item_id]["gemini"] = _provider_record(
                    status=STATUS_PROVIDER_ERROR, via="batch", error=exc
                )
            control.record_provider_error(exc)
            on_progress()
            if control.should_stop():
                return
            continue
        _add_usage(results, totals)
        control.record_success()
        for item_id in pending:
            outcome = outcomes.get(item_id)
            if outcome is not None:
                items[item_id]["gemini"] = _provider_record(
                    status=STATUS_OK,
                    via="batch",
                    prediction=_change_prediction(outcome),
                    inference=outcome.inference_metadata,
                )
        on_progress()
        # Production retries just the items the batch could not answer, one at a time.
        for item_id in pending:
            if not _is_done(items[item_id]):
                await classify_single(item_id, "single_retry")
                on_progress()
                if control.should_stop():
                    return


# --------------------------------------------------------------------------------------
# Claim-extraction task
# --------------------------------------------------------------------------------------


def _claim_prediction(claim: FinancialClaimExtraction) -> dict[str, Any]:
    dumped = claim.model_dump(mode="json", exclude={"original_output"})
    return {
        key: dumped.get(key)
        for key in (
            "claim_text",
            "canonical_metric_name",
            "claim_type",
            "direction",
            "reported_value",
            "reported_unit",
            "reported_change",
            "reported_change_unit",
            "comparison_basis",
            "confidence",
        )
    }


async def _seed_claim_items(
    results: dict[str, Any],
    examples: list[dict[str, Any]],
    deterministic: FinancialClaimExtractionService,
) -> None:
    items = results["tasks"][CLAIM_TASK]["items"]
    for example in examples:
        if example["id"] in items:
            continue
        baseline_claims = await deterministic.deterministic_extract(example["claim"])
        items[example["id"]] = {
            "id": example["id"],
            "input": {"text": example["claim"], "category": example["category"]},
            "expected": {
                "canonical_metric": example.get("metric"),
                "claim_type": CATEGORY_TO_CLAIM_TYPE.get(example["category"]),
            },
            "baseline": [_claim_prediction(claim) for claim in baseline_claims],
            "gemini": _provider_record(status=STATUS_NOT_RUN),
        }


async def _run_claim_task(
    results: dict[str, Any],
    examples: list[dict[str, Any]],
    extractor: ClaimExtractorProvider,
    allowed_metrics: list[str],
    *,
    mode: str,
    batching: BatchingConfig,
    control: RunControl,
    on_progress: Callable[[], None],
) -> None:
    items = results["tasks"][CLAIM_TASK]["items"]
    texts = {example["id"]: example["claim"] for example in examples}

    async def extract_single(item_id: str, via: str) -> None:
        if control.should_stop():
            return
        control.requests_made += 1
        try:
            with collect_usage() as totals:
                claims = await extractor.extract_claims(texts[item_id], {}, allowed_metrics)
        except StructuredOutputError as exc:
            _add_usage(results, totals)
            items[item_id]["gemini"] = _provider_record(
                status=STATUS_INVALID, via=via, inference=exc.metadata.model_dump()
            )
            control.record_success()
            return
        except ProviderRequestError as exc:
            _add_usage(results, totals)
            items[item_id]["gemini"] = _provider_record(
                status=STATUS_PROVIDER_ERROR, via=via, error=exc
            )
            control.record_provider_error(exc)
            return
        _add_usage(results, totals)
        items[item_id]["gemini"] = _provider_record(
            status=STATUS_OK,
            via=via,
            prediction=[_claim_prediction(claim) for claim in claims],
            inference=(claims[0].original_output.get("inference_metadata") if claims else None),
        )
        control.record_success()

    if mode == "single" or not hasattr(extractor, "extract_claims_batch"):
        for example in examples:
            if _is_done(items[example["id"]]):
                continue
            await extract_single(example["id"], "single")
            on_progress()
            if control.should_stop():
                return
        return

    fixed_overhead = int(extractor.batch_fixed_overhead_tokens(allowed_metrics))  # type: ignore[attr-defined]
    planned = plan_batches(
        [
            BatchItem(
                identity=example["id"],
                estimated_tokens=claim_item_tokens(example["claim"], {}),
            )
            for example in examples
        ],
        batching,
        fixed_overhead_tokens=fixed_overhead,
    )
    for batch in planned:
        pending = [item_id for item_id in batch.identities if not _is_done(items[item_id])]
        if not pending:
            continue
        if control.should_stop():
            return
        control.requests_made += 1
        try:
            with collect_usage() as totals:
                outcomes = await extractor.extract_claims_batch(  # type: ignore[attr-defined]
                    [ClaimBatchItem(item_id=item_id, text=texts[item_id]) for item_id in pending],
                    allowed_metrics,
                )
        except ProviderRequestError as exc:
            _add_usage(results, totals)
            for item_id in pending:
                items[item_id]["gemini"] = _provider_record(
                    status=STATUS_PROVIDER_ERROR, via="batch", error=exc
                )
            control.record_provider_error(exc)
            on_progress()
            if control.should_stop():
                return
            continue
        _add_usage(results, totals)
        control.record_success()
        for item_id in pending:
            claims = outcomes.get(item_id)
            if claims is not None:
                items[item_id]["gemini"] = _provider_record(
                    status=STATUS_OK,
                    via="batch",
                    prediction=[_claim_prediction(claim) for claim in claims],
                    inference=(
                        claims[0].original_output.get("inference_metadata") if claims else None
                    ),
                )
        on_progress()
        for item_id in pending:
            if not _is_done(items[item_id]):
                await extract_single(item_id, "single_retry")
                on_progress()
                if control.should_stop():
                    return


# --------------------------------------------------------------------------------------
# Metrics (pure functions over the results file - unit-testable without any provider)
# --------------------------------------------------------------------------------------


def _paired(items: dict[str, Any]) -> list[dict[str, Any]]:
    """Items the provider actually answered (or failed to answer validly) - the only ones on
    which both systems are comparable. provider_error / not_run items are excluded from both."""
    return [item for item in items.values() if _is_done(item)]


def change_metrics(items: dict[str, Any]) -> dict[str, Any]:
    paired = _paired(items)
    total = len(items)
    if not paired:
        reason = "No provider predictions were produced."
        return {
            "n_total": total,
            "n_scored": 0,
            "gemini": not_evaluated(reason),
            "baseline": not_evaluated(reason),
        }

    def system_report(predict: Callable[[dict[str, Any]], tuple[str, str]]) -> dict[str, Any]:
        expected_type = [item["expected"]["change_type"] for item in paired]
        expected_risk = [item["expected"]["risk_category"] for item in paired]
        predicted = [predict(item) for item in paired]
        return {
            "change_type": classification_report(
                expected_type, [p[0] for p in predicted], labels=list(CHANGE_LABELS)
            ),
            "risk_category": classification_report(
                expected_risk, [p[1] for p in predicted], labels=list(RISK_LABELS)
            ),
        }

    def gemini_prediction(item: dict[str, Any]) -> tuple[str, str]:
        prediction = item["gemini"].get("prediction")
        if not prediction:
            return NO_PREDICTION, NO_PREDICTION
        return prediction["change_type"], prediction["risk_category"]

    def baseline_prediction(item: dict[str, Any]) -> tuple[str, str]:
        return item["baseline"]["change_type"], item["baseline"]["risk_category"]

    statuses = Counter(item["gemini"]["status"] for item in items.values())
    return {
        "n_total": total,
        "n_scored": len(paired),
        "n_remaining": total - len(paired),
        "provider_status_counts": dict(statuses),
        "gemini": system_report(gemini_prediction),
        "baseline": system_report(baseline_prediction),
    }


def score_claim_item(
    gold_metric: str | None, gold_type: str | None, claims: list[dict[str, Any]]
) -> dict[str, Any]:
    """Per-item extraction scoring.

    * metric correct: a predicted claim carries the gold canonical metric; for items whose gold
      metric is null (ambiguous / unsupported wording) it is correct only if NO claim asserts a
      metric.
    * claim type correct (typed items only): some predicted claim has the gold claim type.
    * exact match (typed items only): exactly one claim, with the gold metric AND gold type.
    """
    predicted_metrics = [claim.get("canonical_metric_name") for claim in claims]
    if gold_metric is None:
        metric_ok = all(value is None for value in predicted_metrics)
        spurious = any(value is not None for value in predicted_metrics)
    else:
        metric_ok = gold_metric in predicted_metrics
        spurious = False
    type_ok = None
    exact = None
    if gold_type is not None:
        type_ok = any(claim.get("claim_type") == gold_type for claim in claims)
        exact = (
            len(claims) == 1
            and claims[0].get("canonical_metric_name") == gold_metric
            and claims[0].get("claim_type") == gold_type
        )
    return {
        "metric_correct": metric_ok,
        "claim_type_correct": type_ok,
        "exact_match": exact,
        "spurious_metric": spurious if gold_metric is None else None,
        "produced_claim": bool(claims),
        "n_claims": len(claims),
    }


def _claims_for(item: dict[str, Any], system: str) -> list[dict[str, Any]]:
    baseline = item["baseline"]
    gemini = item["gemini"].get("prediction") or []
    if system == "baseline":
        return baseline
    if system == "gemini":
        return gemini
    # The pipeline's actual behaviour: the deterministic pass wins; the model is only consulted
    # when it found nothing (see FinancialClaimExtractionService._hybrid_extract).
    return baseline if baseline else gemini


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator == 0:
        return not_evaluated("No eligible examples.", n=0)
    return metric(numerator / denominator, n=denominator)


def claim_metrics(items: dict[str, Any]) -> dict[str, Any]:
    paired = _paired(items)
    total = len(items)
    if not paired:
        reason = "No provider predictions were produced."
        return {"n_total": total, "n_scored": 0, "systems": {}, "reason": reason}
    systems: dict[str, Any] = {}
    for system in ("baseline", "gemini", "hybrid"):
        scored = [
            (
                item,
                score_claim_item(
                    item["expected"]["canonical_metric"],
                    item["expected"]["claim_type"],
                    _claims_for(item, system),
                ),
            )
            for item in paired
        ]
        typed = [s for _, s in scored if s["claim_type_correct"] is not None]
        with_metric = [
            s for item, s in scored if item["expected"]["canonical_metric"] is not None
        ]
        without_metric = [
            s for item, s in scored if item["expected"]["canonical_metric"] is None
        ]
        per_category: dict[str, Any] = {}
        for category in sorted({item["input"]["category"] for item, _ in scored}):
            rows = [s for item, s in scored if item["input"]["category"] == category]
            per_category[category] = _rate(sum(s["metric_correct"] for s in rows), len(rows))
        systems[system] = {
            "canonical_metric_accuracy": _rate(
                sum(s["metric_correct"] for _, s in scored), len(scored)
            ),
            "claim_type_accuracy": _rate(
                sum(bool(s["claim_type_correct"]) for s in typed), len(typed)
            ),
            "exact_match_rate": _rate(sum(bool(s["exact_match"]) for s in typed), len(typed)),
            "claim_recall_on_items_with_a_metric": _rate(
                sum(s["produced_claim"] for s in with_metric), len(with_metric)
            ),
            "spurious_metric_rate_on_items_without_a_metric": _rate(
                sum(bool(s["spurious_metric"]) for s in without_metric), len(without_metric)
            ),
            "metric_accuracy_by_category": per_category,
        }
    statuses = Counter(item["gemini"]["status"] for item in items.values())
    return {
        "n_total": total,
        "n_scored": len(paired),
        "n_remaining": total - len(paired),
        "provider_status_counts": dict(statuses),
        "systems": systems,
    }


def phase4_metrics(claims: dict[str, Any], model: str | None) -> dict[str, Any]:
    """The Phase 4 metrics the offline report leaves ``not_evaluated``, filled where a real
    provider run now supplies predictions. Everything that needs XBRL facts or the verifier stays
    ``not_evaluated`` - a provider run cannot produce those."""
    verifier_reason = (
        "Needs XBRL facts and verifier predictions; not produced by a provider evaluation."
    )
    filled: dict[str, Any]
    if claims.get("systems"):
        gemini = claims["systems"]["gemini"]
        filled = {
            "claim_extraction.canonical_metric_accuracy": {
                **gemini["canonical_metric_accuracy"],
                "system": f"gemini:{model}",
            },
            "claim_extraction.claim_type_accuracy": {
                **gemini["claim_type_accuracy"],
                "system": f"gemini:{model}",
            },
        }
    else:
        reason = "No provider claim-extraction predictions were produced."
        filled = {
            "claim_extraction.canonical_metric_accuracy": not_evaluated(reason),
            "claim_extraction.claim_type_accuracy": not_evaluated(reason),
        }
    for key in (
        "xbrl_resolution.concept_selection_accuracy",
        "xbrl_resolution.period_resolution_accuracy",
        "xbrl_resolution.unit_selection_accuracy",
        "verification_status",
        "unsafe_period_match_rate",
        "unsafe_unit_acceptance_rate",
        "deterministic_calculation.reproducible_calculation_rate",
    ):
        filled[key] = not_evaluated(verifier_reason)
    return filled


def compute_metrics(results: dict[str, Any]) -> None:
    change = results["tasks"][CHANGE_TASK]
    claims = results["tasks"][CLAIM_TASK]
    change["metrics"] = change_metrics(change["items"]) if change["items"] else None
    claims["metrics"] = claim_metrics(claims["items"]) if claims["items"] else None
    results["phase4_metrics"] = phase4_metrics(claims["metrics"] or {}, claims.get("model"))


def remaining_counts(results: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in ALL_TASKS:
        items = results["tasks"][task]["items"]
        if items:
            counts[task] = sum(1 for item in items.values() if not _is_done(item))
    return counts


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


def resolve_mode(requested: str, provider: object, batch_method: str, settings: Settings) -> str:
    if requested == "single":
        return "single"
    if requested == "batch":
        if not hasattr(provider, batch_method):
            raise EvaluationConfigError("The configured provider has no multi-item batch method.")
        return "batch"
    # auto: mirror what the pipeline does for the current configuration.
    if settings.ai_batch_multi_item_requests and hasattr(provider, batch_method):
        return "batch"
    return "single"


def load_resume(path: Path, *, model_change: str | None, model_claim: str | None) -> dict[str, Any]:
    previous = load_json(path)
    if previous.get("schema_version") != RESULTS_SCHEMA_VERSION:
        raise EvaluationConfigError(f"{path} is not a {RESULTS_SCHEMA_VERSION} results file.")
    for task, model in ((CHANGE_TASK, model_change), (CLAIM_TASK, model_claim)):
        recorded = previous["tasks"][task].get("model")
        if recorded and model and recorded != model:
            raise EvaluationConfigError(
                f"Cannot resume {path.name}: {task} was run with model {recorded!r} but the "
                f"current configuration is {model!r}."
            )
    return previous


async def run_live_evaluation(
    *,
    settings: Settings,
    change_classifier: ChangeClassifierProvider | None,
    claim_extractor: ClaimExtractorProvider | None,
    tasks: tuple[str, ...] = ALL_TASKS,
    mode: str = "auto",
    output_path: Path,
    resume: bool = False,
    max_requests: int | None = None,
    max_consecutive_provider_errors: int = 2,
    on_message: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run (or resume) the evaluation, saving ``output_path`` after every provider call."""
    if CHANGE_TASK in tasks and change_classifier is None:
        raise EvaluationConfigError("A change classifier is required for the change task.")
    if CLAIM_TASK in tasks and claim_extractor is None:
        raise EvaluationConfigError("A claim extractor is required for the claim task.")

    modes: dict[str, str] = {}
    if change_classifier is not None:
        modes[CHANGE_TASK] = resolve_mode(mode, change_classifier, "classify_batch", settings)
    if claim_extractor is not None:
        modes[CLAIM_TASK] = resolve_mode(mode, claim_extractor, "extract_claims_batch", settings)

    if resume:
        results = load_resume(
            output_path,
            model_change=getattr(change_classifier, "model_name", None),
            model_claim=getattr(claim_extractor, "model_name", None),
        )
        results["status"] = "running"
        results["stop_reason"] = None
        results["resumed_at"] = [*results.get("resumed_at", []), _now()]
    else:
        results = _new_results(
            settings=settings,
            tasks=tasks,
            modes=modes,
            change_classifier=change_classifier,
            claim_extractor=claim_extractor,
        )

    control = RunControl(
        max_requests=max_requests,
        max_consecutive_provider_errors=max_consecutive_provider_errors,
    )
    batching = BatchingConfig.from_settings(settings)

    def persist() -> None:
        compute_metrics(results)
        save_results(results, output_path)

    error: BaseException | None = None
    try:
        if CHANGE_TASK in tasks:
            examples = load_change_examples()
            await _seed_change_items(results, examples, DeterministicFakeChangeClassifier())
            persist()
            on_message(f"[{CHANGE_TASK}] {len(examples)} items, mode={modes[CHANGE_TASK]}")
            await _run_change_task(
                results,
                examples,
                change_classifier,  # type: ignore[arg-type]
                mode=modes[CHANGE_TASK],
                batching=batching,
                control=control,
                on_progress=persist,
            )
        if CLAIM_TASK in tasks and not control.should_stop():
            definitions = load_seed_metric_definitions()
            allowed_metrics = [definition.canonical_name for definition in definitions]
            deterministic = build_deterministic_extractor(settings, definitions)
            examples = load_claim_examples()
            await _seed_claim_items(results, examples, deterministic)
            persist()
            on_message(f"[{CLAIM_TASK}] {len(examples)} items, mode={modes[CLAIM_TASK]}")
            await _run_claim_task(
                results,
                examples,
                claim_extractor,  # type: ignore[arg-type]
                allowed_metrics,
                mode=modes[CLAIM_TASK],
                batching=batching,
                control=control,
                on_progress=persist,
            )
    except BaseException as exc:  # save what was paid for, then let it propagate
        error = exc
        control.stop_reason = control.stop_reason or f"crashed ({type(exc).__name__})"
    finally:
        remaining = remaining_counts(results)
        results["remaining_items"] = remaining
        results["stop_reason"] = control.stop_reason
        results["finished_at"] = _now()
        results["control"] = {
            "provider_calls_issued": control.requests_made,
            "max_requests": max_requests,
            "max_consecutive_provider_errors": max_consecutive_provider_errors,
        }
        if error is not None:
            results["status"] = "failed"
        elif any(remaining.values()):
            results["status"] = "partial"
        else:
            results["status"] = "completed"
        persist()
    if error is not None:
        raise error
    return results


# --------------------------------------------------------------------------------------
# Markdown report
# --------------------------------------------------------------------------------------


def _fmt(value: object) -> str:
    if isinstance(value, dict) and "value" in value:
        if value.get("status") != "evaluated":
            return "not evaluated"
        raw = value["value"]
        return f"{raw:.3f}" if isinstance(raw, float) else str(raw)
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _f1_cell(value: object) -> str:
    return f"{value:.3f}" if isinstance(value, int | float) else "n/a"


def _snippet(text: object, limit: int = 150) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _confusion_table(matrix: dict[str, dict[str, int]], labels: list[str]) -> list[str]:
    columns = [*labels, NO_PREDICTION]
    lines = ["| expected \\ predicted | " + " | ".join(columns) + " |"]
    lines.append("|---|" + "---|" * len(columns))
    for label in labels:
        row = matrix.get(label, {})
        lines.append(f"| **{label}** | " + " | ".join(str(row.get(c, 0)) for c in columns) + " |")
    return lines


def render_markdown(results: dict[str, Any]) -> str:
    provider = results["provider"]
    out: list[str] = [
        "# Live Provider Evaluation",
        "",
        f"- Run: `{results['run_id']}`  (code `{results.get('code_version')}`)",
        f"- Status: **{results['status']}**"
        + (f" - stopped: `{results['stop_reason']}`" if results.get("stop_reason") else ""),
        f"- Created: {results['created_at']}  Finished: {results.get('finished_at')}",
        f"- Provider: `{provider['provider']}` at `{provider['base_url_host']}`  "
        f"(chat delay {provider['chat_delay_seconds']}s, client max retries "
        f"{provider['max_retries']}, repair attempts "
        f"{provider['structured_output_repair_attempts']})",
    ]
    for task in ALL_TASKS:
        info = results["tasks"][task]
        if info["items"]:
            out.append(
                f"- `{task}`: model `{info['model']}`, mode `{info['mode']}`, prompt "
                f"`{info['prompt_version']}`, dataset "
                f"`{results['datasets'][task]['name']}` `{results['datasets'][task]['version']}` "
                f"({results['datasets'][task]['provenance']})"
            )
    usage = results["usage"]
    out += [
        f"- Provider chat requests (incl. repair attempts): {usage['provider_chat_requests']}; "
        f"reported tokens in/out/total: {usage['input_tokens']}/{usage['output_tokens']}/"
        f"{usage['total_tokens']}",
        "",
        "> **Read this first.** Both datasets are small and were written by the project author, "
        "not sampled from filings and not independently labelled. The comparison is between the "
        "pipeline's deterministic components and the configured LLM on identical inputs, from a "
        "**single run** with no prompt tuning; LLM output is not guaranteed to repeat. Treat the "
        "numbers as a first honest measurement, not as a quality claim.",
        "",
    ]
    remaining = results.get("remaining_items") or {}
    if any(remaining.values()):
        out += [
            "**Incomplete run.** Items not answered by the provider (excluded from BOTH systems' "
            "scores so the comparison stays paired): "
            + ", ".join(f"{task}: {count}" for task, count in remaining.items() if count)
            + ". Resume with `--resume` once the cause is fixed.",
            "",
        ]

    change = results["tasks"][CHANGE_TASK].get("metrics")
    if change:
        out += ["## Disclosure-change classification", ""]
        out.append(
            f"Scored {change['n_scored']} of {change['n_total']} items. Provider status: "
            f"{change.get('provider_status_counts')}."
        )
        out.append("")
        if change["n_scored"]:
            g, b = change["gemini"], change["baseline"]
            out += [
                "| metric | deterministic baseline | Gemini |",
                "|---|---|---|",
            ]
            for name, key, sub in (
                ("change_type accuracy", "change_type", "accuracy"),
                ("change_type macro F1", "change_type", "macro_f1"),
                ("change_type weighted F1", "change_type", "weighted_f1"),
                ("risk_category accuracy", "risk_category", "accuracy"),
                ("risk_category macro F1", "risk_category", "macro_f1"),
            ):
                out.append(f"| {name} | {_fmt(b[key][sub])} | {_fmt(g[key][sub])} |")
            out += ["", "### Per-class (change_type): precision / recall / F1", ""]
            out += [
                "| class | support | baseline P / R / F1 | Gemini P / R / F1 |",
                "|---|---|---|---|",
            ]
            for label in CHANGE_LABELS:
                gl = g["change_type"]["per_label"][label]
                bl = b["change_type"]["per_label"][label]
                support = gl["true_positive"] + gl["false_negative"]
                keys = ("precision", "recall", "f1")
                baseline_cell = " / ".join(_f1_cell(bl[key]) for key in keys)
                gemini_cell = " / ".join(_f1_cell(gl[key]) for key in keys)
                out.append(f"| {label} | {support} | {baseline_cell} | {gemini_cell} |")
            out += ["", "### Confusion matrix - Gemini (change_type)", ""]
            out += _confusion_table(g["change_type"]["confusion_matrix"], CHANGE_LABELS)
            out += ["", "### Confusion matrix - deterministic baseline (change_type)", ""]
            out += _confusion_table(b["change_type"]["confusion_matrix"], CHANGE_LABELS)
            out += ["", "### Gemini failure examples (change_type)", ""]
            failures = [
                item
                for item in results["tasks"][CHANGE_TASK]["items"].values()
                if _is_done(item)
                and (
                    (item["gemini"].get("prediction") or {}).get("change_type")
                    != item["expected"]["change_type"]
                )
            ]
            if not failures:
                out.append("_None._")
            for item in failures[:15]:
                prediction = item["gemini"].get("prediction") or {}
                out.append(
                    f"- `{item['id']}` expected **{item['expected']['change_type']}**, Gemini "
                    f"**{prediction.get('change_type', NO_PREDICTION)}** "
                    f"({item['gemini']['status']}), baseline "
                    f"**{item['baseline']['change_type']}**  "
                    f"\n  previous: {_snippet(item['input']['previous_text'])}  "
                    f"\n  current: {_snippet(item['input']['current_text'])}  "
                    f"\n  Gemini's reason: {_snippet(prediction.get('explanation'))}"
                )
            if len(failures) > 15:
                out.append(f"- … and {len(failures) - 15} more in the JSON results.")
            out.append("")

    claims = results["tasks"][CLAIM_TASK].get("metrics")
    if claims:
        out += ["## Financial-claim extraction", ""]
        out.append(
            f"Scored {claims['n_scored']} of {claims['n_total']} sentences. Provider status: "
            f"{claims.get('provider_status_counts')}."
        )
        out += [
            "",
            "Systems: **baseline** = the pipeline's deterministic extractor (metric-alias match + "
            "number parser) on its own; **Gemini** = the model on every sentence; **hybrid** = "
            "what the pipeline actually does (deterministic result if it found anything, else the "
            "model). Claim-type gold exists only for the three categories that name a type; "
            "`canonical_metric_accuracy` counts an item with no gold metric as correct only when "
            "no claim asserts a metric.",
            "",
        ]
        if claims["n_scored"]:
            systems = claims["systems"]
            out += ["| metric | baseline | Gemini | hybrid (pipeline) |", "|---|---|---|---|"]
            for name, key in (
                ("canonical_metric_accuracy", "canonical_metric_accuracy"),
                ("claim_type_accuracy (typed items)", "claim_type_accuracy"),
                ("exact match (1 claim, metric + type)", "exact_match_rate"),
                ("claim recall (items with a gold metric)", "claim_recall_on_items_with_a_metric"),
                (
                    "spurious-metric rate (items with no gold metric)",
                    "spurious_metric_rate_on_items_without_a_metric",
                ),
            ):
                out.append(
                    f"| {name} | {_fmt(systems['baseline'][key])} | "
                    f"{_fmt(systems['gemini'][key])} | {_fmt(systems['hybrid'][key])} |"
                )
            out += ["", "### Metric accuracy by category", ""]
            out += ["| category | baseline | Gemini | hybrid |", "|---|---|---|---|"]
            for category in systems["baseline"]["metric_accuracy_by_category"]:
                out.append(
                    f"| {category} | "
                    f"{_fmt(systems['baseline']['metric_accuracy_by_category'][category])} | "
                    f"{_fmt(systems['gemini']['metric_accuracy_by_category'][category])} | "
                    f"{_fmt(systems['hybrid']['metric_accuracy_by_category'][category])} |"
                )
            out += ["", "### Gemini failure examples", ""]
            shown = 0
            for item in results["tasks"][CLAIM_TASK]["items"].values():
                if not _is_done(item):
                    continue
                gemini_claims = item["gemini"].get("prediction") or []
                score = score_claim_item(
                    item["expected"]["canonical_metric"],
                    item["expected"]["claim_type"],
                    gemini_claims,
                )
                wrong = (not score["metric_correct"]) or score["claim_type_correct"] is False
                if not wrong:
                    continue
                shown += 1
                if shown > 15:
                    continue
                predicted = (
                    "; ".join(
                        f"{claim.get('canonical_metric_name')}/{claim.get('claim_type')}"
                        for claim in gemini_claims
                    )
                    or NO_PREDICTION
                )
                out.append(
                    f"- `{item['id']}` ({item['input']['category']}) "
                    f"\"{_snippet(item['input']['text'])}\" expected "
                    f"**{item['expected']['canonical_metric']}/{item['expected']['claim_type']}**, "
                    f"Gemini **{predicted}** ({item['gemini']['status']})"
                )
            if shown == 0:
                out.append("_None._")
            elif shown > 15:
                out.append(f"- … and {shown - 15} more in the JSON results.")
            out.append("")

    coverage = results["real_sec_claim_extraction"]
    out += [
        "## Real-SEC approved records",
        "",
        f"Status: **{coverage['status']}** - {coverage['approved_financial_claim_records']} "
        f"approved financial-claim record(s), {coverage['records_with_stored_input_text']} with "
        f"stored input text (of {coverage['approved_records_all_tasks']} approved records across "
        f"all tasks). {coverage['reason']}",
        "",
        "## Phase 4 metrics",
        "",
        "| metric | value | n | status |",
        "|---|---|---|---|",
    ]
    for key, value in results["phase4_metrics"].items():
        label = f"{key} ({value['system']})" if "system" in value else key
        out.append(
            f"| {label} | {_fmt(value) if value.get('status') == 'evaluated' else 'not evaluated'}"
            f" | {value.get('n')} | {value.get('status')} |"
        )
    out.append("")
    return "\n".join(out)
