from __future__ import annotations

import json

from pydantic import ValidationError

from app.core.config import Settings


def main() -> None:
    try:
        settings = Settings()
    except (ValidationError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "environment": "unknown",
                    "checks": [
                        {
                            "name": "configuration",
                            "status": "blocked",
                            "detail": _safe_detail(exc),
                        }
                    ],
                },
                sort_keys=True,
            )
        )
        raise SystemExit(1) from exc
    payload = production_audit(settings)
    print(json.dumps(payload, sort_keys=True))
    raise SystemExit(0 if payload["status"] in {"ready", "not_production"} else 1)


def production_audit(settings: Settings) -> dict[str, object]:
    checks = [
        _check("auth", settings.auth_enabled, "AUTH_ENABLED must be true in production."),
        _check(
            "storage",
            settings.object_storage_provider != "filesystem",
            "Production must use S3-compatible object storage.",
        ),
        _check(
            "checkpoint",
            settings.workflow_checkpoint_provider == "postgres",
            "Production workflow checkpoint provider must be postgres.",
        ),
        _check(
            "readiness",
            settings.readiness_dependency_checks_enabled,
            "Production readiness dependency checks must be enabled.",
        ),
        _check(
            "cors",
            all(origin.startswith("https://") for origin in settings.cors_origins),
            "Production CORS origins must use HTTPS.",
        ),
        _check(
            "model_providers",
            settings.allow_fake_models_in_production
            or not _fake_provider_names(settings),
            "Fake model providers are disabled unless explicitly allowed.",
        ),
    ]
    if not settings.is_production:
        return {
            "status": "not_production",
            "environment": settings.environment,
            "app_profile": settings.app_profile,
            "checks": checks,
        }
    status = "ready" if all(check["status"] == "ok" for check in checks) else "blocked"
    return {
        "status": status,
        "environment": settings.environment,
        "app_profile": settings.app_profile,
        "checks": checks,
    }


def _check(name: str, ok: bool, detail: str) -> dict[str, str]:
    return {"name": name, "status": "ok" if ok else "blocked", "detail": "ok" if ok else detail}


def _fake_provider_names(settings: Settings) -> list[str]:
    providers = {
        "EMBEDDING_PROVIDER": settings.embedding_provider,
        "CHANGE_CLASSIFIER_PROVIDER": settings.change_classifier_provider,
        "CLAIM_EXTRACTOR_PROVIDER": settings.claim_extractor_provider,
        "CONTRADICTION_CLASSIFIER_PROVIDER": settings.contradiction_classifier_provider,
    }
    if settings.reranker_enabled:
        providers["RERANKER_PROVIDER"] = settings.reranker_provider
    return [name for name, value in providers.items() if value == "fake"]


def _safe_detail(exc: Exception) -> str:
    text = str(exc)
    if "://" in text:
        return exc.__class__.__name__
    return text


if __name__ == "__main__":
    main()
