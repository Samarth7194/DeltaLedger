from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field

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


def create_claim_extractor(provider_name: str) -> ClaimExtractorProvider:
    if provider_name == "fake":
        return DeterministicFakeClaimExtractor()
    raise ValueError(f"Unsupported claim extractor provider: {provider_name}")
