"""Small real-provider canary for the multi-item classification request.

Sends exactly ONE multi-item request (no retries, no repair request) built from
2-3 synthetic disclosure pairs - no database, no filings, no analysis run -
through the same code path the analysis uses, and reports only a safe summary:

* whether every requested item_id came back exactly once (mapping check),
* whether each item validated against the real response schema,
* the provider-reported token usage (null when the provider reports none),
* on failure, the error class/category/subtype (never headers, keys, prompts).

Run from the backend directory (it reads backend/.env):

    cd backend
    python ../scripts/gemini_multi_item_canary.py --items 3

`--dry-run` builds and describes the request without contacting the provider.
Exit code 0 only if every item was returned once and validated.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.ai.batching import canonical_hash, item_request_id  # noqa: E402
from app.ai.inference import collect_usage  # noqa: E402
from app.ai.openai_compatible import ProviderRequestError  # noqa: E402
from app.ai.semantic_change import (  # noqa: E402
    ChangeClassificationRequest,
    change_request_tokens,
)

ALLOWED_LABELS = ["added", "removed", "strengthened", "weakened", "no_material_change"]

# (previous, current, label a careful reader would most plausibly choose).
# The expectation is informational only - the canary checks mapping and schema,
# not model judgement.
SAMPLE_PAIRS = [
    (
        "We believe our existing cash and cash equivalents will be sufficient to meet our "
        "liquidity needs for at least the next twelve months.",
        "We may need to raise additional capital, and there can be no assurance that financing "
        "will be available on acceptable terms if our cash proves insufficient.",
        "weakened",
    ),
    (
        "We may be subject to litigation, and the outcome of any proceeding is uncertain.",
        "We are not currently party to any material legal proceedings.",
        "strengthened",
    ),
    (
        "Our fiscal year ends on the last Saturday of September.",
        "The Company's fiscal year ends on the last Saturday in September.",
        "no_material_change",
    ),
]


def build_items(count: int) -> list[tuple[str, ChangeClassificationRequest, str]]:
    items = []
    for index, (previous, current, expected) in enumerate(SAMPLE_PAIRS[:count]):
        request = ChangeClassificationRequest(
            previous_text=previous,
            current_text=current,
            deterministic_signals={},
            section_metadata={"section_type": "canary", "section_title": f"Canary item {index}"},
            allowed_labels=list(ALLOWED_LABELS),
        )
        item_id = item_request_id(canonical_hash([index, previous, current]))
        items.append((item_id, request, expected))
    return items


async def run_canary(classifier, count: int) -> dict[str, object]:
    """Send one multi-item request and summarise it. Never raises for a
    provider failure - the failure is part of the summary."""
    items = build_items(count)
    requested = [item_id for item_id, _, _ in items]
    summary: dict[str, object] = {
        "model": classifier.model_name,
        "batch_prompt_version": getattr(classifier, "batch_prompt_version", None),
        "items_requested": len(items),
        "estimated_input_tokens": (
            getattr(classifier, "batch_fixed_overhead_tokens", 0)
            + sum(change_request_tokens(request) for _, request, _ in items)
        ),
    }
    started = time.perf_counter()
    try:
        with collect_usage() as usage:
            outcomes = await classifier.classify_batch([(i, r) for i, r, _ in items])
    except ProviderRequestError as exc:
        summary.update(
            ok=False,
            error={
                "type": "ProviderRequestError",
                "category": exc.error_category,
                "subtype": exc.error_subtype,
                "status_code": exc.status_code,
                "retry_after_seconds": exc.retry_after_seconds,
                "retryable": exc.is_retryable,
            },
            actual_usage=None,
        )
        return summary
    except Exception as exc:  # unexpected: report the class only
        summary.update(ok=False, error={"type": exc.__class__.__name__}, actual_usage=None)
        return summary

    per_item = []
    for item_id, _request, expected in items:
        result = outcomes.get(item_id)
        per_item.append(
            {
                "item_id": item_id,
                "returned": item_id in outcomes,
                "valid": result is not None,
                "change_type": result.change_type if result else None,
                "risk_category": result.risk_category if result else None,
                "confidence": result.confidence if result else None,
                "expected_label_informational": expected,
            }
        )
    unexpected_ids = sorted(set(outcomes) - set(requested))
    all_valid = all(entry["valid"] for entry in per_item)
    summary.update(
        ok=all_valid and not unexpected_ids and len(outcomes) == len(items),
        latency_seconds=round(time.perf_counter() - started, 2),
        items=per_item,
        unexpected_item_ids=unexpected_ids,
        requests_sent=usage.requests,
        actual_usage={
            # None means the provider reported nothing - never an estimate.
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.resolved_total(),
            "requests_reporting_usage": usage.requests_reporting_usage,
        },
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--items", type=int, choices=(2, 3), default=3)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="describe the request without contacting the provider",
    )
    args = parser.parse_args(argv)

    from app.ai.semantic_change import OpenAICompatibleChangeClassifier
    from app.core.config import get_settings

    # The canary must be exactly ONE provider request: no retry storm on a 429
    # and no hidden repair request that would mask a malformed response.
    settings = get_settings().model_copy(
        update={"ai_provider_max_retries": 1, "ai_provider_structured_output_repair_attempts": 0}
    )
    if args.dry_run:
        items = build_items(args.items)
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "model": settings.change_classifier_model,
                    "items": len(items),
                    "max_provider_requests": 1,
                    "estimated_item_tokens": sum(
                        change_request_tokens(request) for _, request, _ in items
                    ),
                },
                indent=2,
            )
        )
        return 0
    classifier = OpenAICompatibleChangeClassifier(settings)
    summary = asyncio.run(run_canary(classifier, args.items))
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
