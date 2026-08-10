from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

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


def create_contradiction_classifier(provider: str) -> ContradictionClassifierProvider:
    if provider == "fake":
        return DeterministicFakeContradictionClassifier()
    raise ValueError(f"Unsupported contradiction classifier provider: {provider}")
