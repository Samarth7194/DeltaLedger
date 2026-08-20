from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.evaluation.metrics import metric, no_data


def ai_call_monitoring(records: list[dict[str, Any]]) -> dict[str, object]:
    metadata = [_metadata(record) for record in records]
    metadata = [item for item in metadata if item]
    if not metadata:
        return {
            "ai_call_count": no_data("No inference metadata records were available."),
            "providers": {},
            "models": {},
            "quality_signals": human_feedback_quality_signals(records),
        }
    latencies = [
        float(item["latency_ms"])
        for item in metadata
        if isinstance(item.get("latency_ms"), int | float)
    ]
    failures = [item for item in metadata if item.get("success") is False]
    invalid = [item for item in metadata if item.get("parse_status") == "invalid"]
    total_tokens = [
        int(item["total_tokens"])
        for item in metadata
        if isinstance(item.get("total_tokens"), int)
    ]
    costs = [
        float(item["estimated_cost_usd"])
        for item in metadata
        if isinstance(item.get("estimated_cost_usd"), int | float)
    ]
    return {
        "ai_call_count": metric(len(metadata), n=len(metadata)),
        "failure_rate": metric(len(failures) / len(metadata), n=len(metadata)),
        "invalid_structured_output_rate": metric(len(invalid) / len(metadata), n=len(metadata)),
        "latency_ms": _latency_summary(latencies),
        "retry_count": sum(int(item.get("retry_count") or 0) for item in metadata),
        "token_usage": {
            "total_tokens": sum(total_tokens) if total_tokens else None,
            "tracked_calls": len(total_tokens),
        },
        "estimated_cost_usd": round(sum(costs), 8) if costs else None,
        "providers": _count_by(metadata, "provider"),
        "models": _count_by(metadata, "model"),
        "quality_signals": human_feedback_quality_signals(records),
    }


def human_feedback_quality_signals(records: list[dict[str, Any]]) -> dict[str, object]:
    statuses = Counter(
        str(record["review_status"])
        for record in records
        if record.get("review_status") not in {None, ""}
    )
    if not statuses:
        return {"review_outcomes": no_data("No human feedback status records were available.")}
    provider_rejections: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        metadata = _metadata(record)
        if not metadata or record.get("review_status") in {None, ""}:
            continue
        provider_rejections[str(metadata.get("model") or "unknown")][
            str(record["review_status"])
        ] += 1
    return {
        "review_outcomes": dict(sorted(statuses.items())),
        "by_model": {key: dict(value) for key, value in sorted(provider_rejections.items())},
    }


def _metadata(record: dict[str, Any]) -> dict[str, Any] | None:
    direct = record.get("inference_metadata")
    if isinstance(direct, dict):
        return direct
    original = record.get("original_model_output")
    if isinstance(original, dict) and isinstance(original.get("inference_metadata"), dict):
        return dict(original["inference_metadata"])
    return None


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(key) or "unknown") for row in rows).items()))


def _latency_summary(values: list[float]) -> dict[str, object]:
    if not values:
        return no_data("No latency metadata was available.")
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 3),
        "p50": round(_percentile(ordered, 0.50), 3),
        "p95": round(_percentile(ordered, 0.95), 3),
        "max": round(ordered[-1], 3),
        "n": len(ordered),
        "status": "evaluated",
    }


def _percentile(values: list[float], percentile: float) -> float:
    index = min(len(values) - 1, max(0, round((len(values) - 1) * percentile)))
    return values[index]
