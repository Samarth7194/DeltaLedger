from __future__ import annotations

import json

import pytest

from app.ai.contradictions import (
    ContradictionClassifierInput,
    create_contradiction_classifier,
)
from app.ai.embeddings import create_embedding_service
from app.ai.financial_claims import create_claim_extractor
from app.ai.semantic_change import ChangeClassificationRequest, create_change_classifier
from app.core.config import Settings
from app.evaluation.monitoring import ai_call_monitoring
from app.evaluation.providers import provider_manifest


class _Response:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class _Client:
    payloads: list[dict[str, object]] = []
    requests: list[dict[str, object]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, *args, **kwargs) -> _Response:
        self.requests.append(
            {
                "url": args[0] if args else None,
                "json": kwargs.get("json"),
            }
        )
        return _Response(self.payloads.pop(0))


def _settings(**overrides) -> Settings:
    return Settings(
        ai_provider_api_key="test-key",
        ai_provider_base_url="https://provider.example/v1",
        ai_provider_input_token_cost_usd_per_million=1.0,
        ai_provider_output_token_cost_usd_per_million=2.0,
        **overrides,
    )


def test_provider_manifest_blocks_openai_compatible_without_key() -> None:
    manifest = provider_manifest(
        Settings(
            change_classifier_provider="openai_compatible",
            ai_provider_api_key=None,
        )
    )

    entries = {entry["provider_type"]: entry for entry in manifest["entries"]}

    assert manifest["real_provider_evaluation"] == "BLOCKED_EXTERNAL_CREDENTIAL"
    assert entries["disclosure_change_classifier"]["status"] == "BLOCKED_EXTERNAL_CREDENTIAL"
    assert "AI_PROVIDER_API_KEY" in entries["disclosure_change_classifier"]["reason"]


@pytest.mark.asyncio
async def test_openai_compatible_change_classifier_parses_metadata(monkeypatch) -> None:
    _Client.payloads = [
        _chat_payload(
            {
                "change_type": "weakened",
                "summary": "Disclosure became more conditional.",
                "explanation": "The current text added may.",
                "changed_spans": [],
                "confidence": 0.81,
                "risk_category": "liquidity",
                "materiality_reason": "Risk wording changed.",
            }
        )
    ]
    _Client.requests = []
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _Client)
    classifier = create_change_classifier(
        _settings(
            change_classifier_provider="openai_compatible",
            change_classifier_model="test-chat-model",
        )
    )

    result = await classifier.classify(
        ChangeClassificationRequest(
            previous_text="We will have sufficient cash.",
            current_text="We may need additional financing.",
            deterministic_signals={"uncertainty_added": True},
            section_metadata={},
            allowed_labels=["weakened"],
        )
    )

    assert result.change_type == "weakened"
    assert result.inference_metadata["provider"] == "openai_compatible"
    assert result.inference_metadata["input_tokens"] == 10
    assert result.inference_metadata["estimated_cost_usd"] == 0.00005


@pytest.mark.asyncio
async def test_openai_compatible_chat_request_omits_deprecated_sampling_params(
    monkeypatch,
) -> None:
    _Client.payloads = [
        _chat_payload(
            {
                "change_type": "weakened",
                "summary": "Disclosure became more conditional.",
                "explanation": "The current text added may.",
                "changed_spans": [],
                "confidence": 0.81,
                "risk_category": "liquidity",
                "materiality_reason": "Risk wording changed.",
            }
        )
    ]
    _Client.requests = []
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _Client)
    classifier = create_change_classifier(
        _settings(
            change_classifier_provider="openai_compatible",
            change_classifier_model="gemini-3.6-flash",
        )
    )

    await classifier.classify(
        ChangeClassificationRequest(
            previous_text="We will have sufficient cash.",
            current_text="We may need additional financing.",
            deterministic_signals={"uncertainty_added": True},
            section_metadata={},
            allowed_labels=["weakened"],
        )
    )

    payload = _Client.requests[0]["json"]
    assert payload["model"] == "gemini-3.6-flash"
    assert payload["response_format"] == {"type": "json_object"}
    system_prompt = payload["messages"][0]["content"]
    assert "request allowed_labels" in system_prompt
    assert "liquidity, revenue_guidance, litigation, other" in system_prompt
    assert "changed_spans as an array of objects" in system_prompt
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "top_k" not in payload


@pytest.mark.asyncio
async def test_openai_compatible_claim_extractor_parses_claims(monkeypatch) -> None:
    _Client.payloads = [
        _chat_payload(
            {
                "claims": [
                    {
                        "claim_text": "Revenue increased 12% year over year.",
                        "canonical_metric_name": "revenue",
                        "claim_type": "percentage_change",
                        "direction": "increase",
                        "reported_change": "12",
                        "reported_change_unit": "percent",
                        "confidence": "0.90",
                    }
                ]
            }
        )
    ]
    _Client.requests = []
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _Client)
    extractor = create_claim_extractor(
        "openai_compatible",
        _settings(claim_extractor_model="test-claim-model"),
    )

    claims = await extractor.extract_claims(
        "Revenue increased 12% year over year.",
        {},
        ["revenue"],
    )

    assert len(claims) == 1
    assert claims[0].canonical_metric_name == "revenue"
    assert claims[0].original_output["inference_metadata"]["model"] == "test-claim-model"


