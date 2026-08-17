from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

import redis.asyncio as redis_async
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.evaluation.providers import provider_manifest
from app.integrations.storage.client import ObjectStorageClient
from app.services.analysis_workflow_service import create_workflow_checkpointer

EXPECTED_TABLES = {
    "companies",
    "filings",
    "filing_sections",
    "filing_chunks",
    "filing_tables",
    "filing_processing_stages",
    "xbrl_facts",
    "filing_comparisons",
    "section_matches",
    "passage_units",
    "passage_matches",
    "disclosure_changes",
    "financial_metric_definitions",
    "financial_metric_concepts",
    "financial_claims",
    "claim_fact_candidates",
    "claim_verifications",
    "derived_financial_metrics",
    "contradiction_findings",
    "contradiction_evidence",
    "analysis_runs",
    "analysis_workflow_events",
    "analysis_review_requests",
    "analysis_reports",
    "audit_events",
}


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str
    metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.metadata is None:
            payload.pop("metadata")
        return payload


async def run_doctor(*, initialize_checkpoint: bool = False) -> dict[str, Any]:
    try:
        settings = Settings()
    except (ValidationError, ValueError) as exc:
        return {
            "status": "blocked",
            "checks": [
                DoctorCheck(
                    "configuration",
                    "blocked",
                    _safe_error(exc),
                ).as_dict()
            ],
        }

    checks: list[DoctorCheck] = [
        _configuration_check(settings),
        _provider_check(settings),
        await _database_check(settings),
        await _redis_check(settings),
        _storage_check(settings),
        await _checkpoint_check(settings, initialize=initialize_checkpoint),
    ]
    status = _overall_status(checks)
    return {
        "status": status,
        "environment": settings.environment,
        "app_profile": settings.app_profile,
        "checks": [check.as_dict() for check in checks],
    }


def _configuration_check(settings: Settings) -> DoctorCheck:
    required_production = [
        "APP_PROFILE",
        "ENVIRONMENT",
        "DATABASE_URL",
        "REDIS_URL",
        "OBJECT_STORAGE_PROVIDER",
        "SEC_USER_AGENT",
        "AUTH_ENABLED",
        "AUTH_SECRET_KEY",
        "WORKFLOW_CHECKPOINT_PROVIDER",
        "CORS_ALLOWED_ORIGINS",
        "READINESS_DEPENDENCY_CHECKS_ENABLED",
    ]
    metadata = {
        "database_url": mask_url(settings.database_url),
        "alembic_database_url": mask_url(settings.alembic_database_url or ""),
        "redis_url": mask_url(settings.redis_url),
        "object_storage_provider": settings.object_storage_provider,
        "workflow_checkpoint_provider": settings.workflow_checkpoint_provider,
        "required_production": required_production,
    }
    if settings.is_production:
        return DoctorCheck("configuration", "ok", "production configuration loaded", metadata)
    return DoctorCheck("configuration", "warning", "not running with production profile", metadata)


async def _database_check(settings: Settings) -> DoctorCheck:
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        pool_timeout=settings.database_pool_timeout_seconds,
    )
    try:
        async with engine.connect() as connection:
            version = await connection.scalar(text("select version()"))
            ssl_status = await _ssl_status(connection)
            current_revision = await _optional_scalar(
                connection,
                "select version_num from alembic_version limit 1",
            )
            vector_version = await _optional_scalar(
                connection,
                "select extversion from pg_extension where extname = 'vector'",
            )
            tables = {
                row[0]
                for row in (
                    await connection.execute(
                        text("select tablename from pg_tables where schemaname = 'public'")
                    )
                )
            }
            chunk_columns = {
                row[0]: row[1]
                for row in (
                    await connection.execute(
                        text(
                            "select a.attname, format_type(a.atttypid, a.atttypmod) "
                            "from pg_attribute a join pg_class c on c.oid = a.attrelid "
                            "where c.relname = 'filing_chunks' and a.attnum > 0 "
                            "and not a.attisdropped"
                        )
                    )
                )
            }
            indexes = {
                row[0]: row[1]
                for row in (
                    await connection.execute(
                        text(
                            "select indexname, indexdef from pg_indexes "
                            "where schemaname = 'public' and tablename = 'filing_chunks'"
                        )
                    )
                )
            }
    except Exception as exc:
        return DoctorCheck(
            "database",
            "blocked",
            _safe_error(exc),
            {"url": mask_url(settings.database_url)},
        )
    finally:
        await engine.dispose()

    missing_tables = sorted(EXPECTED_TABLES - tables)
    checks = {
        "alembic_current": current_revision,
        "vector_extension_version": vector_version,
        "missing_tables": missing_tables,
        "embedding_column": chunk_columns.get("embedding"),
        "search_vector_column": chunk_columns.get("search_vector"),
        "has_hnsw_index": "ix_filing_chunks_embedding_hnsw" in indexes,
        "has_fts_index": "ix_filing_chunks_search_vector_gin" in indexes,
        "ssl": ssl_status,
        "server_version": str(version).splitlines()[0] if version else None,
    }
    ok = (
        current_revision == "0006_phase6_workflow"
        and vector_version is not None
        and not missing_tables
        and chunk_columns.get("embedding") == "vector(1024)"
        and chunk_columns.get("search_vector") == "tsvector"
        and checks["has_hnsw_index"]
        and checks["has_fts_index"]
    )
    return DoctorCheck(
        "database",
        "ok" if ok else "degraded",
        "schema validated" if ok else "database reachable but schema validation is incomplete",
        checks,
    )


