from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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


@dataclass
class UsageTotals:
    """Provider-reported token usage summed over the requests made inside a
    `collect_usage()` block.

    Only values the provider actually reported are summed. A field stays None
    (never 0, never an estimate) when no request reported it, so "unknown" is
    distinguishable from "zero".
    """

    requests: int = 0
    requests_reporting_usage: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def add(self, usage: dict[str, Any] | None) -> None:
        self.requests += 1
        if not isinstance(usage, dict):
            return
        input_tokens = _int_or_none(usage.get("prompt_tokens"))
        output_tokens = _int_or_none(usage.get("completion_tokens"))
        total_tokens = _int_or_none(usage.get("total_tokens"))
        if input_tokens is None and output_tokens is None and total_tokens is None:
            return
        self.requests_reporting_usage += 1
        self.input_tokens = _add_optional(self.input_tokens, input_tokens)
        self.output_tokens = _add_optional(self.output_tokens, output_tokens)
        self.total_tokens = _add_optional(self.total_tokens, total_tokens)

    def resolved_total(self) -> int | None:
        """Reported total, else input + output when both were reported."""
        if self.total_tokens is not None:
            return self.total_tokens
        if self.input_tokens is not None and self.output_tokens is not None:
            return self.input_tokens + self.output_tokens
        return None


_usage_collector: ContextVar[UsageTotals | None] = ContextVar("usage_collector", default=None)


@contextmanager
def collect_usage() -> Iterator[UsageTotals]:
    """Collect provider-reported token usage of every chat request made (in
    this task) while the block is active - including repair attempts and
    requests whose output later failed validation, since those cost tokens too.
    """
    totals = UsageTotals()
    token = _usage_collector.set(totals)
    try:
        yield totals
    finally:
        _usage_collector.reset(token)


def record_usage(usage: dict[str, Any] | None) -> None:
    totals = _usage_collector.get()
    if totals is not None:
        totals.add(usage)


def _add_optional(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return value if current is None else current + value


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
