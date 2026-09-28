from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.ai.batching import canonical_hash, estimate_payload_tokens, estimate_tokens
from app.ai.openai_compatible import OpenAICompatibleClient, StructuredOutputError
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


class ClaimBatchItem(BaseModel):
    """One passage in a multi-item extraction request. `item_id` is the
    stable id the response must echo back."""

    item_id: str
    text: str
    section_metadata: dict[str, object] = Field(default_factory=dict)


def claim_item_tokens(text: str, section_metadata: dict[str, object]) -> int:
    """Estimated input tokens one passage adds to a multi-item request."""
    return estimate_tokens(text) + estimate_payload_tokens(section_metadata)


class BatchClaimExtractorProvider(ClaimExtractorProvider, Protocol):
    batch_prompt_version: str

    async def extract_claims_batch(
        self,
        items: Sequence[ClaimBatchItem],
        allowed_metrics: list[str],
    ) -> dict[str, list[FinancialClaimExtraction] | None]: ...

    def batch_fixed_overhead_tokens(self, allowed_metrics: list[str]) -> int: ...


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


class BatchClaimExtractionResponse(BaseModel):
    """Envelope of a multi-item response; entries stay raw so each item is
    validated independently (see `extract_claims_batch`)."""

    items: list[dict[str, object]]


_BATCH_CLAIM_SYSTEM_PROMPT = (
    "Extract factual financial claims from SEC filing text. The request holds "
    "several independent items, each with its own item_id. Extract claims for "
    "every item on its own; never mix claims between items. Return only JSON "
    'of the form {"items": [{"item_id": "...", "claims": [...]}]} with exactly '
    "one entry per input item, copying each item_id exactly as given and "
    "always including a claims array (empty when the item has no claims). Use "
    "null for unknown values and never infer facts not present in the text."
)


_SINGLE_CLAIM_SYSTEM_PROMPT = (
    "Extract factual financial claims from SEC filing text. Return only JSON "
    "with a claims array. Use null for unknown values and never infer facts "
    "not present in the text."
)


# See the matching note in semantic_change: the prompt text hash is folded into
# the version strings so an edited prompt cannot silently reuse old results.
_CLAIM_PROMPT_FINGERPRINT = canonical_hash(
    [_SINGLE_CLAIM_SYSTEM_PROMPT, _BATCH_CLAIM_SYSTEM_PROMPT]
)


class OpenAICompatibleClaimExtractor:
    prompt_version = f"financial-claim-extraction-json-v1+{_CLAIM_PROMPT_FINGERPRINT[:8]}"
    batch_prompt_version = (
        f"financial-claim-extraction-batch-json-v1+{_CLAIM_PROMPT_FINGERPRINT[:8]}"
    )
    prompt_fingerprint = _CLAIM_PROMPT_FINGERPRINT

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.claim_extractor_model
        self.model_version = settings.claim_extractor_model
        self._client = OpenAICompatibleClient(
            settings,
            provider_type="financial_claim_extractor",
        )

    def batch_fixed_overhead_tokens(self, allowed_metrics: list[str]) -> int:
        """Per-request input cost that does not depend on the items."""
        return estimate_tokens(_BATCH_CLAIM_SYSTEM_PROMPT) + estimate_payload_tokens(
            allowed_metrics
        )

    async def extract_claims_batch(
        self,
        items: Sequence[ClaimBatchItem],
        allowed_metrics: list[str],
    ) -> dict[str, list[FinancialClaimExtraction] | None]:
        """Extract claims for several passages in one request.

        One entry per requested item_id: its validated claims, or None when
        the provider gave nothing usable *for that item* (missing, duplicated,
        no `claims` array, or schema-invalid) so the caller retries just it.
        Provider-level failures raise ProviderRequestError and are not
        swallowed.
        """
        requested = [item.item_id for item in items]
        outcomes: dict[str, list[FinancialClaimExtraction] | None] = dict.fromkeys(requested)
        if not items:
            return outcomes
        try:
            response, metadata, raw = await self._client.chat_json(
                model=self.model_name,
                prompt_version=self.batch_prompt_version,
                system_prompt=_BATCH_CLAIM_SYSTEM_PROMPT,
                user_payload={
                    "allowed_metrics": allowed_metrics,
                    "items": [item.model_dump() for item in items],
                },
                response_model=BatchClaimExtractionResponse,
            )
        except StructuredOutputError:
            return outcomes
        inference_metadata = {
            **metadata.model_dump(),
            "response_id": raw.get("id"),
            "batch_size": len(items),
        }
        by_id: dict[str, list[dict[str, object]]] = {}
        for entry in response.items:
            item_id = entry.get("item_id")
            if isinstance(item_id, str):
                by_id.setdefault(item_id, []).append(entry)
        for item_id in requested:
            entries = by_id.get(item_id, [])
            if len(entries) != 1 or "claims" not in entries[0]:
                continue
            try:
                parsed = ClaimExtractionResponse.model_validate({"claims": entries[0]["claims"]})
            except ValidationError:
                continue
            for claim in parsed.claims:
                claim.original_output = {
                    **claim.original_output,
                    "inference_metadata": inference_metadata,
                }
            outcomes[item_id] = parsed.claims
        return outcomes

    async def extract_claims(
        self,
        text: str,
        section_metadata: dict[str, object],
        allowed_metrics: list[str],
    ) -> list[FinancialClaimExtraction]:
        result, metadata, raw = await self._client.chat_json(
            model=self.model_name,
            prompt_version=self.prompt_version,
            system_prompt=_SINGLE_CLAIM_SYSTEM_PROMPT,
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
