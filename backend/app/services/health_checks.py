from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import redis.asyncio as redis_async
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.integrations.storage.client import ObjectStorageClient

HealthStatus = Literal["ok", "degraded"]


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    status: HealthStatus
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


async def run_readiness_checks(settings: Settings) -> dict[str, Any]:
    results = [check_configuration(settings), check_checkpoint_configuration(settings)]
    if settings.readiness_dependency_checks_enabled:
        results.extend(
            [
                await check_database(settings),
                await check_pgvector(settings),
                await check_redis(settings),
                check_storage_configuration(settings),
            ]
        )
    status = "ready" if all(item.status == "ok" for item in results) else "degraded"
    return {
        "status": status,
        "checks": {item.name: item.as_dict() for item in results},
    }


def check_configuration(settings: Settings) -> HealthCheckResult:
    try:
        Settings(**settings.model_dump())
    except ValueError as exc:
        return HealthCheckResult("configuration", "degraded", _safe_error(exc))
    return HealthCheckResult("configuration", "ok", "configuration loaded")


def check_checkpoint_configuration(settings: Settings) -> HealthCheckResult:
    if settings.is_production and settings.workflow_checkpoint_provider != "postgres":
        return HealthCheckResult(
            "checkpoint",
            "degraded",
            "production checkpoint provider must be postgres",
        )
    return HealthCheckResult("checkpoint", "ok", settings.workflow_checkpoint_provider)


async def check_database(settings: Settings) -> HealthCheckResult:
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        pool_timeout=settings.database_pool_timeout_seconds,
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        return HealthCheckResult("database", "degraded", _safe_error(exc))
    finally:
        await engine.dispose()
    return HealthCheckResult("database", "ok", "reachable")


async def check_pgvector(settings: Settings) -> HealthCheckResult:
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        pool_timeout=settings.database_pool_timeout_seconds,
    )
    try:
        async with engine.connect() as connection:
            installed = await connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
    except Exception as exc:
        return HealthCheckResult("pgvector", "degraded", _safe_error(exc))
    finally:
        await engine.dispose()
    if installed:
        return HealthCheckResult("pgvector", "ok", "extension enabled")
    return HealthCheckResult("pgvector", "degraded", "vector extension is not enabled")


async def check_redis(settings: Settings) -> HealthCheckResult:
    client = redis_async.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.redis_connect_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        retry_on_timeout=True,
    )
    try:
        await client.ping()
    except Exception as exc:
        return HealthCheckResult("redis", "degraded", _safe_error(exc))
    finally:
        await client.aclose()
    return HealthCheckResult("redis", "ok", "reachable")


def check_storage_configuration(settings: Settings) -> HealthCheckResult:
    try:
        ObjectStorageClient(settings)
    except Exception as exc:
        return HealthCheckResult("storage", "degraded", _safe_error(exc))
    return HealthCheckResult("storage", "ok", settings.object_storage_provider)


def _safe_error(exc: Exception) -> str:
    message = exc.__class__.__name__
    text_value = str(exc)
    if text_value and "://" not in text_value and "password" not in text_value.lower():
        return f"{message}: {text_value}"
    return message
