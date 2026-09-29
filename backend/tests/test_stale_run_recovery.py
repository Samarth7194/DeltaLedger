"""Pure predicate: when is an in-progress run stale (its worker likely died)?

No database: `is_stale_by_heartbeat` only looks at already-loaded values. The
advisory-lock half of "stale" (is anyone actually still holding it right now)
is DB-backed and covered separately (test_db_session_lock.py for the helper,
and the Postgres integration test for the end-to-end recovery)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.workflow import ANALYSIS_STATUSES
from app.services.stale_run_recovery import STALE_ELIGIBLE_STATUSES, is_stale_by_heartbeat

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
THRESHOLD = 600.0


def _stale(status: str, *, heartbeat_age_seconds: float | None, **overrides) -> bool:
    last_heartbeat_at = (
        NOW - timedelta(seconds=heartbeat_age_seconds)
        if heartbeat_age_seconds is not None
        else None
    )
    kwargs = {
        "status": status,
        "last_heartbeat_at": last_heartbeat_at,
        "started_at": None,
        "created_at": None,
        "now": NOW,
        "threshold_seconds": THRESHOLD,
        **overrides,
    }
    return is_stale_by_heartbeat(**kwargs)


def test_every_status_is_classified_as_either_eligible_or_not_with_no_overlap() -> None:
    terminal_or_review = {
        "completed",
        "completed_with_warnings",
        "failed",
        "cancelled",
        "awaiting_human_review",
    }
    assert STALE_ELIGIBLE_STATUSES == set(ANALYSIS_STATUSES) - terminal_or_review
    assert STALE_ELIGIBLE_STATUSES.isdisjoint(terminal_or_review)
    assert STALE_ELIGIBLE_STATUSES | terminal_or_review == set(ANALYSIS_STATUSES)


@pytest.mark.parametrize("status", sorted(STALE_ELIGIBLE_STATUSES))
def test_an_eligible_status_with_a_fresh_heartbeat_is_not_stale(status: str) -> None:
    assert _stale(status, heartbeat_age_seconds=1.0) is False


@pytest.mark.parametrize("status", sorted(STALE_ELIGIBLE_STATUSES))
def test_an_eligible_status_with_an_old_heartbeat_is_stale(status: str) -> None:
    assert _stale(status, heartbeat_age_seconds=THRESHOLD + 1) is True


@pytest.mark.parametrize(
    "status",
    ["completed", "completed_with_warnings", "failed", "cancelled", "awaiting_human_review"],
)
def test_a_terminal_or_review_status_is_never_stale_no_matter_how_old_the_heartbeat(
    status: str,
) -> None:
    assert _stale(status, heartbeat_age_seconds=THRESHOLD * 1000) is False
    assert _stale(status, heartbeat_age_seconds=None) is False


def test_right_at_the_threshold_counts_as_stale_not_one_second_before() -> None:
    status = next(iter(STALE_ELIGIBLE_STATUSES))
    assert _stale(status, heartbeat_age_seconds=THRESHOLD) is True
    assert _stale(status, heartbeat_age_seconds=THRESHOLD - 1) is False


def test_a_missing_heartbeat_falls_back_to_started_at() -> None:
    status = next(iter(STALE_ELIGIBLE_STATUSES))
    fresh_start = NOW - timedelta(seconds=1)
    old_start = NOW - timedelta(seconds=THRESHOLD + 1)

    assert is_stale_by_heartbeat(
        status=status,
        last_heartbeat_at=None,
        started_at=fresh_start,
        created_at=None,
        now=NOW,
        threshold_seconds=THRESHOLD,
    ) is False
    assert is_stale_by_heartbeat(
        status=status,
        last_heartbeat_at=None,
        started_at=old_start,
        created_at=None,
        now=NOW,
        threshold_seconds=THRESHOLD,
    ) is True


def test_a_missing_heartbeat_and_started_at_falls_back_to_created_at() -> None:
    status = next(iter(STALE_ELIGIBLE_STATUSES))

    assert is_stale_by_heartbeat(
        status=status,
        last_heartbeat_at=None,
        started_at=None,
        created_at=NOW - timedelta(seconds=1),
        now=NOW,
        threshold_seconds=THRESHOLD,
    ) is False
    assert is_stale_by_heartbeat(
        status=status,
        last_heartbeat_at=None,
        started_at=None,
        created_at=NOW - timedelta(seconds=THRESHOLD + 1),
        now=NOW,
        threshold_seconds=THRESHOLD,
    ) is True


def test_a_run_with_no_timestamps_at_all_is_treated_as_stale() -> None:
    # A run whose worker died before its very first heartbeat touch is exactly
    # as stale as one whose worker died later - it is never "not stale" just
    # because nothing was ever recorded.
    status = next(iter(STALE_ELIGIBLE_STATUSES))
    assert is_stale_by_heartbeat(
        status=status,
        last_heartbeat_at=None,
        started_at=None,
        created_at=None,
        now=NOW,
        threshold_seconds=THRESHOLD,
    ) is True


def test_last_heartbeat_at_wins_over_an_older_started_at_and_created_at() -> None:
    status = next(iter(STALE_ELIGIBLE_STATUSES))
    assert is_stale_by_heartbeat(
        status=status,
        last_heartbeat_at=NOW - timedelta(seconds=1),  # fresh: a batch just completed
        started_at=NOW - timedelta(days=1),  # the run itself started a day ago
        created_at=NOW - timedelta(days=2),
        now=NOW,
        threshold_seconds=THRESHOLD,
    ) is False
