from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class InferenceMetadata(BaseModel):
    provider: str
    provider_type: str
    model: str
    model_version: str | None = None
    prompt_version: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    latency_ms: float | None = None
    success: bool
    parse_status: str
    retry_count: int = 0
    error_type: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None


def metadata_from_usage(
    *,
    provider: str,
    provider_type: str,
    model: str,
    model_version: str | None,
    prompt_version: str | None,
    latency_ms: float,
    success: bool,
    parse_status: str,
    retry_count: int,
    usage: dict[str, Any] | None,
    input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
    error_type: str | None = None,
) -> InferenceMetadata:
    input_tokens = _int_or_none((usage or {}).get("prompt_tokens"))
    output_tokens = _int_or_none((usage or {}).get("completion_tokens"))
    total_tokens = _int_or_none((usage or {}).get("total_tokens"))
    return InferenceMetadata(
        provider=provider,
        provider_type=provider_type,
        model=model,
        model_version=model_version,
        prompt_version=prompt_version,
        latency_ms=round(latency_ms, 3),
        success=success,
        parse_status=parse_status,
        retry_count=retry_count,
        error_type=error_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=_estimated_cost(
            input_tokens,
            output_tokens,
            input_cost_per_million,
            output_cost_per_million,
        ),
    )


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _estimated_cost(
    input_tokens: int | None,
    output_tokens: int | None,
    input_cost_per_million: float | None,
    output_cost_per_million: float | None,
) -> float | None:
    if (
        input_tokens is None
        or output_tokens is None
        or input_cost_per_million is None
        or output_cost_per_million is None
    ):
        return None
    return round(
        (input_tokens / 1_000_000) * input_cost_per_million
        + (output_tokens / 1_000_000) * output_cost_per_million,
        8,
    )
