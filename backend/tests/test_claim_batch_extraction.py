from __future__ import annotations

import contextlib
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.ai.financial_claims import (
    BatchClaimExtractionResponse,
    ClaimBatchItem,
    FinancialClaimExtraction,
    OpenAICompatibleClaimExtractor,
)
from app.ai.openai_compatible import ProviderRequestError, StructuredOutputError
from app.core.config import Settings
from app.db.models.workflow import BATCH_STAGE_FINANCIAL_CLAIMS as STAGE
from app.repositories.stage_batch_repository import StageBatchRepository
from app.services.claim_batch_extraction_service import ClaimBatchExtractionService
from app.services.financial_claim_extraction_service import FinancialClaimExtractionService
from tests.batch_test_helpers import InMemoryBatchSession, batch_rows

RUN_ID = uuid.uuid4()
COMPARISON_ID = uuid.uuid4()
FILING_ID = uuid.uuid4()

FINANCIAL_TEXT = "Revenue increased 5% compared to the prior year."  # deterministic hit
PLAIN_TEXT = "Management discussed seasonal patterns in the quarter."  # needs the model


def _claim(text: str) -> FinancialClaimExtraction:
    return FinancialClaimExtraction(
        claim_text=f"claim from: {text}",
        canonical_metric_name=None,
        claim_type="qualitative_financial_claim",
        confidence=Decimal("0.8"),
    )


def _provider_error() -> ProviderRequestError:
    return ProviderRequestError(
        "provider request failed after 5 attempt(s): quota exceeded",
        provider="openai_compatible",
        provider_type="financial_claim_extractor",
        model="m",
        status_code=429,
        retry_count=5,
        retry_after_seconds=10.0,
        error_category="rate_limited",
    )


class _ScriptedExtractor:
    model_name = "fake-extractor"
    model_version = "v1"
    prompt_version = "single-v1"
    batch_prompt_version = "batch-v1"

    def __init__(
        self,
        *,
        bad_texts: tuple[str, ...] = (),
        hopeless_texts: tuple[str, ...] = (),
        fail_on_batch_call: int | None = None,
    ) -> None:
        self.bad_texts = bad_texts
        self.hopeless_texts = hopeless_texts
        self.fail_on_batch_call = fail_on_batch_call
        self.batch_calls: list[list[str]] = []
        self.single_calls: list[str] = []

    def batch_fixed_overhead_tokens(self, allowed_metrics: list[str]) -> int:
        return 0

    async def extract_claims_batch(self, items, allowed_metrics):
        self.batch_calls.append([item.item_id for item in items])
        if self.fail_on_batch_call == len(self.batch_calls):
            raise _provider_error()
        return {
            item.item_id: (
                None if any(bad in item.text for bad in self.bad_texts) else [_claim(item.text)]
            )
            for item in items
        }

    async def extract_claims(self, text, section_metadata, allowed_metrics):
        self.single_calls.append(text)
        if any(bad in text for bad in self.hopeless_texts):
            raise StructuredOutputError("invalid after repair", SimpleNamespace())
        return [_claim(text)]


class _FakeFinancialRepo:
    """Stores claims idempotently, like the real upsert_claim."""

    def __init__(self, sections: dict[uuid.UUID, SimpleNamespace]) -> None:
        self.sections = sections
        self.claims: dict[tuple, object] = {}

    async def list_metric_definitions(self, *, active_only=True):
        return [SimpleNamespace(canonical_name="revenue")]

    async def get_metric_by_name(self, name):
        return None

    async def get_section(self, section_id):
        return self.sections.get(section_id)

    async def get_passage(self, passage_id):
        return SimpleNamespace(id=passage_id)

    async def upsert_claim(self, claim):
        key = (claim.filing_id, claim.source_passage_id, claim.claim_text, None)
        existing = self.claims.get(key)
        if existing is not None:
            return existing, False
        self.claims[key] = claim
        return claim, True


class _FakeRegistry:
    async def resolve_metric(self, sentence):
        return SimpleNamespace(status="unresolved", metric=None, reason="test")


class _FakeComparisons:
    def __init__(self, changes: list[SimpleNamespace]) -> None:
        self._changes = changes

    async def list_changes(self, comparison_id, *, limit=50, **_):
        return self._changes


class _FakeSession:
    def __init__(self) -> None:
        self.close_count = 0

    async def commit(self) -> None:
        return None

    async def close(self) -> None:
        self.close_count += 1

    async def rollback(self) -> None:
        return None


@contextlib.asynccontextmanager
async def _lock(_key: int):
    yield True


