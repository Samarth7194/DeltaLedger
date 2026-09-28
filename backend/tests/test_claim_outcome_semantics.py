"""Claim extraction must tell "analysed, no claims" apart from "could not be
analysed", keep that fact durably, and resume without redoing finished items."""

from __future__ import annotations

import pytest

from app.ai.inference import record_usage
from app.ai.openai_compatible import ProviderRequestError
from app.services.analysis_progress import build_stage_progress
from tests.test_claim_batch_extraction import (
    PLAIN_TEXT,
    RUN_ID,
    _claim,
    _provider_error,
    _Scenario,
    _ScriptedExtractor,
)


class SimulatedCrash(BaseException):
    pass


def _texts(count: int) -> list[str]:
    return [f"{PLAIN_TEXT} #{i}" for i in range(count)]


class _OutcomeExtractor(_ScriptedExtractor):
    """`empty_texts`: analysed fine, genuinely no claims. `bad_texts`: the model
    never produces a usable answer (also on the individual retry)."""

    def __init__(self, *, empty_texts=(), **kwargs) -> None:
        super().__init__(**kwargs)
        self.empty_texts = empty_texts

    def _claims_for(self, text):
        return [] if any(e in text for e in self.empty_texts) else [_claim(text)]

    async def extract_claims_batch(self, items, allowed_metrics):
        outcomes = await super().extract_claims_batch(items, allowed_metrics)
        return {
            item.item_id: (
                self._claims_for(item.text) if outcomes[item.item_id] is not None else None
            )
            for item in items
        }

    async def extract_claims(self, text, section_metadata, allowed_metrics):
        result = await super().extract_claims(text, section_metadata, allowed_metrics)
        return self._claims_for(text) if result else result


@pytest.mark.asyncio
async def test_a_genuine_zero_result_is_not_a_failure() -> None:
    scenario = _Scenario(_texts(3), max_items=3)

    metrics = await scenario.run(_OutcomeExtractor(empty_texts=("#1",)))

    (row,) = scenario.ledger()
    assert (row.successful, row.zero_result, row.requires_review) == (2, 1, 0)
    assert metrics["claim_items_zero_result"] == 1
    assert metrics["claim_items_requires_review"] == 0
    assert {r["status"] for r in row.item_results.values()} == {"success", "zero_result"}
    stages = await _stage(scenario)
    assert stages["financial_claims"]["status"] == "completed"  # clean: nothing unanalysed


@pytest.mark.asyncio
async def test_a_failed_item_is_recorded_as_requires_review_and_never_fabricated() -> None:
    scenario = _Scenario(_texts(3), max_items=3)
    extractor = _OutcomeExtractor(bad_texts=("#1",), hopeless_texts=("#1",))

    metrics = await scenario.run(extractor)

    (row,) = scenario.ledger()
    assert (row.successful, row.zero_result, row.requires_review) == (2, 0, 1)
    assert metrics["claim_items_requires_review"] == 1
    failed = next(r for r in row.item_results.values() if r["status"] == "requires_review")
    assert failed["error"] == "StructuredOutputError" and failed["message"]
    # No claim exists for the passage the model could not analyse.
    stored = {claim.claim_text for claim in scenario.financial.claims.values()}
    assert stored == {f"claim from: {PLAIN_TEXT} #0", f"claim from: {PLAIN_TEXT} #2"}
    # ...and the truth is visible downstream: not "completed", but requires_review.
    stages = await _stage(scenario)
    assert stages["financial_claims"]["status"] == "requires_review"
    assert stages["financial_claims"]["requires_review_items"] == 1
    assert stages["financial_claims"]["zero_result_items"] == 0


@pytest.mark.asyncio
async def test_the_same_scenario_with_and_without_the_failure_differs_in_accounting() -> None:
    clean = _Scenario(_texts(2), max_items=2)
    await clean.run(_OutcomeExtractor(empty_texts=("#0", "#1")))  # both analysed, both empty

    broken = _Scenario(_texts(2), max_items=2)
    await broken.run(_OutcomeExtractor(bad_texts=("#0", "#1"), hopeless_texts=("#0", "#1")))

    assert (clean.ledger()[0].zero_result, clean.ledger()[0].requires_review) == (2, 0)
    assert (broken.ledger()[0].zero_result, broken.ledger()[0].requires_review) == (0, 2)
    assert clean.financial.claims == broken.financial.claims == {}  # same visible claims...
    assert (await _stage(clean))["financial_claims"]["status"] == "completed"
    # ...but a different truth:
    assert (await _stage(broken))["financial_claims"]["status"] == "requires_review"