@pytest.mark.asyncio
async def test_openai_compatible_contradiction_classifier_parses_output(monkeypatch) -> None:
    _Client.payloads = [
        _chat_payload(
            {
                "is_candidate": True,
                "contradiction_type": "numerical_claim_contradiction",
                "summary": "Claim differs from calculated value.",
                "explanation": "The reported percentage does not match.",
                "severity": "medium",
                "confidence": 0.72,
                "limitations": [],
            }
        )
    ]
    _Client.requests = []
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _Client)
    classifier = create_contradiction_classifier(
        "openai_compatible",
        _settings(contradiction_classifier_model="test-contradiction-model"),
    )

    result = await classifier.classify(
        ContradictionClassifierInput(
            narrative_claim="Revenue increased 20%.",
            allowed_labels=["numerical_claim_contradiction"],
        )
    )

    assert result.is_candidate is True
    assert result.inference_metadata["provider_type"] == "contradiction_classifier"


@pytest.mark.asyncio
async def test_openai_compatible_embedding_provider_parses_vectors(monkeypatch) -> None:
    _Client.payloads = [
        {
            "model": "test-embedding-model",
            "data": [
                {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                {"index": 1, "embedding": [0.0, 1.0, 0.0]},
            ],
            "usage": {"prompt_tokens": 2, "total_tokens": 2},
        }
    ]
    _Client.requests = []
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _Client)
    service = create_embedding_service(
        _settings(
            embedding_provider="openai_compatible",
            embedding_model="test-embedding-model",
            embedding_model_name="test-embedding-model",
            embedding_dimension=3,
            embedding_dimensions=3,
        )
    )

    vectors = await service.embed_documents(["a", "b"])

    assert len(vectors) == 2
    assert vectors[0] == [1.0, 0.0, 0.0]
    assert _Client.requests[0]["json"] == {
        "model": "test-embedding-model",
        "input": ["a", "b"],
        "dimensions": 3,
    }


@pytest.mark.asyncio
async def test_openai_compatible_embedding_request_uses_configured_1024_dimensions(
    monkeypatch,
) -> None:
    _Client.payloads = [
        {
            "model": "gemini-embedding-001",
            "data": [{"index": 0, "embedding": [1.0] + [0.0] * 1023}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
    ]
    _Client.requests = []
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _Client)
    service = create_embedding_service(
        _settings(
            embedding_provider="openai_compatible",
            embedding_model="gemini-embedding-001",
            embedding_model_name="gemini-embedding-001",
            embedding_dimension=1024,
            embedding_dimensions=1024,
        )
    )

    vectors = await service.embed_documents(["cash flow disclosure"])

    assert len(vectors[0]) == 1024
    assert dict(_Client.requests[0]["json"])["dimensions"] == 1024


@pytest.mark.asyncio
async def test_openai_compatible_embedding_dimension_mismatch_fails_clearly(monkeypatch) -> None:
    _Client.payloads = [
        {
            "model": "gemini-embedding-001",
            "data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
    ]
    _Client.requests = []
    monkeypatch.setattr("app.ai.openai_compatible.httpx.AsyncClient", _Client)
    service = create_embedding_service(
        _settings(
            embedding_provider="openai_compatible",
            embedding_model="gemini-embedding-001",
            embedding_model_name="gemini-embedding-001",
            embedding_dimension=1024,
            embedding_dimensions=1024,
        )
    )

    with pytest.raises(ValueError, match="Embedding vector has dimension 3; expected 1024"):
        await service.embed_documents(["cash flow disclosure"])


def test_ai_monitoring_summarizes_inference_metadata_and_review_outcomes() -> None:
    summary = ai_call_monitoring(
        [
            {
                "review_status": "approved",
                "original_model_output": {
                    "inference_metadata": {
                        "provider": "openai_compatible",
                        "model": "model-a",
                        "success": True,
                        "parse_status": "valid",
                        "latency_ms": 50,
                        "retry_count": 1,
                        "total_tokens": 12,
                        "estimated_cost_usd": 0.01,
                    }
                },
            },
            {
                "review_status": "rejected",
                "inference_metadata": {
                    "provider": "openai_compatible",
                    "model": "model-a",
                    "success": False,
                    "parse_status": "invalid",
                    "latency_ms": 70,
                },
            },
        ]
    )

    assert summary["failure_rate"]["value"] == 0.5
    assert summary["invalid_structured_output_rate"]["value"] == 0.5
    assert summary["retry_count"] == 1
    assert summary["quality_signals"]["review_outcomes"] == {"approved": 1, "rejected": 1}


def _chat_payload(content: dict[str, object]) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "model": "resolved-model",
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
