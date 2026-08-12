from __future__ import annotations

import pytest

from app.core.config import Settings
from app.demo.dataset import DEMO_TICKER, build_demo_manifest
from app.demo.seed import seed_offline_demo


def test_demo_manifest_contains_full_reviewable_scenario() -> None:
    manifest = build_demo_manifest()

    assert manifest["company"]["ticker"] == DEMO_TICKER
    assert manifest["filings"]["previous"]["accession_number"]
    assert manifest["filings"]["current"]["accession_number"]
    assert manifest["expected_outputs"]["disclosure_change"]["change_type"] == "weakened"
    assert (
        manifest["expected_outputs"]["xbrl_verification"]["verification_status"]
        == "contradicted"
    )
    assert manifest["expected_outputs"]["potential_inconsistency"]["requires_human_review"] is True
    assert manifest["expected_outputs"]["report"]["status"] == "finalized"


@pytest.mark.asyncio
async def test_demo_reset_refuses_to_run_in_production() -> None:
    settings = Settings(
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
        auth_secret_key="0123456789abcdef0123456789abcdef",
        allow_fake_models_in_production=True,
    )

    with pytest.raises(ValueError, match="Refusing to reset demo data"):
        await seed_offline_demo(None, settings, reset=True)  # type: ignore[arg-type]
