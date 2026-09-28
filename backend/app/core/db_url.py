"""Database URL helpers shared by the application and Alembic.

Deliberately free of any import of `Settings`: Alembic must be able to resolve
its migration URL without instantiating (and validating) the application's
whole runtime configuration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# asyncpg's `ssl=` takes the libpq sslmode vocabulary, plus boolean-ish forms.
_SSL_VALUE_TO_SSLMODE = {
    "true": "require",
    "1": "require",
    "false": "disable",
    "0": "disable",
}
# Query parameters that only the asyncpg driver / SQLAlchemy's asyncpg dialect
# understand; libpq (psycopg) rejects unknown parameters outright.
_ASYNCPG_ONLY_PARAMS = frozenset(
    {
        "prepared_statement_cache_size",
        "prepared_statement_name_func",
        "statement_cache_size",
        "max_cached_statement_lifetime",
        "max_cacheable_statement_size",
        "command_timeout",
        "server_settings",
    }
)
_SYNC_SCHEMES = ("postgresql+psycopg://", "postgresql://")


def to_sync_database_url(url: str) -> str:
    """Convert a runtime (asyncpg) database URL into one psycopg/libpq accepts.

    * scheme `postgresql+asyncpg` -> `postgresql+psycopg`
    * `ssl=<mode>` -> `sslmode=<mode>` (libpq has no `ssl` parameter; boolean
      spellings map to require/disable). An explicit `sslmode` wins over `ssl`.
    * asyncpg-only parameters are dropped.
    * every other parameter - e.g. Neon's `channel_binding` or `options` - and
      the userinfo are preserved byte-for-byte (no re-encoding).
    """
    parts = urlsplit(url)
    scheme = "postgresql+psycopg" if parts.scheme == "postgresql+asyncpg" else parts.scheme
    pairs = [pair for pair in parts.query.split("&") if pair]
    has_sslmode = any(pair.partition("=")[0] == "sslmode" for pair in pairs)
    kept: list[str] = []
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if key in _ASYNCPG_ONLY_PARAMS:
            continue
        if key == "ssl":
            if has_sslmode:
                continue
            kept.append(f"sslmode={_SSL_VALUE_TO_SSLMODE.get(value.lower(), value)}")
            continue
        kept.append(f"{key}{separator}{value}")
    return urlunsplit(parts._replace(scheme=scheme, query="&".join(kept)))


def resolve_migration_url(
    environ: Mapping[str, str],
    settings_factory: Callable[[], Any],
) -> str:
    """The database URL Alembic should migrate.

    An explicit `ALEMBIC_DATABASE_URL` in the process environment wins and is
    used directly: `settings_factory` is not called, so no unrelated runtime
    configuration (object storage, Redis, model providers...) is required just
    to run migrations. Without it, the application's normal settings decide.
    """
    explicit = (environ.get("ALEMBIC_DATABASE_URL") or "").strip()
    if explicit:
        url = to_sync_database_url(explicit)
        if not url.startswith(_SYNC_SCHEMES):
            raise ValueError(
                "ALEMBIC_DATABASE_URL must be a PostgreSQL URL "
                "(postgresql+psycopg:// or postgresql+asyncpg://)."
            )
        return url
    settings = settings_factory()
    return settings.alembic_database_url or settings.database_url
