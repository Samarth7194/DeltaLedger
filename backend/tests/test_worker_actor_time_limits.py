from __future__ import annotations

from app.core.config import get_settings
from app.workers import tasks

SHORT_TASK_ACTORS = [
    tasks.process_filing_task,
    tasks.process_comparison_task,
    tasks.extract_financial_claims_task,
    tasks.verify_financial_claim_task,
    tasks.verify_comparison_financials_task,
    tasks.analyze_contradictions_for_comparison,
]

LONG_RUNNING_ANALYSIS_ACTORS = [
    tasks.run_analysis_workflow_task,
    tasks.resume_analysis_workflow_task,
]


def test_analysis_workflow_actors_use_the_long_running_time_limit() -> None:
    settings = get_settings()
    expected_ms = int(settings.analysis_workflow_time_limit_seconds * 1000)

    for actor in LONG_RUNNING_ANALYSIS_ACTORS:
        assert actor.options["time_limit"] == expected_ms
        assert actor.options["max_retries"] == 1


def test_short_tasks_keep_the_default_worker_time_limit_not_the_long_one() -> None:
    settings = get_settings()
    expected_ms = int(settings.worker_default_time_limit_seconds * 1000)
    long_running_ms = int(settings.analysis_workflow_time_limit_seconds * 1000)

    for actor in SHORT_TASK_ACTORS:
        assert actor.options["time_limit"] == expected_ms
        assert actor.options["time_limit"] != long_running_ms
        assert actor.options["max_retries"] == 3


def test_analysis_workflow_time_limit_is_meaningfully_longer_than_default() -> None:
    """Guards against the actual regression this fixes: previously both used
    the same hard-coded 60-minute limit, which killed real multi-stage runs
    mid-classification."""
    settings = get_settings()

    assert (
        settings.analysis_workflow_time_limit_seconds > settings.worker_default_time_limit_seconds
    )
    # The specific real-world failure this fixes: a full run needed at least
    # ~48 minutes for disclosure classification alone (observed), on top of
    # BGE processing and every later workflow stage. One hour is not enough.
    assert settings.analysis_workflow_time_limit_seconds > 60 * 60