@pytest.mark.asyncio
async def test_a_completed_part_keeps_its_review_items_and_is_not_retried() -> None:
    scenario = _Scenario(_texts(2), max_items=2)
    await scenario.run(_OutcomeExtractor(bad_texts=("#1",), hopeless_texts=("#1",)))

    retry = _OutcomeExtractor()
    await scenario.run(retry)

    assert retry.batch_calls == [] and retry.single_calls == []  # completed is final
    assert scenario.ledger()[0].requires_review == 1


@pytest.mark.asyncio
async def test_a_killed_worker_resumes_claims_at_the_processing_part_in_a_fresh_process() -> None:
    scenario = _Scenario(_texts(6), max_items=2)  # 3 parts

    class _Dies(_ScriptedExtractor):
        async def extract_claims_batch(self, items, allowed_metrics):
            if len(self.batch_calls) == 2:
                self.batch_calls.append([i.item_id for i in items])
                raise SimulatedCrash
            return await super().extract_claims_batch(items, allowed_metrics)

    with pytest.raises(SimulatedCrash):
        await scenario.run(_Dies())
    assert [r.status for r in scenario.ledger()] == ["completed", "completed", "processing"]
    assert len(scenario.financial.claims) == 4

    fresh = _ScriptedExtractor()
    await scenario.run(fresh)  # everything rebuilt except the persisted state

    assert len(fresh.batch_calls) == 1  # only part 3
    assert [r.status for r in scenario.ledger()] == ["completed"] * 3
    assert [r.retry_count for r in scenario.ledger()] == [0, 0, 1]
    assert len(scenario.financial.claims) == 6


@pytest.mark.asyncio
async def test_a_retried_part_skips_items_already_analysed_before_the_failure() -> None:
    scenario = _Scenario(_texts(3), max_items=3)

    class _RateLimitedOnItem(_ScriptedExtractor):
        async def extract_claims_batch(self, items, allowed_metrics):
            outcomes = await super().extract_claims_batch(items, allowed_metrics)
            # Only the first item came back usable; the rest must be retried.
            return {
                i.item_id: (outcomes[i.item_id] if n == 0 else None)
                for n, i in enumerate(items)
            }

        async def extract_claims(self, text, section_metadata, allowed_metrics):
            self.single_calls.append(text)
            raise _provider_error()

    with pytest.raises(ProviderRequestError):
        await scenario.run(_RateLimitedOnItem())
    (row,) = scenario.ledger()
    assert row.status == "failed" and row.successful == 1  # item 0 durably kept
    assert row.provider_error_type == "rate_limited"

    retry = _ScriptedExtractor()
    await scenario.run(retry)

    requested = [text for call in retry.single_calls for text in [call]] + [
        i for call in retry.batch_calls for i in call
    ]
    assert len(retry.batch_calls) == 1 and len(retry.batch_calls[0]) == 2  # items 1-2 only
    assert requested  # sanity
    assert len(scenario.financial.claims) == 3 and scenario.ledger()[0].status == "completed"


@pytest.mark.asyncio
async def test_claim_usage_is_persisted_and_null_when_unreported() -> None:
    reporting = _Scenario(_texts(4), max_items=2)

    class _Reports(_ScriptedExtractor):
        async def extract_claims_batch(self, items, allowed_metrics):
            record_usage({"prompt_tokens": 300, "completion_tokens": 30, "total_tokens": 330})
            return await super().extract_claims_batch(items, allowed_metrics)

    metrics = await reporting.run(_Reports())
    assert [(r.actual_input, r.actual_output, r.actual_total) for r in reporting.ledger()] == [
        (300, 30, 330),
        (300, 30, 330),
    ]
    assert metrics["claim_actual_input_tokens"] == 600

    silent = _Scenario(_texts(4), max_items=2)
    metrics = await silent.run(_ScriptedExtractor())
    assert all(r.actual_input is None and r.actual_total is None for r in silent.ledger())
    assert metrics["claim_actual_input_tokens"] is None


async def _stage(scenario) -> dict[str, dict]:
    """The API-facing stage progress as it would be derived from the ledger."""
    from app.repositories.stage_batch_repository import StageBatchRepository
    from tests.batch_test_helpers import InMemoryBatchSession

    repo = StageBatchRepository(InMemoryBatchSession(scenario.ledger_rows))
    return {
        entry["stage"]: entry
        for entry in build_stage_progress(
            completed_nodes=["run_disclosure_comparison", "extract_financial_claims"],
            current_node=None,
            run_status="verifying_claims",
            failure_node=None,
            batches=await repo.stage_progress(RUN_ID),
        )
    }
