"""Concise, uniform log lines for the durable batches of an AI stage.

    Disclosure classification: part 4 / 17 started | items=8 estimated_input_tokens=7,842
    Disclosure classification: part 4 / 17 completed | provider_calls=1 actual_input_tokens=7,390
    Disclosure classification: part 1 / 17 skipped (already completed)
    Disclosure classification: part 3 / 17 resumed (previous attempt was interrupted; retry 1)
    Disclosure classification: part 5 / 17 failed | error=rate_limited_short_term retry_after=21s

Only counts, ids and error types - never filing text, prompts or responses.
"""

from __future__ import annotations

import logging
from typing import Any


def _format(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def log_batch_event(
    logger: logging.Logger,
    *,
    stage_label: str,
    index: int,
    total: int,
    event: str,
    level: int = logging.INFO,
    scope: str | None = None,
    **details: Any,
) -> None:
    """One line per part event. Detail values that are None are omitted (an
    unreported token count is simply not shown, never shown as 0)."""
    shown = " ".join(
        f"{key}={_format(value)}" for key, value in details.items() if value is not None
    )
    message = f"{stage_label}: part {index} / {total} {event}"
    if shown:
        message += f" | {shown}"
    if scope:
        message += f" [{scope}]"
    logger.log(level, message)


def describe_attempt(status: str | None, retry_count: int) -> tuple[str, str]:
    """(event, note) for a part about to run, from its persisted status: a part
    left `processing` or `failed` by an earlier attempt is *resumed*."""
    if status == "processing":
        return "resumed", f"previous attempt was interrupted; retry {retry_count + 1}"
    if status == "failed":
        return "resumed", f"previous attempt failed; retry {retry_count + 1}"
    return "started", ""
