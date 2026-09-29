"""Startup/runtime configuration reporting (no secrets), uniform batch log lines,
and the doctor's migration-head awareness."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from app.cli import production_doctor
from app.core.config import Settings
from app.core.runtime_report import (
    log_runtime_config,
    prompt_versions,
    runtime_notes,
    runtime_summary,
)
from app.services.batch_logging import describe_attempt, log_batch_event
from tests.test_comparison_batch_resume import _FailOnNthBatchClassifier, _Scenario
from tests.test_disclosure_batch_classification import _ScriptedClassifier

SECRETS = ("s3cretpassword", "sk-live-api-key", "hf_secret_token", "minio-secret-key")


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, app_profile="local-cloud", environment="local", **overrides)


def _secretive_settings(**overrides) -> Settings:
    return _settings(
        database_url="postgresql+asyncpg://dbuser:s3cretpassword@ep-host.example.com:5432/appdb",
        redis_url="redis://:s3cretpassword@redis.example.com:6379/0",
        ai_provider_api_key="sk-live-api-key",
        hf_token="hf_secret_token",
        **overrides,
    )


# --- runtime summary ----------------------------------------------------------------------------


def test_the_runtime_summary_contains_no_credentials() -> None:
    summary = runtime_summary(_secretive_settings(), "worker")
    dumped = json.dumps(summary, default=str)

    for secret in SECRETS:
        assert secret not in dumped
    assert "dbuser" not in dumped
    assert summary["database_host"] == "ep-host.example.com:5432"
    assert summary["database_name"] == "appdb"
    assert summary["redis_host"] == "redis.example.com:6379"
    assert summary["ai_provider_api_key_configured"] is True  # a boolean, never the key


def test_the_summary_reports_the_batching_and_limit_values_operators_need() -> None:
    summary = runtime_summary(
        _settings(
            ai_batch_max_items=8,
            ai_batch_input_token_budget=12000,
            ai_batch_token_safety_margin=0.25,
            analysis_workflow_time_limit_seconds=10800,
            workflow_checkpoint_provider="postgres",
        ),
        "api",
    )

    assert summary["embedding_model"] == "BAAI/bge-large-en-v1.5"
    assert summary["batch_input_token_budget"] == 12000
    assert summary["batch_effective_budget"] == 9000
    assert summary["batch_max_items"] == 8
    assert summary["analysis_workflow_limit_seconds"] == 10800
    assert summary["checkpoint_provider"] == "postgres"
    assert summary["role"] == "api"


def test_api_and_worker_fingerprints_match_only_when_configuration_matches() -> None:
    same_api = runtime_summary(_settings(), "api")["config_fingerprint"]
    same_worker = runtime_summary(_settings(), "worker")["config_fingerprint"]
    other = runtime_summary(_settings(ai_batch_max_items=4), "worker")["config_fingerprint"]
    other_model = runtime_summary(_settings(embedding_provider="local"), "worker")[
        "config_fingerprint"
    ]

    assert same_api == same_worker  # role does not change the fingerprint
    assert len({same_api, other, other_model}) == 3


def test_real_provider_prompt_versions_are_reported() -> None:
    versions = prompt_versions(
        _settings(
            change_classifier_provider="openai_compatible",
            claim_extractor_provider="openai_compatible",
            ai_provider_api_key="k",
        )
    )

    disclosure = versions["disclosure_classification_batch"]
    claims = versions["claim_extraction_batch"]
    assert disclosure.startswith("disclosure-change-batch-json-v1+")
    assert claims.startswith("financial-claim-extraction-batch-json-v1+")
    assert prompt_versions(_settings()) == {}  # fake providers stamp none


class _CapturingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def info(self, event, **kw):
        self.events.append(("info", event, kw))

    def warning(self, event, **kw):
        self.events.append(("warning", event, kw))

    def error(self, event, **kw):
        self.events.append(("error", event, kw))


def test_startup_logging_emits_the_summary_and_never_a_secret() -> None:
    logger = _CapturingLogger()

    log_runtime_config(_secretive_settings(), "worker", logger)

    assert logger.events[0][1] == "runtime_config"
    dumped = json.dumps(logger.events, default=str)
    for secret in SECRETS:
        assert secret not in dumped


# --- configuration problems ---------------------------------------------------------------------


def _fake(**overrides) -> SimpleNamespace:
    base = {
        "change_classifier_provider": "fake",
        "claim_extractor_provider": "fake",
        "ai_provider_api_key": None,
        "analysis_workflow_time_limit_seconds": 10800.0,
        "worker_default_time_limit_seconds": 1800.0,
        "workflow_checkpoint_provider": "postgres",
        "is_production": False,
        "database_url": "postgresql+asyncpg://u:p@db.example.com/x",
        "redis_url": "redis://r.example.com:6379/0",
        "object_storage_provider": "minio",
        "embedding_provider": "local",
    }
    return SimpleNamespace(**{**base, **overrides})


def test_a_consistent_configuration_has_no_notes() -> None:
    assert runtime_notes(_fake(), "worker") == []


@pytest.mark.parametrize(
    ("overrides", "level", "fragment"),
    [
        ({"change_classifier_provider": "openai_compatible"}, "error", "AI_PROVIDER_API_KEY"),
        (
            {"analysis_workflow_time_limit_seconds": 900.0},
            "warning",
            "ANALYSIS_WORKFLOW_TIME_LIMIT_SECONDS",
        ),
        ({"workflow_checkpoint_provider": "memory"}, "warning", "checkpoints"),
        (
            {"is_production": True, "database_url": "postgresql://u:p@localhost/x"},
            "error",
            "DATABASE_URL",
        ),
        (
            {"is_production": True, "redis_url": "redis://localhost:6379/0"},
            "error",
            "REDIS_URL",
        ),
        (
            {"object_storage_provider": "filesystem"},
            "warning",
            "filesystem object storage",
        ),
    ],
)
def test_runtime_notes_flag_problems_that_would_only_surface_mid_run(
    overrides, level, fragment
) -> None:
    notes = runtime_notes(_fake(**overrides), "worker")

    assert any(n.level == level and fragment in n.message for n in notes), notes


# --- uniform part log lines -----------------------------------------------------------------------


def test_part_log_lines_are_concise_and_omit_unreported_values(caplog) -> None:
    logger = logging.getLogger("test.batch")
    with caplog.at_level(logging.INFO, logger="test.batch"):
        log_batch_event(
            logger,
            stage_label="Disclosure classification",
            index=4,
            total=17,
            event="started",
            items=8,
            estimated_input_tokens=7842,
        )
        log_batch_event(
            logger,
            stage_label="Disclosure classification",
            index=4,
            total=17,
            event="completed",
            provider_calls=1,
            actual_input_tokens=7390,
            actual_output_tokens=None,  # provider reported none: not shown as 0
        )

    lines = [record.getMessage() for record in caplog.records]
    assert lines[0] == (
        "Disclosure classification: part 4 / 17 started | items=8 estimated_input_tokens=7,842"
    )
    assert lines[1] == (
        "Disclosure classification: part 4 / 17 completed | provider_calls=1 "
        "actual_input_tokens=7,390"
    )


def test_attempt_descriptions_distinguish_fresh_from_resumed() -> None:
    assert describe_attempt("pending", 0) == ("started", "")
    assert describe_attempt(None, 0) == ("started", "")
    assert describe_attempt("processing", 0)[0] == "resumed"
    assert "retry 3" in describe_attempt("failed", 2)[1]


@pytest.mark.asyncio
async def test_a_resumed_run_logs_skipped_and_resumed_parts_without_any_filing_text(
    caplog,
) -> None:
    scenario = _Scenario(model_pairs=6, max_items=2)  # 3 parts
    with caplog.at_level(logging.INFO):
        with pytest.raises(Exception):  # noqa: B017 - the scripted rate limit
            await scenario.run(_FailOnNthBatchClassifier(fail_on=2))
        caplog.clear()
        await scenario.run(_ScriptedClassifier())

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "Disclosure classification: part 1 / 3 skipped (already completed" in text
    assert "part 2 / 3 resumed (previous attempt failed; retry 1)" in text
    assert "Disclosure classification: part 3 / 3 started" in text
    assert "Disclosure classification: part 2 / 3 completed | provider_calls=1" in text
    assert "reusing persisted matching" in text
    # Counts and ids only: never passage text, prompts or model output.
    for leaked in ("resilient", "weaken materially", "We expect"):
        assert leaked not in text


@pytest.mark.asyncio
async def test_a_failed_part_is_logged_with_its_error_type_and_kept_parts(caplog) -> None:
    scenario = _Scenario(model_pairs=6, max_items=2)
    with caplog.at_level(logging.INFO):
        with pytest.raises(Exception):  # noqa: B017
            await scenario.run(_FailOnNthBatchClassifier(fail_on=2))

    failed = [r.getMessage() for r in caplog.records if "failed |" in r.getMessage()]
    assert failed and "part 2 / 3 failed" in failed[0]
    assert "error=rate_limited" in failed[0] and "completed_parts_kept=1" in failed[0]


# --- doctor ------------------------------------------------------------------------------


def test_the_doctor_expects_the_actual_migration_head_and_the_batch_table() -> None:
    assert production_doctor._expected_alembic_head() == "0008_stale_run_recovery"
    assert "analysis_stage_batches" in production_doctor.EXPECTED_TABLES


def test_the_doctor_runtime_check_is_credential_free() -> None:
    check = production_doctor._runtime_check(_secretive_settings())

    dumped = json.dumps(check.as_dict(), default=str)
    for secret in SECRETS:
        assert secret not in dumped
    assert check.name == "runtime" and check.metadata["batch_effective_budget"] == 9000


def test_the_worker_logs_its_runtime_configuration_at_boot() -> None:
    from app.workers import tasks

    assert any(isinstance(m, tasks._RuntimeConfigLogger) for m in tasks.broker.middleware)
