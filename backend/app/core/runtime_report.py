"""Safe, credential-free description of the runtime configuration.

The API and the Dramatiq worker are separate processes that must agree on
everything that affects results (providers, models, versions, batching). This
builds one summary of that configuration - logged at startup of both, and shown
by the production doctor - plus a fingerprint of the shared part so a deployment
can confirm at a glance that API and worker are configured identically.

It never includes passwords, API keys, tokens, or full connection URLs: only
hosts, ports, model names, numbers and booleans.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.ai.batching import BatchingConfig, canonical_hash
from app.core.config import Settings

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class RuntimeNote:
    level: str  # "warning" | "error"
    message: str


def _endpoint(url: str | None) -> str | None:
    """host[:port] of a URL - never userinfo, path or query."""
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"//{url}")
    if not parsed.hostname:
        return None
    return f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname


def _hostname(url: str | None) -> str | None:
    return urlparse(url).hostname if url else None


def _database_name(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).path.lstrip("/") or None


def prompt_versions(settings: Settings) -> dict[str, str]:
    """Prompt/response-schema versions the configured providers will stamp on
    their results (the fake providers report "none")."""
    versions: dict[str, str] = {}
    if settings.change_classifier_provider == "openai_compatible":
        from app.ai.semantic_change import OpenAICompatibleChangeClassifier as Classifier

        versions["disclosure_classification"] = Classifier.prompt_version
        versions["disclosure_classification_batch"] = Classifier.batch_prompt_version
    if settings.claim_extractor_provider == "openai_compatible":
        from app.ai.financial_claims import OpenAICompatibleClaimExtractor as Extractor

        versions["claim_extraction"] = Extractor.prompt_version
        versions["claim_extraction_batch"] = Extractor.batch_prompt_version
    return versions


def runtime_summary(settings: Settings, role: str) -> dict[str, Any]:
    batching = BatchingConfig.from_settings(settings)
    shared: dict[str, Any] = {
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "reranker_enabled": settings.reranker_enabled,
        "change_classifier": [
            settings.change_classifier_provider,
            settings.change_classifier_model,
        ],
        "claim_extractor": [settings.claim_extractor_provider, settings.claim_extractor_model],
        "batch_max_items": batching.max_items,
        "batch_input_token_budget": batching.input_token_budget,
        "batch_token_safety_margin": batching.safety_margin,
        "batch_multi_item_requests": settings.ai_batch_multi_item_requests,
        "comparison_version": settings.comparison_version,
        "analysis_workflow_version": settings.analysis_workflow_version,
        "analysis_graph_version": settings.analysis_graph_version,
        "prompt_versions": prompt_versions(settings),
        "checkpoint_provider": settings.workflow_checkpoint_provider,
        "object_storage_provider": settings.object_storage_provider,
    }
    return {
        "role": role,
        "environment": settings.environment,
        "app_profile": settings.app_profile,
        # Equal on API and worker when they are configured consistently.
        "config_fingerprint": canonical_hash(shared)[:12],
        **shared,
        "batch_effective_budget": batching.effective_token_budget,
        "analysis_workflow_limit_seconds": int(settings.analysis_workflow_time_limit_seconds),
        "worker_default_limit_seconds": int(settings.worker_default_time_limit_seconds),
        "ai_provider_host": _endpoint(settings.ai_provider_base_url),
        "ai_provider_api_key_configured": bool(settings.ai_provider_api_key),
        "ai_provider_max_retries": settings.ai_provider_max_retries,
        "ai_provider_chat_delay_seconds": settings.ai_provider_chat_delay_seconds,
        "database_host": _endpoint(settings.database_url),
        "database_name": _database_name(settings.database_url),
        "redis_host": _endpoint(settings.redis_url),
        "storage_endpoint": (
            _endpoint(settings.minio_endpoint)
            if settings.object_storage_provider == "minio"
            else None
        ),
    }


def runtime_notes(settings: Settings, role: str) -> list[RuntimeNote]:
    """Configuration problems that would only show up later, mid-run."""
    notes: list[RuntimeNote] = []

    def add(level: str, message: str) -> None:
        notes.append(RuntimeNote(level, message))

    ai_providers = {
        "CHANGE_CLASSIFIER_PROVIDER": settings.change_classifier_provider,
        "CLAIM_EXTRACTOR_PROVIDER": settings.claim_extractor_provider,
    }
    if "openai_compatible" in ai_providers.values() and not settings.ai_provider_api_key:
        add(
            "error",
            "an openai_compatible AI provider is selected but AI_PROVIDER_API_KEY is unset",
        )
    if settings.analysis_workflow_time_limit_seconds <= settings.worker_default_time_limit_seconds:
        add(
            "warning",
            "ANALYSIS_WORKFLOW_TIME_LIMIT_SECONDS is not longer than the default worker limit; "
            "a full analysis can be killed mid-classification (progress is saved and resumes).",
        )
    if settings.workflow_checkpoint_provider != "postgres" and role == "worker":
        add(
            "warning",
            "WORKFLOW_CHECKPOINT_PROVIDER is not postgres: LangGraph checkpoints (human-review "
            "resume) do not survive a worker restart. Batch progress is stored in the database "
            "regardless.",
        )
    if settings.is_production:
        if _hostname(settings.database_url) in _LOCAL_HOSTS:
            add("error", "production DATABASE_URL points at localhost")
        if _hostname(settings.redis_url) in _LOCAL_HOSTS:
            add("error", "production REDIS_URL points at localhost")
        if settings.object_storage_provider != "minio":
            add("warning", "production should use OBJECT_STORAGE_PROVIDER=minio (shared storage)")
    elif role == "worker" and settings.object_storage_provider == "filesystem":
        add(
            "warning",
            "filesystem object storage is per-machine: an API and worker on different hosts "
            "will not see each other's stored filings",
        )
    if settings.embedding_provider == "fake" and not settings.is_production:
        add("warning", "EMBEDDING_PROVIDER=fake: matching results are not meaningful")
    return notes


def log_runtime_config(settings: Settings, role: str, logger: Any) -> None:
    """Log the summary (and any notes) once, e.g. at API/worker startup."""
    summary = runtime_summary(settings, role)
    logger.info("runtime_config", **summary)
    for note in runtime_notes(settings, role):
        log = logger.error if note.level == "error" else logger.warning
        log("runtime_config_note", role=role, message=note.message)
