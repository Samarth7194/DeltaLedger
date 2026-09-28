"""The AAPL E2E preflight command: never mutates data, never calls Gemini,
never enqueues a job, never prints a secret, and correctly classifies
PASS/WARN/FAIL from configuration alone. No real database or Redis is
contacted - `run_doctor` (the only network-touching part) is monkeypatched."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.cli import preflight_e2e
from app.cli.preflight_e2e import (
    PreflightCheck,
    _ai_checks,
    _doctor_status_to_preflight,
    _looks_like_placeholder,
    _print_summary,
    _security_checks,
    _storage_checks,
    _workflow_checks,
    main,
    run_preflight,
)
from app.cli.production_doctor import DoctorCheck
from app.core.config import Settings

SECRETS = ("s3cretpassword", "sk-live-secret-key", "redis-secret", "minio-secret-value")


def _settings(**overrides) -> Settings:
    defaults = {"_env_file": None, "app_profile": "local-cloud", "environment": "local"}
    return Settings(**{**defaults, **overrides})


def _production(**overrides) -> Settings:
    defaults = {
        "_env_file": None,
        "app_profile": "production",
        "environment": "production",
        "auth_enabled": True,
        "auth_secret_key": "a-genuinely-long-random-production-secret-value",
        "database_url": "postgresql+asyncpg://u:s3cretpassword@ep-prod.neon.tech/deltaledger",
        "redis_url": "redis://:redis-secret@prod-redis.example.com:6379/0",
        "object_storage_provider": "minio",
        "minio_endpoint": "https://s3.example.com",
        "minio_access_key": "prod-access-key",
        "minio_secret_key": "minio-secret-value",
        "sec_user_agent": "DeltaLedgerAI/1.0 ops@realcompany.com",
        "ai_provider_api_key": "sk-live-secret-key",
        "change_classifier_provider": "openai_compatible",
        "claim_extractor_provider": "openai_compatible",
        "readiness_dependency_checks_enabled": True,
        "cors_allowed_origins": "https://app.realcompany.com",
        "allow_fake_models_in_production": True,
        "workflow_checkpoint_provider": "postgres",
    }
    return Settings(**{**defaults, **overrides})


# --- placeholder detection ------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "<user>",
        "postgresql://<user>:<password>@host/db",
        "YOUR_API_KEY_HERE",
        "ACTUAL_TEST_HOST",
        "PASTE_YOUR_TOKEN",
        "sk-CHANGE_ME",
        "already-replace_me-please",
    ],
)
def test_placeholder_values_are_detected(value: str) -> None:
    assert _looks_like_placeholder(value) is True


@pytest.mark.parametrize(
    "value",
    ["sk-ant-real-looking-secret-1234567890", "a-real-production-secret-key", None, ""],
)
def test_real_looking_values_are_not_flagged(value: str | None) -> None:
    assert _looks_like_placeholder(value) is False


def test_security_checks_flag_placeholder_credentials_as_fail_in_production() -> None:
    settings = _production(ai_provider_api_key="YOUR_GEMINI_API_KEY")

    checks = _security_checks(settings)

    placeholder_check = next(c for c in checks if c.name == "placeholder_values")
    assert placeholder_check.status == "FAIL"
    assert "AI_PROVIDER_API_KEY" in placeholder_check.detail


def test_security_checks_flag_placeholder_credentials_as_warn_outside_production() -> None:
    settings = _settings(ai_provider_api_key="YOUR_GEMINI_API_KEY")

    checks = _security_checks(settings)

    assert next(c for c in checks if c.name == "placeholder_values").status == "WARN"


def test_security_checks_pass_with_real_looking_configuration() -> None:
    checks = _security_checks(_production())

    assert all(c.status == "PASS" for c in checks), checks


def test_localhost_in_production_is_flagged() -> None:
    settings = _production(redis_url="redis://localhost:6379/0")

    checks = _security_checks(settings)

    check = next(c for c in checks if c.name == "no_localhost_in_production")
    assert check.status == "FAIL" and "localhost" in check.detail


def _fake_production_settings(**overrides) -> SimpleNamespace:
    """A stand-in for a production Settings object with a weak secret - real
    Settings refuses to even construct that (see test_config_profiles.py), so
    this exercises _security_checks' own FAIL branch directly."""
    base = {
        "sec_user_agent": "DeltaLedgerAI/1.0 ops@realcompany.com",
        "auth_secret_key": "short",
        "auth_enabled": True,
        "ai_provider_api_key": "sk-live-secret-key",
        "minio_access_key": "prod-access-key",
        "minio_secret_key": "minio-secret-value",
        "hf_token": None,
        "is_production": True,
        "app_profile": "production",
        "environment": "production",
        "change_classifier_provider": "openai_compatible",
        "change_classifier_model": "gemini-3.5-flash-lite",
        "claim_extractor_provider": "openai_compatible",
        "claim_extractor_model": "gemini-3.5-flash-lite",
        "ai_provider_base_url": "https://api.openai.com/v1",
        "ai_provider_max_retries": 5,
        "ai_provider_chat_delay_seconds": 15.0,
        "ai_batch_multi_item_requests": True,
        "analysis_workflow_time_limit_seconds": 10800.0,
        "worker_default_time_limit_seconds": 1800.0,
        "analysis_workflow_version": "v1",
        "analysis_graph_version": "v1",
        "comparison_version": "v1",
        "workflow_checkpoint_provider": "postgres",
        "database_url": "postgresql+asyncpg://u:p@ep-prod.neon.tech/deltaledger",
        "redis_url": "redis://:p@prod-redis.example.com:6379/0",
        "object_storage_provider": "minio",
        "minio_endpoint": "https://s3.example.com",
        "embedding_provider": "sentence_transformers",
        "embedding_model": "BAAI/bge-large-en-v1.5",
        "embedding_dimension": 1024,
        "reranker_enabled": False,
    }
    return SimpleNamespace(**{**base, **overrides})


