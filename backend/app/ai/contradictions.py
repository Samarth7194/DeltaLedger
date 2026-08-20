from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.ai.openai_compatible import OpenAICompatibleClient
from app.core.config import Settings

AllowedContradictionType = Literal[
    "direction_contradiction",
    "magnitude_overstatement",
    "magnitude_understatement",
    "unsupported_qualitative_claim",
    "narrative_cross_section_inconsistency",
    "temporal_narrative_inconsistency",
    "numerical_claim_contradiction",
]
AllowedSeverity = Literal["low", "medium", "high", "critical"]


class ContradictionClassifierInput(BaseModel):
    narrative_claim: str
    deterministic_signals: dict[str, Any] = Field(default_factory=dict)
    financial_verification: dict[str, Any] | None = None
    previous_passage: str | None = None
    current_passage: str | None = None
    allowed_labels: list[AllowedContradictionType]
    metric_context: dict[str, Any] = Field(default_factory=dict)


class ContradictionClassifierOutput(BaseModel):
    is_candidate: bool
    contradiction_type: AllowedContradictionType | None = None
    summary: str
    explanation: str
    severity: AllowedSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)
    inference_metadata: dict[str, Any] = Field(default_factory=dict)


class ContradictionClassifierProvider(ABC):
    model_name = "abstract-contradiction-classifier"
    model_version = "unknown"
    prompt_version = "unknown"

    @abstractmethod
    async def classify(
        self,
        payload: ContradictionClassifierInput,
    ) -> ContradictionClassifierOutput:
        raise NotImplementedError


class DeterministicFakeContradictionClassifier(ContradictionClassifierProvider):
    model_name = "deterministic-fake-contradiction-classifier"
    model_version = "phase5-test-v1"
    prompt_version = "phase5-test-v1"

    async def classify(
        self,
        payload: ContradictionClassifierInput,
    ) -> ContradictionClassifierOutput:
        signal_type = payload.deterministic_signals.get("contradiction_type")
        label = signal_type if signal_type in payload.allowed_labels else payload.allowed_labels[0]
        is_candidate = bool(payload.deterministic_signals.get("is_candidate", True))
        return ContradictionClassifierOutput(
            is_candidate=is_candidate,
            contradiction_type=label,
            summary="Potential inconsistency identified for analyst review.",
            explanation=(
                "The deterministic evidence indicates a possible inconsistency; "
                "this classifier does not add unsupported accusations."
            ),
            severity="low",
            confidence=0.50,
            limitations=["Deterministic fake classifier used for CI and unit tests."],
        )


class OpenAICompatibleContradictionClassifier(ContradictionClassifierProvider):
    prompt_version = "contradiction-classifier-json-v1"

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.contradiction_classifier_model
        self.model_version = settings.contradiction_classifier_model
        self._client = OpenAICompatibleClient(
            settings,
            provider_type="contradiction_classifier",
        )

    async def classify(
        self,
        payload: ContradictionClassifierInput,
    ) -> ContradictionClassifierOutput:
        result, metadata, raw = await self._client.chat_json(
            model=self.model_name,
            prompt_version=self.prompt_version,
            system_prompt=(
                "Classify possible financial disclosure inconsistencies for analyst review. "
                "Return only JSON matching the schema. Do not assert fraud or wrongdoing."
            ),
            user_payload=payload.model_dump(),
            response_model=ContradictionClassifierOutput,
        )
        result.inference_metadata = {
            **metadata.model_dump(),
            "response_id": raw.get("id"),
        }
        return result


def create_contradiction_classifier(
    provider: str,
    settings: Settings | None = None,
) -> ContradictionClassifierProvider:
    if provider == "fake":
        return DeterministicFakeContradictionClassifier()
    if provider == "openai_compatible":
        if settings is None:
            raise ValueError(
                "Settings are required for CONTRADICTION_CLASSIFIER_PROVIDER=openai_compatible"
            )
        return OpenAICompatibleContradictionClassifier(settings)
    raise ValueError(f"Unsupported contradiction classifier provider: {provider}")