class _Scenario:
    def __init__(self, texts: list[str], *, max_items: int = 2, token_budget: int = 12000) -> None:
        self.section = SimpleNamespace(
            id=uuid.uuid4(), section_type="mda", section_title="MD&A"
        )
        self.financial = _FakeFinancialRepo({self.section.id: self.section})
        changes = []
        for text in texts:
            passage_id = uuid.uuid4()
            changes.append(
                SimpleNamespace(
                    id=uuid.uuid4(),
                    comparison_id=COMPARISON_ID,
                    current_text=text,
                    previous_text=None,
                    supporting_evidence={
                        "current": {
                            "filing_id": str(FILING_ID),
                            "section_id": str(self.section.id),
                            "passage_id": str(passage_id),
                        },
                        "previous": None,
                    },
                )
            )
        self.comparisons = _FakeComparisons(changes)
        self.ledger_rows: list = []
        self.session = _FakeSession()
        self.settings = Settings(
            _env_file=None,
            app_profile="local-cloud",
            environment="local",
            ai_batch_max_items=max_items,
            ai_batch_input_token_budget=token_budget,
            ai_batch_token_safety_margin=0.0,
        )

    def service(self, extractor: _ScriptedExtractor) -> ClaimBatchExtractionService:
        extraction = FinancialClaimExtractionService(self.session, self.settings, extractor)
        extraction.repo = self.financial
        extraction.registry = _FakeRegistry()
        service = ClaimBatchExtractionService(
            self.session,
            self.settings,
            extraction,
            session_factory=lambda: InMemoryBatchSession(self.ledger_rows),
            batches_factory=StageBatchRepository,
            lock_factory=_lock,
        )
        service.financial = self.financial
        service.comparisons = self.comparisons
        service.batches = StageBatchRepository(InMemoryBatchSession(self.ledger_rows))
        return service

    async def run(self, extractor: _ScriptedExtractor, *, run_id=RUN_ID):
        return await self.service(extractor).extract_for_comparison(
            COMPARISON_ID, analysis_run_id=run_id
        )

    def ledger(self):
        return batch_rows(self.ledger_rows, STAGE)


@pytest.mark.asyncio
async def test_the_model_is_not_called_when_deterministic_extraction_already_found_claims() -> None:
    """The redundant request this removes: the old code always asked the model,
    then discarded its answer whenever the deterministic pass found anything."""
    extractor = _ScriptedExtractor()
    scenario = _Scenario([FINANCIAL_TEXT])
    extraction = FinancialClaimExtractionService(scenario.session, scenario.settings, extractor)
    extraction.repo = scenario.financial
    extraction.registry = _FakeRegistry()

    claims = await extraction.extract_from_passage(
        filing_id=FILING_ID,
        source_section=scenario.section,
        passage=None,
        text=FINANCIAL_TEXT,
    )

    assert claims  # deterministic result
    assert extractor.single_calls == [] and extractor.batch_calls == []


@pytest.mark.asyncio
async def test_the_model_is_still_used_when_deterministic_extraction_finds_nothing() -> None:
    extractor = _ScriptedExtractor()
    scenario = _Scenario([PLAIN_TEXT])
    extraction = FinancialClaimExtractionService(scenario.session, scenario.settings, extractor)
    extraction.repo = scenario.financial
    extraction.registry = _FakeRegistry()

    claims = await extraction.extract_from_passage(
        filing_id=FILING_ID,
        source_section=scenario.section,
        passage=None,
        text=PLAIN_TEXT,
    )

    assert [claim.claim_text for claim in claims] == [f"claim from: {PLAIN_TEXT}"]
    assert extractor.single_calls == [PLAIN_TEXT]


@pytest.mark.asyncio
async def test_only_passages_needing_the_model_are_batched_and_stored_by_item() -> None:
    texts = [FINANCIAL_TEXT, FINANCIAL_TEXT + " Again.", *(f"{PLAIN_TEXT} #{i}" for i in range(5))]
    scenario = _Scenario(texts, max_items=2)
    extractor = _ScriptedExtractor()

    metrics = await scenario.run(extractor)

    assert metrics["claim_items_deterministic"] == 2
    assert metrics["claim_items_needing_model"] == 5
    assert [row.status for row in scenario.ledger()] == ["completed"] * 3  # 5 items / 2 per part
    # 2 multi-item requests + 1 single-item part, versus 5 requests unbatched.
    assert len(extractor.batch_calls) == 2 and len(extractor.single_calls) == 1
    assert metrics["claim_provider_calls"] == 3
    # Each model-extracted claim is tied to its own passage's text.
    model_claims = [
        claim
        for claim in scenario.financial.claims.values()
        if claim.claim_text.startswith("claim from")
    ]
    assert sorted(claim.claim_text for claim in model_claims) == sorted(
        f"claim from: {PLAIN_TEXT} #{i}" for i in range(5)
    )


@pytest.mark.asyncio
async def test_batches_are_bounded_by_the_token_budget() -> None:
    scenario = _Scenario([f"{PLAIN_TEXT} #{i}" for i in range(4)], max_items=50, token_budget=200)
    extractor = _ScriptedExtractor()

    await scenario.run(extractor)

    # ~80 estimated tokens per item (text + metadata + framing): two fit in
    # 200, three do not, so the 4 items become two 2-item requests even
    # though AI_BATCH_MAX_ITEMS would have allowed 50.
    assert [row.item_ids.__len__() for row in scenario.ledger()] == [2, 2]
    assert [len(call) for call in extractor.batch_calls] == [2, 2]