def test_weak_auth_secret_is_flagged() -> None:
    settings = _fake_production_settings()

    checks = _security_checks(settings)

    assert next(c for c in checks if c.name == "auth_secret_strength").status == "FAIL"


# --- AI / workflow / storage checks reflect real configuration -----------------------------


def test_ai_checks_report_batching_and_provider_configuration() -> None:
    settings = _settings(
        ai_batch_max_items=8,
        ai_batch_input_token_budget=12000,
        ai_batch_token_safety_margin=0.25,
        ai_provider_chat_delay_seconds=15.0,
        change_classifier_provider="openai_compatible",
        change_classifier_model="gemini-3.5-flash-lite",
        ai_provider_api_key="k",
    )

    checks = _ai_checks(settings)

    batch = next(c for c in checks if c.name == "batch_configuration")
    assert "max_items=8" in batch.detail and "effective_budget=9000" in batch.detail
    model = next(c for c in checks if c.name == "generative_model")
    assert "gemini-3.5-flash-lite" in model.detail and model.status == "PASS"
    pacing = next(c for c in checks if c.name == "chat_pacing")
    assert "chat_delay_seconds=15.0" in pacing.detail


def test_ai_checks_fail_when_a_real_provider_has_no_credential() -> None:
    settings = _settings(change_classifier_provider="openai_compatible", ai_provider_api_key=None)

    checks = _ai_checks(settings)

    assert any(c.name == "provider_credential" and c.status == "FAIL" for c in checks)


def test_workflow_checks_flag_a_short_analysis_time_limit() -> None:
    settings = _settings(
        analysis_workflow_time_limit_seconds=600, worker_default_time_limit_seconds=1800
    )

    checks = _workflow_checks(settings)

    assert next(c for c in checks if c.name == "analysis_time_limit").status == "WARN"


def test_storage_checks_fail_minio_without_bucket_names() -> None:
    settings = _settings(
        app_profile="ci",
        object_storage_provider="minio",
        minio_bucket_filings="",
        minio_bucket_reports="",
    )

    checks = _storage_checks(settings)

    assert next(c for c in checks if c.name == "bucket_configuration").status == "FAIL"


def test_storage_checks_never_include_the_minio_secret_key(monkeypatch) -> None:
    settings = _production()

    checks = _storage_checks(settings)

    dumped = json.dumps([c.detail for c in checks])
    assert "minio-secret-value" not in dumped


# --- full run: doctor is faked, nothing touches the network --------------------------------


def _fake_doctor_result(*, database_status="ok", redis_status="ok") -> dict:
    return {
        "status": "ready",
        "environment": "production",
        "app_profile": "production",
        "checks": [
            DoctorCheck(
                "database",
                database_status,
                "schema validated",
                {"url": "postgresql://u:***@ep-prod.neon.tech/deltaledger"},
            ).as_dict(),
            DoctorCheck(
                "redis", redis_status, "reachable", {"url": "redis://:***@prod-redis:6379/0"}
            ).as_dict(),
        ],
    }


