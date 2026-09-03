from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.ai.openai_compatible import OpenAICompatibleClient
from app.core.config import Settings

ChangeType = Literal["added", "removed", "strengthened", "weakened", "no_material_change"]
RiskCategory = Literal["liquidity", "revenue_guidance", "litigation", "other"]


class ChangeClassificationRequest(BaseModel):
    previous_text: str | None
    current_text: str | None
    deterministic_signals: dict[str, object]
    section_metadata: dict[str, object]
    allowed_labels: list[str]


class ChangeClassificationResult(BaseModel):
    change_type: ChangeType
    summary: str
    explanation: str
    changed_spans: list[dict[str, object]] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_category: RiskCategory
    materiality_reason: str
    inference_metadata: dict[str, object] = Field(default_factory=dict)


class ChangeClassifierProvider(Protocol):
    model_name: str
    model_version: str
    prompt_version: str

    async def classify(
        self, request: ChangeClassificationRequest
    ) -> ChangeClassificationResult: ...


class DeterministicFakeChangeClassifier:
    model_name = "deterministic-disclosure-change"
    model_version = "phase3-v1"
    prompt_version = "none"

    async def classify(self, request: ChangeClassificationRequest) -> ChangeClassificationResult:
        signals = request.deterministic_signals
        previous = request.previous_text
        current = request.current_text
        risk = classify_risk(current or previous or "", request.section_metadata)
        if previous is None:
            change_type: ChangeType = "added"
            summary = "Disclosure was added."
            confidence = 0.92
        elif current is None:
            change_type = "removed"
            summary = "Disclosure was removed."
            confidence = 0.92
        elif signals.get("normalized_equal"):
            change_type = "no_material_change"
            summary = "No material semantic change detected."
            confidence = 0.9
        elif _has_any(
            signals,
            "uncertainty_added",
            "conditional_added",
            "negation_added",
            "risk_terms_added",
        ) or _has_any(signals, "commitment_removed"):
            change_type = "weakened"
            summary = "Current disclosure introduces weaker or more conditional language."
            confidence = 0.84
        elif _has_any(
            signals,
            "uncertainty_removed",
            "commitment_added",
            "negation_removed",
            "risk_terms_removed",
        ):
            change_type = "strengthened"
            summary = "Current disclosure uses stronger or less risky language."
            confidence = 0.82
        else:
            change_type = "no_material_change"
            summary = "Wording changed without a material semantic signal."
            confidence = 0.72
        return ChangeClassificationResult(
            change_type=change_type,
            summary=summary,
            explanation=_explanation(change_type, signals),
            changed_spans=_changed_spans(previous, current),
            confidence=confidence,
            risk_category=risk,
            materiality_reason="Deterministic signal mix and risk category were used.",
        )


class OpenAICompatibleChangeClassifier:
    prompt_version = "disclosure-change-json-v1"

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.change_classifier_model
        self.model_version = settings.change_classifier_model
        self._client = OpenAICompatibleClient(
            settings,
            provider_type="disclosure_change_classifier",
        )

    async def classify(self, request: ChangeClassificationRequest) -> ChangeClassificationResult:
        result, metadata, raw = await self._client.chat_json(
            model=self.model_name,
            prompt_version=self.prompt_version,
            system_prompt=(
                "Classify SEC filing disclosure changes. Return only a single JSON "
                "object with ALL of the following fields present -- every field "
                "below is REQUIRED in every response, with no field ever omitted:\n"
                "- change_type: one of the request's allowed_labels\n"
                "- summary: a short plain-language summary of the change\n"
                "- explanation: why the change was classified this way\n"
                "- changed_spans: an array of objects, not strings; each object "
                "should include text and side when available\n"
                "- confidence: a number between 0.0 and 1.0\n"
                "- risk_category: exactly one of liquidity, revenue_guidance, "
                "litigation, other\n"
                "- materiality_reason: a short explanation of why this change is, "
                "or is not, material. This field is REQUIRED even when the change "
                "is minor, the reasoning is brief, or materiality_reason overlaps "
                "with explanation -- never omit it.\n"
                "Do not make legal conclusions. Do not include any text, "
                "commentary, or markdown outside the single JSON object."
            ),
            user_payload=request.model_dump(),
            response_model=ChangeClassificationResult,
        )
        result.inference_metadata = {
            **metadata.model_dump(),
            "response_id": raw.get("id"),
        }
        return result


def create_change_classifier(settings: Settings) -> ChangeClassifierProvider:
    if settings.change_classifier_provider == "fake":
        return DeterministicFakeChangeClassifier()
    if settings.change_classifier_provider == "openai_compatible":
        return OpenAICompatibleChangeClassifier(settings)
    raise ValueError(
        f"Unsupported change classifier provider: {settings.change_classifier_provider}"
    )


def classify_risk(text: str, section_metadata: dict[str, object] | None = None) -> RiskCategory:
    value = f"{section_metadata or {}} {text}".lower()
    liquidity_terms = [
        "cash",
        "liquidity",
        "credit facility",
        "borrowings",
        "financing",
        "debt covenant",
    ]
    revenue_terms = [
        "revenue",
        "sales",
        "demand",
        "guidance",
        "forecast",
        "orders",
        "backlog",
        "margin",
    ]
    litigation_terms = [
        "lawsuit",
        "litigation",
        "claim",
        "legal proceeding",
        "investigation",
        "settlement",
    ]
    if any(term in value for term in liquidity_terms):
        return "liquidity"
    if any(term in value for term in revenue_terms):
        return "revenue_guidance"
    if any(term in value for term in litigation_terms):
        return "litigation"
    return "other"


def _has_any(signals: dict[str, object], *keys: str) -> bool:
    return any(bool(signals.get(key)) for key in keys)


def _explanation(change_type: str, signals: dict[str, object]) -> str:
    return (
        f"Classified as {change_type} using deterministic additions/removals, "
        f"uncertainty, commitment, conditional, negation, risk, and numeric signals: {signals}"
    )


def _changed_spans(previous: str | None, current: str | None) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    if previous is None and current:
        spans.append({"text": current, "side": "current", "start": 0, "end": len(current)})
    elif current is None and previous:
        spans.append({"text": previous, "side": "previous", "start": 0, "end": len(previous)})
    return spans