@pytest.mark.asyncio
async def test_a_failed_part_is_retried_and_completed_parts_are_not_redone() -> None:
    texts = [f"{PLAIN_TEXT} #{i}" for i in range(6)]
    scenario = _Scenario(texts, max_items=2)  # 3 parts

    with pytest.raises(ProviderRequestError):
        await scenario.run(_ScriptedExtractor(fail_on_batch_call=3))
    ledger = scenario.ledger()
    assert [row.status for row in ledger] == ["completed", "completed", "failed"]
    assert ledger[2].error_category == "rate_limited"
    claims_after_failure = len(scenario.financial.claims)
    assert claims_after_failure == 4  # parts 1-2 stored their claims

    healthy = _ScriptedExtractor()
    metrics = await scenario.run(healthy)

    assert len(healthy.batch_calls) == 1  # only part 3
    assert [row.status for row in scenario.ledger()] == ["completed"] * 3
    assert [row.retry_count for row in scenario.ledger()] == [0, 0, 1]
    assert (metrics["claim_batches_skipped"], metrics["claim_batches_executed"]) == (2, 1)
    assert len(scenario.financial.claims) == 6  # no duplicates from the retry


@pytest.mark.asyncio
async def test_a_bad_item_is_retried_alone_and_an_unusable_one_does_not_block_the_run() -> None:
    texts = [f"{PLAIN_TEXT} #{i}" for i in range(3)]
    scenario = _Scenario(texts, max_items=3)
    extractor = _ScriptedExtractor(bad_texts=("#1",), hopeless_texts=("#1",))

    metrics = await scenario.run(extractor)

    assert extractor.single_calls == [f"{PLAIN_TEXT} #1"]  # only the bad one, alone
    assert metrics["claim_items_requires_review"] == 1  # not silently dropped
    assert [row.status for row in scenario.ledger()] == ["completed"]
    stored = {claim.claim_text for claim in scenario.financial.claims.values()}
    assert stored == {f"claim from: {PLAIN_TEXT} #0", f"claim from: {PLAIN_TEXT} #2"}


@pytest.mark.asyncio
async def test_a_model_change_invalidates_completed_claim_parts() -> None:
    scenario = _Scenario([f"{PLAIN_TEXT} #{i}" for i in range(4)], max_items=2)
    await scenario.run(_ScriptedExtractor())

    class _Other(_ScriptedExtractor):
        model_name = "other-extractor"

    other = _Other()
    await scenario.run(other)

    assert len(other.batch_calls) == 2


@pytest.mark.asyncio
async def test_without_an_analysis_run_extraction_still_batches_but_persists_no_ledger() -> None:
    scenario = _Scenario([f"{PLAIN_TEXT} #{i}" for i in range(4)], max_items=2)
    extractor = _ScriptedExtractor()

    await scenario.service(extractor).extract_for_comparison(COMPARISON_ID)

    assert len(extractor.batch_calls) == 2
    assert scenario.ledger() == []


# --- the real provider-facing multi-item parsing ------------------------------------------


class _FakeChatClient:
    def __init__(self, items) -> None:
        self._items = items
        self.payloads: list[dict] = []

    async def chat_json(self, **kwargs):
        self.payloads.append(kwargs["user_payload"])
        return (
            BatchClaimExtractionResponse(items=self._items),
            SimpleNamespace(model_dump=lambda: {"total_tokens": 1}),
            {"id": "r1"},
        )


def _claim_payload(text: str) -> dict[str, object]:
    return {
        "claim_text": text,
        "canonical_metric_name": None,
        "claim_type": "qualitative_financial_claim",
        "confidence": 0.7,
    }


@pytest.mark.asyncio
async def test_batch_claim_response_is_mapped_by_item_id_and_validated_per_item() -> None:
    client = _FakeChatClient(
        [
            {"item_id": "i_2", "claims": [_claim_payload("two")]},
            {"item_id": "i_0", "claims": []},  # legitimately no claims
            {"item_id": "i_1", "claims": [{"claim_text": "missing required fields"}]},
            {"item_id": "i_unknown", "claims": [_claim_payload("ignored")]},
        ]
    )
    extractor = OpenAICompatibleClaimExtractor(
        Settings(
            _env_file=None,
            app_profile="local-cloud",
            environment="local",
            ai_provider_api_key="test-key",
        )
    )
    extractor._client = client
    items = [
        ClaimBatchItem(item_id=f"i_{i}", text=f"text {i}", section_metadata={}) for i in range(4)
    ]

    outcomes = await extractor.extract_claims_batch(items, ["revenue"])

    assert outcomes["i_0"] == []
    assert outcomes["i_1"] is None  # invalid claim -> retried alone, others unaffected
    assert [c.claim_text for c in outcomes["i_2"]] == ["two"]
    assert outcomes["i_3"] is None  # missing from the response
    assert "i_unknown" not in outcomes
    assert [item["item_id"] for item in client.payloads[0]["items"]] == [
        "i_0",
        "i_1",
        "i_2",
        "i_3",
    ]
    assert client.payloads[0]["allowed_metrics"] == ["revenue"]  # sent once per request