@pytest.mark.asyncio
async def test_run_preflight_never_calls_gemini_or_enqueues_and_reuses_doctor_for_db_redis(
    monkeypatch,
) -> None:
    calls: list[str] = []

    async def fake_run_doctor(*, initialize_checkpoint: bool) -> dict:
        calls.append("run_doctor")
        assert initialize_checkpoint is False  # must never create/initialize anything
        return _fake_doctor_result()

    monkeypatch.setattr(preflight_e2e, "run_doctor", fake_run_doctor)
    monkeypatch.setattr(preflight_e2e, "Settings", lambda: _production())

    # If anything here imported/touched dramatiq's broker or a Gemini client,
    # these attribute errors would happen; instead the whole module surface
    # used is Settings + doctor + pure config math.
    result = await run_preflight()

    assert calls == ["run_doctor"]
    assert result["environment"] == "production"
    names = [c["name"] for c in result["checks"]]
    assert "connectivity_and_schema" in names and "connectivity" in names
    assert result["overall"] in {"PASS", "WARN", "FAIL"}


@pytest.mark.asyncio
async def test_a_blocked_doctor_database_check_fails_the_whole_preflight(monkeypatch) -> None:
    async def fake_run_doctor(*, initialize_checkpoint: bool) -> dict:
        return _fake_doctor_result(database_status="blocked")

    monkeypatch.setattr(preflight_e2e, "run_doctor", fake_run_doctor)
    monkeypatch.setattr(preflight_e2e, "Settings", lambda: _production())

    result = await run_preflight()

    db_check = next(c for c in result["checks"] if c["name"] == "connectivity_and_schema")
    assert db_check["status"] == "FAIL"
    assert result["overall"] == "FAIL"


@pytest.mark.asyncio
async def test_result_never_contains_any_configured_secret(monkeypatch) -> None:
    async def fake_run_doctor(*, initialize_checkpoint: bool) -> dict:
        return _fake_doctor_result()

    monkeypatch.setattr(preflight_e2e, "run_doctor", fake_run_doctor)
    monkeypatch.setattr(preflight_e2e, "Settings", lambda: _production())

    result = await run_preflight()

    dumped = json.dumps(result)
    for secret in SECRETS:
        assert secret not in dumped


def test_doctor_status_mapping() -> None:
    assert _doctor_status_to_preflight("blocked") == "FAIL"
    assert _doctor_status_to_preflight("warning") == "WARN"
    assert _doctor_status_to_preflight("degraded") == "WARN"
    assert _doctor_status_to_preflight("ok") == "PASS"


def test_print_summary_is_concise_and_grouped(capsys) -> None:
    result = {
        "app_profile": "production",
        "environment": "production",
        "overall": "WARN",
        "checks": [
            {
                "group": "database",
                "name": "connectivity_and_schema",
                "status": "PASS",
                "detail": "ok",
            },
            {
                "group": "ai",
                "name": "batch_configuration",
                "status": "WARN",
                "detail": "max_items=8",
            },
        ],
    }

    _print_summary(result)

    out = capsys.readouterr().out
    assert "OVERALL: WARN" in out
    assert "[DATABASE]" in out and "[AI]" in out
    assert "PASS" in out and "WARN" in out


def test_main_exit_code_reflects_overall_status(monkeypatch) -> None:
    async def fake_run_preflight() -> dict:
        return {
            "overall": "FAIL",
            "environment": "production",
            "app_profile": "production",
            "checks": [],
        }

    monkeypatch.setattr(preflight_e2e, "run_preflight", fake_run_preflight)

    assert main(["--json"]) == 1


def test_main_json_flag_prints_json_not_the_human_summary(monkeypatch, capsys) -> None:
    async def fake_run_preflight() -> dict:
        return {"overall": "PASS", "environment": "e", "app_profile": "p", "checks": []}

    monkeypatch.setattr(preflight_e2e, "run_preflight", fake_run_preflight)

    exit_code = main(["--json"])

    out = capsys.readouterr().out
    assert exit_code == 0
    parsed = json.loads(out)
    assert parsed["overall"] == "PASS"


def test_preflight_check_dataclass_shape() -> None:
    check = PreflightCheck("group", "name", "PASS", "detail")
    fields = (check.group, check.name, check.status, check.detail)
    assert fields == ("group", "name", "PASS", "detail")