async def _redis_check(settings: Settings) -> DoctorCheck:
    client = redis_async.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.redis_connect_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        retry_on_timeout=True,
    )
    try:
        await client.ping()
    except Exception as exc:
        return DoctorCheck(
            "redis",
            "blocked",
            _safe_error(exc),
            {"url": mask_url(settings.redis_url)},
        )
    finally:
        await client.aclose()
    return DoctorCheck("redis", "ok", "reachable", {"url": mask_url(settings.redis_url)})


def _storage_check(settings: Settings) -> DoctorCheck:
    try:
        ObjectStorageClient(settings)
    except Exception as exc:
        return DoctorCheck(
            "storage",
            "blocked",
            _safe_error(exc),
            {"provider": settings.object_storage_provider},
        )
    status = "ok" if settings.object_storage_provider == "minio" else "warning"
    detail = (
        "S3-compatible storage configured"
        if settings.object_storage_provider == "minio"
        else "filesystem storage is development-only"
    )
    return DoctorCheck(
        "storage",
        status,
        detail,
        {
            "provider": settings.object_storage_provider,
            "endpoint": mask_url(settings.minio_endpoint),
            "filings_bucket": settings.minio_bucket_filings,
            "reports_bucket": settings.minio_bucket_reports,
        },
    )


async def _checkpoint_check(settings: Settings, *, initialize: bool) -> DoctorCheck:
    if settings.workflow_checkpoint_provider != "postgres":
        status = "blocked" if settings.is_production else "warning"
        return DoctorCheck(
            "checkpoint",
            status,
            "workflow checkpoint provider is not postgres",
            {"provider": settings.workflow_checkpoint_provider},
        )
    if not initialize:
        return DoctorCheck(
            "checkpoint",
            "warning",
            "postgres checkpoint selected; initialization skipped",
            {"provider": settings.workflow_checkpoint_provider},
        )
    try:
        await create_workflow_checkpointer(settings)
    except Exception as exc:
        return DoctorCheck(
            "checkpoint",
            "blocked",
            _safe_error(exc),
            {"provider": settings.workflow_checkpoint_provider},
        )
    return DoctorCheck(
        "checkpoint",
        "ok",
        "postgres checkpoint initialized",
        {"provider": settings.workflow_checkpoint_provider},
    )


def _provider_check(settings: Settings) -> DoctorCheck:
    manifest = provider_manifest(settings)
    status = manifest["real_provider_evaluation"]
    if status == "NOT_EVALUATED_FAKE_ONLY_CONFIGURATION":
        check_status = "warning"
    elif status == "BLOCKED_EXTERNAL_CREDENTIAL":
        check_status = "blocked"
    else:
        check_status = "ok"
    return DoctorCheck(
        "model_providers",
        check_status,
        str(status),
        {"entries": manifest["entries"]},
    )


async def _ssl_status(connection) -> str:
    try:
        value = await connection.scalar(
            text(
                "select ssl from pg_stat_ssl "
                "where pid = pg_backend_pid()"
            )
        )
    except Exception:
        return "unknown"
    return "enabled" if value else "disabled"


async def _optional_scalar(connection, query: str) -> Any:
    try:
        return await connection.scalar(text(query))
    except Exception:
        return None


def mask_url(value: str | None) -> str | None:
    if not value:
        return value
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    username = quote(unquote(parsed.username or ""), safe="")
    password = ":***" if parsed.password is not None else ""
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    auth = f"{username}{password}@" if username or password else ""
    query = urlencode(_masked_query(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme, f"{auth}{host}{port}", parsed.path, query, ""))


def _masked_query(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    sensitive = {"password", "pass", "token", "key", "secret", "access_key", "secret_key"}
    masked = []
    for key, value in values:
        lowered = key.lower()
        masked.append((key, "***" if any(item in lowered for item in sensitive) else value))
    return masked


def _safe_error(exc: Exception) -> str:
    text_value = str(exc)
    if "://" in text_value or "password" in text_value.lower() or "token" in text_value.lower():
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {text_value}" if text_value else exc.__class__.__name__


def _overall_status(checks: list[DoctorCheck]) -> str:
    if any(check.status == "blocked" for check in checks):
        return "blocked"
    if any(check.status in {"warning", "degraded"} for check in checks):
        return "degraded"
    return "ready"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run safe DeltaLedger production infrastructure diagnostics."
    )
    parser.add_argument(
        "--initialize-checkpoint",
        action="store_true",
        help="Initialize LangGraph PostgreSQL checkpoint tables when configured.",
    )
    args = parser.parse_args()
    payload = asyncio.run(run_doctor(initialize_checkpoint=args.initialize_checkpoint))
    print(json.dumps(payload, sort_keys=True))
    raise SystemExit(0 if payload["status"] in {"ready", "degraded"} else 1)


if __name__ == "__main__":
    main()
