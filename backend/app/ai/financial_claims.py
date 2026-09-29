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


# v2 (2026-09): the v1 prompt never named a single field, so the model
# invented its own shape (e.g. {"metric": ..., "value": ..., "period": ...})
# instead of the fields FinancialClaimExtraction actually requires - a live
# evaluation on gemini-3.5-flash-lite found canonical_metric_accuracy of 0.067
# against a 0.917 deterministic baseline, with 32/60 responses failing schema
# validation outright. See docs/claim-extraction-prompt-fix.md.
_CLAIM_FIELDS_PROMPT = (
    "Each entry in claims must contain ALL of the following fields -- every "
    "field is REQUIRED in every entry, with no field ever omitted; use null "
    "for a field that does not apply to that claim:\n"
    "- claim_text: the exact sentence or clause the claim came from\n"
    "- canonical_metric_name: exactly one value from the request's "
    "allowed_metrics, or null if no listed metric matches this claim\n"
    "- claim_type: exactly one of absolute_value, directional_change, "
    "percentage_change, percentage_point_change, ratio_change, "
    "comparative_statement, qualitative_financial_claim -- never any other "
    "string\n"
    "- direction: exactly one of increase, decrease, unchanged, positive, "
    "negative, unknown, or null\n"
    "- reported_value: the absolute numeric value stated (e.g. 112000000 for "
    '"$112 million"), or null when the claim is not an absolute value\n'
    "- reported_unit: the unit of reported_value (e.g. USD), or null\n"
    "- reported_change: the numeric size of a stated change (e.g. 12 for "
    '"12%", 1.25 for "1.25 percentage points"), or null when the claim is '
    "not a change\n"
    "- reported_change_unit: exactly one of percent, percentage_points, or "
    "null\n"
    "- comparison_basis: the comparison period stated (e.g. "
    "prior_year_quarter), or null\n"
    "- comparison_text: the exact comparison phrase from the text (e.g. "
    '"compared with the same period last year"), or null\n'
    "- qualifiers: an object of any additional qualifiers, or {} when none\n"
    "- confidence: a number between 0.0 and 1.0\n"
)


_BATCH_CLAIM_SYSTEM_PROMPT = (
    "Extract factual financial claims from SEC filing text. The request holds "
    "several independent items, each with its own item_id. Extract claims for "
    "every item on its own; never mix claims between items. Return only a "
    'single JSON object of the form {"items": [{"item_id": "...", "claims": '
    "[...]}]} with exactly one entry per input item, copying each item_id "
    "exactly as given and always including a claims array (empty when the "
    "item has no claims). Use null for unknown values and never infer facts "
    "not present in the text.\n"
    + _CLAIM_FIELDS_PROMPT
    + "Do not include any text, commentary, or markdown outside the single "
    "JSON object."
)


_SINGLE_CLAIM_SYSTEM_PROMPT = (
    "Extract factual financial claims from SEC filing text. Return only a "
    'single JSON object of the form {"claims": [...]} with one entry per '
    "claim found in the text (an empty array when there are none). Use null "
    "for unknown values and never infer facts not present in the text.\n"
    + _CLAIM_FIELDS_PROMPT
    + "Do not include any text, commentary, or markdown outside the single "
    "JSON object."
)


# See the matching note in semantic_change: the prompt text hash is folded into
# the version strings so an edited prompt cannot silently reuse old results.
_CLAIM_PROMPT_FINGERPRINT = canonical_hash(
    [_SINGLE_CLAIM_SYSTEM_PROMPT, _BATCH_CLAIM_SYSTEM_PROMPT]
)


class OpenAICompatibleClaimExtractor:
    # v2: names every required field and enum explicitly (v1 named none of
    # them - see the comment above _CLAIM_FIELDS_PROMPT).
    prompt_version = f"financial-claim-extraction-json-v2+{_CLAIM_PROMPT_FINGERPRINT[:8]}"
    batch_prompt_version = (
        f"financial-claim-extraction-batch-json-v2+{_CLAIM_PROMPT_FINGERPRINT[:8]}"
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
