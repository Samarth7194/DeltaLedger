"""Isolation of the test process from the developer's environment, and the
safety guard for destructive database tests. Imported first by conftest.py,
before anything imports the application."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

# Why this exists:
#
# Settings reads `.env` (and process environment variables). A developer's real
# `.env` describes a production-like setup (hosted providers, production
# profile, real database/storage), so letting it leak into unit tests both
# breaks them and risks pointing tests at real services.
#
# Unless a run explicitly opts in, tests therefore see Settings defaults plus
# whatever a test sets itself (Settings(...) arguments or monkeypatch.setenv):
#   * `.env` loading is switched off for the process, and
#   * ambient environment variables that map to Settings fields are removed
#     (TEST_DATABASE_URL is kept: it is the explicit opt-in for Postgres tests).
# Opt in to the real `.env` with DELTALEDGER_TEST_USE_DOTENV=1; live/model-smoke
# runs (RUN_LIVE_TESTS / RUN_MODEL_SMOKE[_TESTS]) do so automatically because
# they need real provider credentials.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_KEEP_ENV = {"TEST_DATABASE_URL"}
# The only process-environment variables handed to a subprocess (alembic): what
# Python needs to start and find its packages, and nothing about the
# application's configuration or credentials.
SUBPROCESS_ENV_ALLOWLIST = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
    "VIRTUAL_ENV",
    "LANG",
    "LC_ALL",
)
_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres"}
# Obvious copy-paste-instructions placeholders we've actually typed into
# TEST_DATABASE_URL by mistake (e.g. "postgresql+asyncpg://<user>:<password>@
# ACTUAL_TEST_HOST/deltaledger_test"). Checked as a plain substring scan of the
# raw URL - no DNS, no connection attempt - so a placeholder is rejected
# immediately, before any of the other (name/host) checks below even run.
_PLACEHOLDER_TOKENS = (
    "<user>",
    "<username>",
    "<password>",
    "<host>",
    "<pass>",
    "ACTUAL_",
    "REAL_TEST_",
    "PASTE_",
    "YOUR_",
    "CHANGE_ME",
    "REPLACE_ME",
)


def _wants_real_dotenv() -> bool:
    return any(
        os.getenv(name) == "1"
        for name in (
            "DELTALEDGER_TEST_USE_DOTENV",
            "RUN_LIVE_TESTS",
            "RUN_MODEL_SMOKE",
            "RUN_MODEL_SMOKE_TESTS",
        )
    )


def _database_identity(url: str | None) -> tuple[str, int | None, str] | None:
    """(host, port, database) - what makes two database URLs the same database."""
    if not url:
        return None
    parsed = urlparse(url.replace("+asyncpg", "").replace("+psycopg", ""))
    return (parsed.hostname or "", parsed.port, parsed.path.lstrip("/"))


def _capture_application_databases() -> set[tuple[str, int | None, str]]:
    """The databases the application itself is configured for (DATABASE_URL /
    ALEMBIC_DATABASE_URL from the environment and from `.env`), captured BEFORE
    the isolation below hides them, so the destructive-test guard can refuse
    to touch any of them."""
    urls = [os.getenv("DATABASE_URL"), os.getenv("ALEMBIC_DATABASE_URL")]
    dotenv_path = _BACKEND_ROOT / ".env"
    if dotenv_path.exists():
        from dotenv import dotenv_values

        values = dotenv_values(dotenv_path)
        urls += [values.get("DATABASE_URL"), values.get("ALEMBIC_DATABASE_URL")]
    return {identity for identity in map(_database_identity, urls) if identity}


_APPLICATION_DATABASES = _capture_application_databases()


def _isolate_settings_from_environment() -> None:
    if _wants_real_dotenv():
        return
    from app.core.config import Settings, get_settings

    Settings.model_config["env_file"] = None
    for field_name in Settings.model_fields:
        key = field_name.upper()
        if key not in _KEEP_ENV:
            os.environ.pop(key, None)
    get_settings.cache_clear()


def assert_safe_test_database(test_url: str) -> None:
    """Refuse to run destructive database tests against anything but a
    disposable local test database: never an application database (from the
    environment or `.env`), never an unfilled-in placeholder, never a database
    whose name lacks "test", and never a non-local host unless
    ALLOW_REMOTE_TEST_DATABASE=1."""
    if not test_url or not test_url.strip():
        raise RuntimeError("TEST_DATABASE_URL is empty.")
    upper = test_url.upper()
    placeholder = next(
        (token for token in _PLACEHOLDER_TOKENS if token.upper() in upper), None
    )
    if placeholder is not None:
        # No DNS lookup, no connection attempt: this is a pure string check,
        # so it runs (and fails fast) before anything else here does.
        raise RuntimeError(
            "Refusing destructive integration tests: TEST_DATABASE_URL looks like an "
            f"unfilled-in placeholder (contains {placeholder!r}). Set it to your actual "
            "disposable test database connection string."
        )
    identity = _database_identity(test_url)
    assert identity is not None  # test_url was already confirmed non-empty above
    host, _port, name = identity
    if identity in _APPLICATION_DATABASES:
        raise RuntimeError(
            "Refusing destructive integration tests: TEST_DATABASE_URL is the same database "
            "as the application's DATABASE_URL."
        )
    if "test" not in name.lower():
        raise RuntimeError(
            "Refusing destructive integration tests: the test database name must contain 'test'."
        )
    if host not in _LOCAL_DB_HOSTS and os.getenv("ALLOW_REMOTE_TEST_DATABASE") != "1":
        raise RuntimeError(
            f"Refusing destructive integration tests against non-local host {host!r}. "
            "Use a disposable local database (docker compose up -d postgres), or set "
            "ALLOW_REMOTE_TEST_DATABASE=1 if you are certain it is disposable."
        )


isolate_settings_from_environment = _isolate_settings_from_environment
