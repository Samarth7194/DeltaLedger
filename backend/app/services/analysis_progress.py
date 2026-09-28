"""Per-stage progress of an analysis run, derived from real persisted state.

Nothing here is time-based: a batched stage reports how many of its durable
batches ("parts") are completed out of the total, plus the item accounting and
token usage recorded with them; every other stage reports only its status from
the workflow node it maps to.

Statuses: ``pending``, ``processing``, ``completed``, ``failed`` (with a
``retryable`` flag saying whether running again can help) and
``requires_review`` (the stage finished, but some source items could not be
analysed and need an analyst).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.ai.batching import BatchingConfig
from app.db.models.workflow import (
    BATCH_STAGE_DISCLOSURE_COMPARISON,
    BATCH_STAGE_FINANCIAL_CLAIMS,
)
from app.repositories.stage_batch_repository import (
    PartProgress,
    StageProgress,
    is_retryable_error_type,
)


@dataclass(frozen=True)
class _StageDefinition:
    key: str
    label: str
    node: str
    batch_stage: str | None = None


STAGES = (
    _StageDefinition(
        "disclosure_comparison",
        "Disclosure Classification",
        "run_disclosure_comparison",
        BATCH_STAGE_DISCLOSURE_COMPARISON,
    ),
    _StageDefinition(
        "financial_claims",
        "Financial Claims",
        "extract_financial_claims",
        BATCH_STAGE_FINANCIAL_CLAIMS,
    ),
    _StageDefinition("xbrl_verification", "XBRL Verification", "verify_financial_claims"),
    _StageDefinition("contradiction_analysis", "Contradiction Analysis", "analyze_contradictions"),
    _StageDefinition("human_review", "Human Review", "review_gate"),
    _StageDefinition("final_report", "Final Report", "generate_report"),
)


def build_stage_progress(
    *,
    completed_nodes: Sequence[str],
    current_node: str | None,
    run_status: str,
    failure_node: str | None,
    batches: Mapping[str, StageProgress],
    failure_code: str | None = None,
    batching: BatchingConfig | None = None,
) -> list[dict[str, object]]:
    """One entry per stage, in workflow order.

    `completed_units` / `total_units` are batch counts for a batched stage
    (`total_units` is None until its plan exists) and None for the rest.
    `batching` supplies the configured per-request input budget (and the
    effective budget after the safety margin) - our own planning limits, not
    the provider's quota, which is not known.
    """
    stages: list[dict[str, object]] = []
    for definition in STAGES:
        node_done = definition.node in completed_nodes
        node_running = current_node == definition.node and run_status not in {
            "failed",
            "cancelled",
        }
        node_failed = run_status == "failed" and failure_node == definition.node
        progress = batches.get(definition.batch_stage) if definition.batch_stage else None
        part_failed = progress is not None and progress.failed > 0

        if node_failed:
            # The node that just failed wins over a stale "completed" entry
            # left by an earlier attempt.
            status = "failed"
        elif node_done:
            status = "completed"
        elif part_failed and not node_running:
            status = "failed"
        elif node_running or (progress is not None and (progress.processing or progress.completed)):
            status = "processing"
        else:
            status = "pending"
        if part_failed and status != "completed":
            status = "failed"
        # Finished, but some items were never analysed: say so instead of
        # presenting the stage as cleanly complete.
        if (
            progress is not None
            and progress.requires_review_items > 0
            and status == "completed"
        ):
            status = "requires_review"

        entry: dict[str, object] = {
            "stage": definition.key,
            "label": definition.label,
            "status": status,
            "batched": definition.batch_stage is not None,
            "retryable": None,
            "completed_units": None,
            "total_units": None,
            "current_unit": None,
            "unit_label": None,
            "provider_calls": None,
            "retries": None,
            "estimated_input_tokens": None,
            "actual_input_tokens": None,
            "actual_output_tokens": None,
            "actual_total_tokens": None,
            "configured_input_budget": None,
            "effective_input_budget": None,
            "successful_items": None,
            "zero_result_items": None,
            "requires_review_items": None,
            "last_provider_error_type": None,
            "retry_after_seconds": None,
            "last_provider_error_at": None,
            "parts": [],
        }
        if status == "failed":
            error_type = progress.last_provider_error_type if progress else None
            entry["retryable"] = is_retryable_error_type(error_type or failure_code)
        if progress is not None:
            entry.update(
                completed_units=progress.completed,
                total_units=progress.total,
                current_unit=progress.current_batch if status != "completed" else None,
                unit_label="parts",
                provider_calls=progress.provider_calls,
                retries=progress.retries,
                estimated_input_tokens=progress.estimated_input_tokens,
                actual_input_tokens=progress.actual_input_tokens,
                actual_output_tokens=progress.actual_output_tokens,
                actual_total_tokens=progress.actual_total_tokens,
                successful_items=progress.successful_items,
                zero_result_items=progress.zero_result_items,
                requires_review_items=progress.requires_review_items,
                last_provider_error_type=(
                    progress.last_provider_error_type if part_failed else None
                ),
                retry_after_seconds=progress.last_retry_after_seconds if part_failed else None,
                last_provider_error_at=progress.last_provider_error_at if part_failed else None,
                parts=[_part(part) for part in progress.parts],
            )
        if definition.batch_stage is not None and batching is not None:
            entry["configured_input_budget"] = batching.input_token_budget
            entry["effective_input_budget"] = batching.effective_token_budget
        stages.append(entry)
    return stages


def current_stage_fraction(stages: Sequence[Mapping[str, object]]) -> float:
    """Completed fraction (0..1) of the batched stage currently processing,
    from real batch counts; 0 when no batched stage is in flight."""
    for stage in stages:
        if stage["status"] == "processing" and stage["batched"]:
            total = stage["total_units"]
            completed = stage["completed_units"]
            if isinstance(total, int) and total > 0 and isinstance(completed, int):
                return min(completed / total, 1.0)
    return 0.0


def _part(part: PartProgress) -> dict[str, object]:
    return {
        "index": part.index,
        "status": part.status,
        "item_count": part.item_count,
        "estimated_input_tokens": part.estimated_input_tokens,
        "actual_input_tokens": part.actual_input_tokens,
        "actual_output_tokens": part.actual_output_tokens,
        "actual_total_tokens": part.actual_total_tokens,
        "provider_calls": part.provider_calls,
        "retry_count": part.retry_count,
        "successful_items": part.successful_items,
        "zero_result_items": part.zero_result_items,
        "requires_review_items": part.requires_review_items,
        "last_provider_error_type": part.last_provider_error_type,
        "retry_after_seconds": part.last_retry_after_seconds,
        "last_provider_error_at": part.last_provider_error_at,
    }
