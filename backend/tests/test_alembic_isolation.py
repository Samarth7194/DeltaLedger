"""Alembic must run from an explicit migration URL alone, independent of the
developer's application `.env`; the asyncpg -> psycopg URL conversion must be
valid for libpq. No database is contacted."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.errors import ProgrammingError

from app.core.db_url import resolve_migration_url, to_sync_database_url
from tests import env_isolation
from tests.conftest import BACKEND_DIR, alembic_subprocess_env
from tests.env_isolation import assert_safe_test_database

NEON = (
    "postgresql+asyncpg://neondb_owner:p%40ss%2Fw0rd@ep-cool-name-123.us-east-2.aws.neon.tech"
    "/deltaledger_test?ssl=require"
)


def _libpq(url: str) -> dict[str, str]:
    """What libpq itself makes of the URL (raises for parameters it rejects)."""
    return conninfo_to_dict(url.replace("postgresql+psycopg://", "postgresql://", 1))


# --- URL conversion ----------------------------------------------------------------------------


def test_the_neon_style_asyncpg_url_becomes_a_valid_libpq_url() -> None:
    converted = to_sync_database_url(NEON)

    assert converted == (
        "postgresql+psycopg://neondb_owner:p%40ss%2Fw0rd@ep-cool-name-123.us-east-2.aws.neon.tech"
        "/deltaledger_test?sslmode=require"
    )
    parsed = _libpq(converted)
    assert parsed["sslmode"] == "require" and parsed["dbname"] == "deltaledger_test"
    assert parsed["password"] == "p@ss/w0rd"  # percent-encoding preserved and decodable


def test_libpq_really_rejects_the_asyncpg_ssl_parameter() -> None:
    """Why a plain scheme swap is not enough."""
    naive = NEON.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)

    with pytest.raises(ProgrammingError, match='invalid URI query parameter: "ssl"'):
        _libpq(naive)
    _libpq(to_sync_database_url(NEON))  # the converted URL parses


@pytest.mark.parametrize(
    ("asyncpg_query", "expected_query"),
    [
        ("ssl=require", "sslmode=require"),
        ("ssl=verify-full", "sslmode=verify-full"),
        ("ssl=prefer", "sslmode=prefer"),
        ("ssl=true", "sslmode=require"),
        ("ssl=false", "sslmode=disable"),
        ("ssl=require&channel_binding=require", "sslmode=require&channel_binding=require"),
        (
            "ssl=require&options=endpoint%3Dep-cool-name-123&application_name=dl",
            "sslmode=require&options=endpoint%3Dep-cool-name-123&application_name=dl",
        ),
        ("sslmode=require", "sslmode=require"),  # already libpq style: untouched
        ("sslmode=verify-ca&ssl=require", "sslmode=verify-ca"),  # explicit sslmode wins
        ("ssl=require&prepared_statement_cache_size=0", "sslmode=require"),  # asyncpg-only
        ("statement_cache_size=0&connect_timeout=10", "connect_timeout=10"),
        ("", ""),
    ],
)
def test_query_parameters_are_normalised_and_valid_ones_preserved(
    asyncpg_query: str, expected_query: str
) -> None:
    url = "postgresql+asyncpg://u:p@localhost:5433/deltaledger_test"
    converted = to_sync_database_url(f"{url}?{asyncpg_query}" if asyncpg_query else url)

    expected = f"{url.replace('+asyncpg', '+psycopg')}" + (
        f"?{expected_query}" if expected_query else ""
    )
    assert converted == expected
    _libpq(converted)  # every converted URL is accepted by libpq


def test_already_synchronous_urls_are_left_alone() -> None:
    for url in (
        "postgresql+psycopg://u:p@h:5432/db?sslmode=require",
        "postgresql://u:p@h:5432/db?sslmode=require",
    ):
        assert to_sync_database_url(url) == url


def test_the_application_settings_use_the_same_conversion() -> None:
    from app.core.config import Settings

    settings = Settings(
        _env_file=None, app_profile="local-cloud", environment="local", database_url=NEON
    )

    assert settings.alembic_database_url == to_sync_database_url(NEON)
    _libpq(settings.alembic_database_url)


# --- URL resolution: explicit ALEMBIC_DATABASE_URL never needs Settings ---------------------------


def _boom():
    raise AssertionError("application Settings must not be instantiated")


def test_an_explicit_migration_url_wins_without_touching_the_application_settings() -> None:
    url = resolve_migration_url(
        {"ALEMBIC_DATABASE_URL": NEON, "DATABASE_URL": "postgresql+asyncpg://x@prod/prod"}, _boom
    )

    assert url == to_sync_database_url(NEON)
    assert "prod" not in url


def test_without_an_explicit_url_the_normal_application_fallback_is_preserved() -> None:
    class Settings:
        alembic_database_url = "postgresql+psycopg://app@host/app"
        database_url = "postgresql+asyncpg://app@host/app"

    assert resolve_migration_url({}, lambda: Settings) == "postgresql+psycopg://app@host/app"
    assert resolve_migration_url({"ALEMBIC_DATABASE_URL": "  "}, lambda: Settings) == (
        "postgresql+psycopg://app@host/app"
    )

    Settings.alembic_database_url = None
    assert resolve_migration_url({}, lambda: Settings) == "postgresql+asyncpg://app@host/app"


def test_a_non_postgres_migration_url_is_refused() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        resolve_migration_url({"ALEMBIC_DATABASE_URL": "sqlite:///x.db"}, _boom)


# --- the test subprocess environment -----------------------------------------------------


def test_the_alembic_subprocess_env_carries_only_the_migration_url_and_startup_basics(
    monkeypatch,
) -> None:
    for key, value in {
        "DATABASE_URL": "postgresql+asyncpg://prod:secret@prod-host/prod",
        "OBJECT_STORAGE_PROVIDER": "minio",
        "AI_PROVIDER_API_KEY": "sk-secret",
        "HF_TOKEN": "hf-secret",
        "REDIS_URL": "redis://:secret@redis/0",
        "MINIO_SECRET_KEY": "minio-secret",
        "APP_PROFILE": "production",
    }.items():
        monkeypatch.setenv(key, value)

    env = alembic_subprocess_env("postgresql+asyncpg://u:p@localhost:5433/deltaledger_test?ssl=require")

    assert env["ALEMBIC_DATABASE_URL"] == (
        "postgresql+psycopg://u:p@localhost:5433/deltaledger_test?sslmode=require"
    )
    assert set(env) <= set(env_isolation.SUBPROCESS_ENV_ALLOWLIST) | {"ALEMBIC_DATABASE_URL"}
    assert "DATABASE_URL" not in env
    assert "secret" not in " ".join(env.values()).replace("p@localhost", "")


def test_the_migration_fixtures_go_through_the_database_safety_guard() -> None:
    import inspect

    from tests import conftest

    assert "safe_test_database_url" in inspect.signature(
        conftest.migrated_test_database.__wrapped__
        if hasattr(conftest.migrated_test_database, "__wrapped__")
        else conftest.migrated_test_database._get_wrapped_function()
    ).parameters


def test_the_production_database_cannot_become_the_test_database(monkeypatch) -> None:
    production = ("ep-prod.us-east-2.aws.neon.tech", None, "deltaledger_test")
    monkeypatch.setattr(env_isolation, "_APPLICATION_DATABASES", {production})

    # Same host and database in a different dialect / query spelling: still refused.
    for spelling in (
        "postgresql+asyncpg://u:p@ep-prod.us-east-2.aws.neon.tech/deltaledger_test?ssl=require",
        "postgresql+psycopg://u:p@ep-prod.us-east-2.aws.neon.tech/deltaledger_test?sslmode=require",
    ):
        with pytest.raises(RuntimeError, match="same database"):
            assert_safe_test_database(spelling)


def test_unsafe_remote_or_non_test_databases_are_still_refused(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DATABASE", raising=False)

    with pytest.raises(RuntimeError, match="non-local host"):
        assert_safe_test_database(NEON)  # a "test" name, but a remote host
    with pytest.raises(RuntimeError, match="must contain 'test'"):
        assert_safe_test_database("postgresql+asyncpg://u@localhost:5433/deltaledger")

    monkeypatch.setenv("ALLOW_REMOTE_TEST_DATABASE", "1")
    assert_safe_test_database(NEON)  # explicit opt-in for a disposable remote test DB


# --- Alembic itself, with a hostile application .env (offline SQL, no connection) -----------


HOSTILE_DOTENV = "\n".join(
    [
        # Rejected by Settings validation (profile/environment/storage mismatch).
        "APP_PROFILE=local-cloud",
        "OBJECT_STORAGE_PROVIDER=minio",
        "ENVIRONMENT=production",
        "DATABASE_URL=postgresql+asyncpg://prod:secret@prod-host.example.com/prod",
    ]
)


def _run_alembic_offline(tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    (tmp_path / ".env").write_text(HOSTILE_DOTENV, encoding="utf-8")
    ini = (BACKEND_DIR / "alembic.ini").read_text(encoding="utf-8")
    ini = ini.replace("script_location = alembic", f"script_location = {BACKEND_DIR / 'alembic'}")
    ini = ini.replace("prepend_sys_path = .", f"prepend_sys_path = {BACKEND_DIR}")
    (tmp_path / "alembic.ini").write_text(ini, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "0006_phase6_workflow:0007_stage_batches",
            "--sql",
        ],
        cwd=tmp_path,  # Settings would find the hostile .env here
        env={**env, "PYTHONPATH": str(BACKEND_DIR)},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_alembic_runs_from_the_explicit_url_despite_an_incompatible_application_dotenv(
    tmp_path,
) -> None:
    env = alembic_subprocess_env("postgresql+asyncpg://u:p@localhost:5433/deltaledger_test")
    assert "OBJECT_STORAGE_PROVIDER" not in env

    result = _run_alembic_offline(tmp_path, env)

    assert result.returncode == 0, result.stderr[-800:]
    assert "CREATE TABLE analysis_stage_batches" in result.stdout


def test_the_hostile_dotenv_really_does_break_the_settings_based_path(tmp_path) -> None:
    """Control: without an explicit migration URL alembic falls back to the
    application Settings, which the same .env makes fail - so the test above
    proves the explicit URL is what protects migrations."""
    env = dict(alembic_subprocess_env("postgresql+asyncpg://u@h/x_test"))
    env.pop("ALEMBIC_DATABASE_URL")

    result = _run_alembic_offline(tmp_path, env)

    assert result.returncode != 0
    assert "ValidationError" in result.stderr  # Settings rejected the hostile .env


def test_the_explicit_url_beats_a_different_url_in_the_process_environment(tmp_path) -> None:
    env = alembic_subprocess_env("postgresql+asyncpg://u:p@localhost:5433/deltaledger_test")
    env["DATABASE_URL"] = "postgresql+asyncpg://prod:secret@prod-host.example.com/prod"

    result = _run_alembic_offline(tmp_path, env)

    assert result.returncode == 0, result.stderr[-800:]
    assert "prod-host" not in result.stdout + result.stderr


def test_this_test_process_is_itself_isolated() -> None:
    assert "OBJECT_STORAGE_PROVIDER" not in os.environ or env_isolation._wants_real_dotenv()
