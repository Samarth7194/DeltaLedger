from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.ai.openai_compatible import OpenAICompatibleClient
from app.core.config import Settings

ClaimType = Literal[
    "absolute_value",
    "directional_change",
    "percentage_change",
    "percentage_point_change",
    "ratio_change",
    "comparative_statement",
    "qualitative_financial_claim",
]
Direction = Literal["increase", "decrease", "unchanged", "positive", "negative", "unknown"]


class FinancialClaimExtraction(BaseModel):
    claim_text: str
    canonical_metric_name: str | None
    claim_type: ClaimType
    direction: Direction | None = None
    reported_value: Decimal | None = None
    reported_unit: str | None = None
    reported_change: Decimal | None = None
    reported_change_unit: str | None = None
    comparison_basis: str | None = None
    comparison_text: str | None = None
    qualifiers: dict[str, object] = Field(default_factory=dict)
    confidence: Decimal = Field(ge=0, le=1)
    original_output: dict[str, object] = Field(default_factory=dict)


class ClaimExtractorProvider(Protocol):
    model_name: str
    model_version: str
    prompt_version: str

    async def extract_claims(
        self,
        text: str,
        section_metadata: dict[str, object],
        allowed_metrics: list[str],
    ) -> list[FinancialClaimExtraction]: ...


class DeterministicFakeClaimExtractor:
    model_name = "deterministic-financial-claim-extractor"
    model_version = "phase4-v1"
    prompt_version = "none"

    async def extract_claims(
        self,
        text: str,
        section_metadata: dict[str, object],
        allowed_metrics: list[str],
    ) -> list[FinancialClaimExtraction]:
        return []


class ClaimExtractionResponse(BaseModel):
    claims: list[FinancialClaimExtraction] = Field(default_factory=list)


class OpenAICompatibleClaimExtractor:
    prompt_version = "financial-claim-extraction-json-v1"

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.claim_extractor_model
        self.model_version = settings.claim_extractor_model
        self._client = OpenAICompatibleClient(
            settings,
            provider_type="financial_claim_extractor",
        )

    async def extract_claims(
        self,
        text: str,
        section_metadata: dict[str, object],
        allowed_metrics: list[str],
    ) -> list[FinancialClaimExtraction]:
        result, metadata, raw = await self._client.chat_json(
            model=self.model_name,
            prompt_version=self.prompt_version,
            system_prompt=(
                "Extract factual financial claims from SEC filing text. Return only JSON "
                "with a claims array. Use null for unknown values and never infer facts "
                "not present in the text."
            ),
            user_payload={
                "text": text,
                "section_metadata": section_metadata,
                "allowed_metrics": allowed_metrics,
            },
            response_model=ClaimExtractionResponse,
        )
        inference_metadata = {
            **metadata.model_dump(),
            "response_id": raw.get("id"),
        }
        for claim in result.claims:
            claim.original_output = {
                **claim.original_output,
                "inference_metadata": inference_metadata,
            }
        return result.claims


def create_claim_extractor(
    provider_name: str,
    settings: Settings | None = None,
) -> ClaimExtractorProvider:
    if provider_name == "fake":
        return DeterministicFakeClaimExtractor()
    if provider_name == "openai_compatible":
        if settings is None:
            raise ValueError("Settings are required for CLAIM_EXTRACTOR_PROVIDER=openai_compatible")
        return OpenAICompatibleClaimExtractor(settings)
    raise ValueError(f"Unsupported claim extractor provider: {provider_name}")
