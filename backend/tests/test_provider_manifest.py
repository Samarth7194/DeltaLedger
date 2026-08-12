from __future__ import annotations

from app.core.config import Settings
from app.evaluation.providers import provider_manifest


def test_provider_manifest_labels_default_fake_configuration() -> None:
    manifest = provider_manifest(Settings())

    entries = {entry["provider_type"]: entry for entry in manifest["entries"]}

    assert manifest["real_provider_evaluation"] == "NOT_EVALUATED_FAKE_ONLY_CONFIGURATION"
    assert entries["embedding"]["status"] == "FAKE_CI_PROVIDER"
    assert entries["disclosure_change_classifier"]["status"] == "FAKE_CI_PROVIDER"
    assert entries["financial_claim_extractor"]["status"] == "FAKE_CI_PROVIDER"
    assert entries["contradiction_classifier"]["status"] == "FAKE_CI_PROVIDER"
    assert entries["reranker"]["status"] == "NOT_CONFIGURED"


def test_provider_manifest_reports_missing_external_embedding_credential() -> None:
    manifest = provider_manifest(
        Settings(
            embedding_provider="huggingface_inference",
            hf_token=None,
        )
    )

    entries = {entry["provider_type"]: entry for entry in manifest["entries"]}

    assert manifest["real_provider_evaluation"] == "BLOCKED_EXTERNAL_CREDENTIAL"
    assert entries["embedding"]["status"] == "BLOCKED_EXTERNAL_CREDENTIAL"
    assert "HF_TOKEN" in entries["embedding"]["reason"]
