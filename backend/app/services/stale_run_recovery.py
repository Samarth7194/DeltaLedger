"""When an in-progress analysis run counts as stale (its worker likely died).

A run is stale when all three hold:

1. its status is still in-progress (not a terminal status, and not
   ``awaiting_human_review`` - that one is a deliberate pause for a human,
   not a stuck worker);
2. its heartbeat (``analysis_runs.last_heartbeat_at``, touched at every node
   boundary and every stage-batch transition - see
   ``WorkflowRepository.set_run_status`` and ``StageBatchRepository``) has not
   been renewed for at least ``STALE_RUN_HEARTBEAT_THRESHOLD_SECONDS``;
3. its Postgres advisory lock is not currently held.

The third condition needs a database round trip
(``app.db.session.is_advisory_lock_free``), so it is deliberately not part of
this module: everything here is a pure, DB-free predicate over already-loaded
values, easy to unit test and safe to call from a response-building path.
Callers that are about to act on staleness (the retry endpoint) must still
check the lock themselves, right before acting, to avoid a race against a
worker that reacquires it.
"""

from __future__ import annotations

from datetime import datetime

from app.db.models.workflow import ANALYSIS_STATUSES

# Every status except a terminal outcome or a deliberate human-review pause.
STALE_ELIGIBLE_STATUSES: frozenset[str] = frozenset(ANALYSIS_STATUSES) - {
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
    "awaiting_human_review",
}


def is_stale_by_heartbeat(
    *,
    status: str,
    last_heartbeat_at: datetime | None,
    started_at: datetime | None,
    created_at: datetime | None,
    now: datetime,
    threshold_seconds: float,
) -> bool:
    """True if `status` is stale-eligible and its heartbeat is older than
    `threshold_seconds` (or it never had one - a run whose worker died before
    the first heartbeat touch is exactly as stale as one whose worker died
    later). Falls back to `started_at`, then `created_at`, for a run that
    predates the heartbeat column."""
    if status not in STALE_ELIGIBLE_STATUSES:
        return False
    reference = last_heartbeat_at or started_at or created_at
    if reference is None:
        return True
    age_seconds = (now - reference).total_seconds()
    return age_seconds >= threshold_seconds
