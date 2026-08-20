from __future__ import annotations

from dataclasses import asdict, dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class ProviderManifestEntry:
    provider_type: str
    provider: str
    model: str
    version: str
    status: str
    reason: str
    dimension: int | None = None
    prompt_version: str | None = None
    timeout_seconds: float | None = None
    batch_size: int | None = None


def provider_manifest(settings: Settings) -> dict[str, object]:
    entries = [
        _embedding_entry(settings),
        _reranker_entry(settings),
        ProviderManifestEntry(
            provider_type="disclosure_change_classifier",
            provider=settings.change_classifier_provider,
            model=settings.change_classifier_model,
            version=settings.comparison_version,
            prompt_version=_prompt_version(
                settings.change_classifier_provider,
                fake_version="none",
                real_version="disclosure-change-json-v1",
            ),
            timeout_seconds=settings.change_classifier_timeout,
            status=_provider_status(settings, settings.change_classifier_provider),
            reason=_provider_reason(settings, settings.change_classifier_provider),
        ),
        ProviderManifestEntry(
            provider_type="financial_claim_extractor",
            provider=settings.claim_extractor_provider,
            model=settings.claim_extractor_model,
            version="phase4-v1",
            prompt_version=_prompt_version(
                settings.claim_extractor_provider,
                fake_version="none",
                real_version="financial-claim-extraction-json-v1",
            ),
            timeout_seconds=settings.claim_extractor_timeout,
            status=_provider_status(settings, settings.claim_extractor_provider),
            reason=_provider_reason(settings, settings.claim_extractor_provider),
        ),
        ProviderManifestEntry(
            provider_type="metric_resolver",
            provider="deterministic",
            model="deterministic-metric-resolver",
            version="phase4-v1",
            status="DETERMINISTIC_LOCAL",
            reason="Metric resolver is implemented as deterministic local logic.",
        ),
        ProviderManifestEntry(
            provider_type="contradiction_classifier",
            provider=settings.contradiction_classifier_provider,
            model=settings.contradiction_classifier_model,
            version=settings.contradiction_policy_version,
            prompt_version="phase5-test-v1"
            if settings.contradiction_classifier_provider == "fake"
            else "contradiction-classifier-json-v1",
            timeout_seconds=settings.contradiction_classifier_timeout,
            status=_provider_status(settings, settings.contradiction_classifier_provider),
            reason=_provider_reason(settings, settings.contradiction_classifier_provider),
        ),
    ]
    return {
        "environment": settings.environment,
        "app_profile": settings.app_profile,
        "entries": [asdict(entry) for entry in entries],
        "real_provider_evaluation": _real_provider_evaluation_status(entries),
    }


def _embedding_entry(settings: Settings) -> ProviderManifestEntry:
    if settings.embedding_provider == "huggingface_inference" and not settings.hf_token:
        status = "BLOCKED_EXTERNAL_CREDENTIAL"
        reason = "HF_TOKEN is required for Hugging Face inference embeddings."
    elif settings.embedding_provider == "openai_compatible" and not settings.ai_provider_api_key:
        status = "BLOCKED_EXTERNAL_CREDENTIAL"
        reason = "AI_PROVIDER_API_KEY is required for OpenAI-compatible embeddings."
    else:
        status = _provider_status(settings, settings.embedding_provider)
        reason = _provider_reason(settings, settings.embedding_provider)
    return ProviderManifestEntry(
        provider_type="embedding",
        provider=settings.embedding_provider,
        model=settings.embedding_model,
        version=settings.embedding_model,
        dimension=settings.embedding_dimension,
        timeout_seconds=settings.embedding_timeout_seconds,
        batch_size=settings.embedding_batch_size,
        status=status,
        reason=reason,
    )


def _reranker_entry(settings: Settings) -> ProviderManifestEntry:
    if not settings.reranker_enabled:
        return ProviderManifestEntry(
            provider_type="reranker",
            provider=settings.reranker_provider,
            model=settings.reranker_model,
            version=settings.reranker_model,
            batch_size=settings.reranker_batch_size,
            timeout_seconds=settings.reranker_timeout_seconds,
            status="NOT_CONFIGURED",
            reason="Reranker is disabled.",
        )
    return ProviderManifestEntry(
        provider_type="reranker",
        provider=settings.reranker_provider,
        model=settings.reranker_model,
        version=settings.reranker_model,
        batch_size=settings.reranker_batch_size,
        timeout_seconds=settings.reranker_timeout_seconds,
        status=_provider_status(settings, settings.reranker_provider),
        reason=_provider_reason(settings, settings.reranker_provider),
    )


def _provider_status(settings: Settings, provider: str) -> str:
    if provider == "fake":
        return "FAKE_CI_PROVIDER"
    if provider == "openai_compatible" and not settings.ai_provider_api_key:
        return "BLOCKED_EXTERNAL_CREDENTIAL"
    return "CONFIGURED_LOCAL_OR_MANAGED_PROVIDER"


def _provider_reason(settings: Settings, provider: str) -> str:
    if provider == "fake":
        return "Deterministic fake provider is retained for offline CI."
    if provider == "openai_compatible" and not settings.ai_provider_api_key:
        return "AI_PROVIDER_API_KEY is required for OpenAI-compatible providers."
    if provider == "openai_compatible":
        return (
            "OpenAI-compatible HTTP provider is configured by endpoint, model, "
            "timeout, retry, and API-key environment variables."
        )
    return "Provider is configured; run explicit real-provider evaluation with secrets protected."


def _prompt_version(provider: str, *, fake_version: str, real_version: str) -> str:
    return real_version if provider == "openai_compatible" else fake_version


def _real_provider_evaluation_status(entries: list[ProviderManifestEntry]) -> str:
    if any(entry.status == "BLOCKED_EXTERNAL_CREDENTIAL" for entry in entries):
        return "BLOCKED_EXTERNAL_CREDENTIAL"
    if any(entry.status == "CONFIGURED_LOCAL_OR_MANAGED_PROVIDER" for entry in entries):
        return "READY_FOR_EXPLICIT_REAL_PROVIDER_RUN"
    return "NOT_EVALUATED_FAKE_ONLY_CONFIGURATION"
