"""The test process must not inherit the developer's `.env` / shell settings,
and destructive database tests must refuse anything but a disposable local
database."""

from __future__ import annotations

import os

import pytest

from app.core.config import Settings
from tests import env_isolation
from tests.env_isolation import assert_safe_test_database

opted_in = env_isolation._wants_real_dotenv()
skip_if_opted_in = pytest.mark.skipif(
    opted_in, reason="this run opted in to the real .env (live/model-smoke or DOTENV opt-in)"
)


@skip_if_opted_in
def test_a_dotenv_file_in_the_working_directory_is_not_loaded(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "ENVIRONMENT=production\nAPP_PROFILE=production\nEMBEDDING_PROVIDER=huggingface\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()  # no _env_file argument: exactly what application code does

    assert settings.environment != "production"
    assert settings.app_profile != "production"
    assert settings.embedding_provider != "huggingface"


@skip_if_opted_in
def test_ambient_settings_environment_variables_are_removed_for_the_test_process() -> None:
    for field_name in Settings.model_fields:
        key = field_name.upper()
        if key != "TEST_DATABASE_URL":
            assert key not in os.environ, f"{key} leaked into the test process"


def test_explicit_test_overrides_still_work(monkeypatch) -> None:
    monkeypatch.setenv("AI_PROVIDER_CHAT_DELAY_SECONDS", "2.5")
    monkeypatch.setenv("AI_BATCH_MAX_ITEMS", "3")

    settings = Settings()

    assert settings.ai_provider_chat_delay_seconds == 2.5
    assert settings.ai_batch_max_items == 3
    assert Settings(ai_batch_max_items=5).ai_batch_max_items == 5


def test_an_explicit_env_file_argument_still_loads_that_file(tmp_path) -> None:
    env_file = tmp_path / "custom.env"
    env_file.write_text("AI_BATCH_MAX_ITEMS=11\n", encoding="utf-8")

    assert Settings(_env_file=env_file).ai_batch_max_items == 11


# --- destructive-test database guard ----------------------------------------------------------


@pytest.fixture
def application_database(monkeypatch):
    monkeypatch.setattr(
        env_isolation,
        "_APPLICATION_DATABASES",
        {("ep-real-host.neon.tech", None, "deltaledger_test")},
    )


def test_a_disposable_local_test_database_is_accepted() -> None:
    assert_safe_test_database("postgresql+asyncpg://u:p@localhost:5433/deltaledger_test")
    assert_safe_test_database("postgresql+asyncpg://u@127.0.0.1:5433/other_test_db")


def test_the_application_database_is_refused_even_if_its_name_contains_test(
    application_database,
) -> None:
    with pytest.raises(RuntimeError, match="same database"):
        assert_safe_test_database(
            "postgresql+asyncpg://u:p@ep-real-host.neon.tech/deltaledger_test"
        )


def test_a_database_without_test_in_its_name_is_refused() -> None:
    with pytest.raises(RuntimeError, match="must contain 'test'"):
        assert_safe_test_database("postgresql+asyncpg://u@localhost:5433/deltaledger")


def test_a_remote_host_is_refused_unless_explicitly_allowed(monkeypatch) -> None:
    url = "postgresql+asyncpg://u:p@db.example.com:5432/scratch_test"

    with pytest.raises(RuntimeError, match="non-local host"):
        assert_safe_test_database(url)

    monkeypatch.setenv("ALLOW_REMOTE_TEST_DATABASE", "1")
    assert_safe_test_database(url)


def test_an_empty_url_is_refused() -> None:
    with pytest.raises(RuntimeError):
        assert_safe_test_database("")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://<user>:<password>@ep-host.neon.tech/deltaledger_test",
        "postgresql+asyncpg://u:p@ACTUAL_TEST_HOST.neon.tech/deltaledger_test",
        "postgresql+asyncpg://u:p@REAL_TEST_ENDPOINT.neon.tech/deltaledger_test",
        "postgresql+asyncpg://u:PASTE_YOUR_PASSWORD@host.neon.tech/deltaledger_test",
        "postgresql+asyncpg://YOUR_USER:p@host.neon.tech/deltaledger_test",
        "postgresql+asyncpg://u:p@host.neon.tech/CHANGE_ME_test",
        # Case must not matter - a placeholder pasted in any case is still one.
        "postgresql+asyncpg://u:p@actual_test_host.neon.tech/deltaledger_test",
    ],
)
def test_placeholder_tokens_are_refused_immediately_without_any_dns_or_connection(
    url: str, monkeypatch
) -> None:
    # If the guard tried DNS/connection first, an unresolvable placeholder
    # host would raise a socket/DNS error here, not RuntimeError - resolving
    # would also mean the guard *did* reach out to the network for a string
    # that was never a real host to begin with.
    def _no_network(*_args, **_kwargs):
        raise AssertionError("the placeholder guard must not touch the network")

    monkeypatch.setattr("socket.getaddrinfo", _no_network, raising=False)
    monkeypatch.setenv("ALLOW_REMOTE_TEST_DATABASE", "1")  # even opting in must not help

    with pytest.raises(RuntimeError, match="placeholder"):
        assert_safe_test_database(url)


def test_a_real_looking_url_that_merely_contains_test_is_not_flagged_as_a_placeholder(
    monkeypatch,
) -> None:
    # "test" alone is expected and required; only the specific placeholder
    # tokens above are treated as unfilled-in instructions. The remote-host
    # opt-in below is a separate, later check - this only proves the
    # placeholder scan itself doesn't misfire on a normal Neon hostname.
    monkeypatch.setenv("ALLOW_REMOTE_TEST_DATABASE", "1")
    assert_safe_test_database("postgresql+asyncpg://neondb_owner:p@ep-cool-1.neon.tech/dl_test")


def test_the_guard_recognises_the_real_dotenv_database(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://u:p@prod.example.com:5432/app_test_named\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(env_isolation, "_BACKEND_ROOT", tmp_path)

    captured = env_isolation._capture_application_databases()

    assert ("prod.example.com", 5432, "app_test_named") in captured
