from __future__ import annotations

from app.cli.production_audit import production_audit
from app.core.config import Settings

SECRET = "0123456789abcdef0123456789abcdef"


def test_production_audit_reports_local_profile_without_claiming_deployment() -> None:
    result = production_audit(Settings())

    assert result["status"] == "not_production"
    assert result["environment"] == "local"


def test_production_audit_accepts_safe_production_shape_with_explicit_demo_override() -> None:
    result = production_audit(
        Settings(
            app_profile="production",
            environment="production",
            cors_allowed_origins="https://app.example.com",
            workflow_checkpoint_provider="postgres",
            object_storage_provider="minio",
            minio_access_key="prod-access",
            minio_secret_key="prod-secret",
            sec_user_agent="DeltaLedgerAI/0.1 ops@deltaledger.local",
            readiness_dependency_checks_enabled=True,
            auth_enabled=True,
            auth_secret_key=SECRET,
            allow_fake_models_in_production=True,
        )
    )

    assert result["status"] == "ready"
    assert {item["status"] for item in result["checks"]} == {"ok"}
