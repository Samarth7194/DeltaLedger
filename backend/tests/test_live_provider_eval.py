"""Offline tests for the live provider evaluation. No network, no database: the "provider" is a
scripted fake that speaks the same protocol as the OpenAI-compatible classifier/extractor."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.ai.financial_claims import ClaimBatchItem, FinancialClaimExtraction
from app.ai.inference import InferenceMetadata
from app.ai.openai_compatible import (
    QUOTA_EXHAUSTED_DAILY,
    RATE_LIMITED_SHORT_TERM,
    ProviderRequestError,
    StructuredOutputError,
)
from app.ai.semantic_change import ChangeClassificationRequest, ChangeClassificationResult
from app.cli import evaluate_providers
from app.core.config import Settings
from app.evaluation import live_provider_eval as live
from app.evaluation.live_provider_eval import (
    CHANGE_TASK,
    CLAIM_TASK,
    EvaluationConfigError,
    render_markdown,
    run_live_evaluation,
    score_claim_item,
)

CHANGE_GOLD = {example["id"]: example for example in live.load_change_examples()}
CHANGE_BY_TEXT = {
    (example.get("previous_text"), example.get("current_text")): example
    for example in CHANGE_GOLD.values()
}
CLAIM_GOLD = {example["id"]: example for example in live.load_claim_examples()}


def _quota_error() -> ProviderRequestError:
    return ProviderRequestError(
        "daily quota exhausted",
        provider="openai_compatible",
        provider_type="disclosure_change_classifier",
        model="fake-model",
        status_code=429,
        retry_count=0,
        retry_after_seconds=None,
        error_category="rate_limited",
        error_subtype=QUOTA_EXHAUSTED_DAILY,
    )


def _short_term_error() -> ProviderRequestError:
    return ProviderRequestError(
        "slow down",
        provider="openai_compatible",
        provider_type="disclosure_change_classifier",
        model="fake-model",
        status_code=429,
        retry_count=5,
        retry_after_seconds=30.0,
        error_category="rate_limited",
        error_subtype=RATE_LIMITED_SHORT_TERM,
    )


def _change_result(gold: dict, change_type: str | None = None) -> ChangeClassificationResult:
    return ChangeClassificationResult(
        change_type=change_type or gold["expected_change_type"],
        summary="s",
        explanation="e",
        confidence=0.9,
        risk_category=gold["expected_risk_category"],
        materiality_reason="m",
        inference_metadata={
            "model": "fake-model",
            "prompt_version": "fake-prompt",
            "created_at": "2026-01-01T00:00:00+00:00",
            "api_key": "must-not-be-persisted",
        },
    )


class FakeChangeClassifier:
    model_name = "fake-model"
    model_version = "fake-model"
    prompt_version = "fake-single-prompt"
    batch_prompt_version = "fake-batch-prompt"
    batch_fixed_overhead_tokens = 0

    def __init__(self) -> None:
        self.batch_calls: list[list[str]] = []
        self.single_calls: list[str] = []
        self.batch_errors: dict[int, ProviderRequestError] = {}  # 1-based call number -> error
        self.always_error: ProviderRequestError | None = None
        self.drop_ids: set[str] = set()  # ids a batch "forgets" (forces the single retry)
        self.invalid_ids: set[str] = set()  # ids whose single retry fails validation
        self.wrong: dict[str, str] = {}  # id -> wrong change_type

    async def classify_batch(self, items):
        ids = [item_id for item_id, _ in items]
        self.batch_calls.append(ids)
        if self.always_error is not None:
            raise self.always_error
        if len(self.batch_calls) in self.batch_errors:
            raise self.batch_errors[len(self.batch_calls)]
        return {
            item_id: (
                None
                if item_id in self.drop_ids
                else _change_result(CHANGE_GOLD[item_id], self.wrong.get(item_id))
            )
            for item_id in ids
        }

    async def classify(self, request: ChangeClassificationRequest):
        gold = CHANGE_BY_TEXT[(request.previous_text, request.current_text)]
        self.single_calls.append(gold["id"])
        if gold["id"] in self.invalid_ids:
            raise StructuredOutputError(
                "invalid",
                InferenceMetadata(
                    provider="openai_compatible",
                    provider_type="disclosure_change_classifier",
                    model="fake-model",
                    success=False,
                    parse_status="invalid",
                ),
            )
        return _change_result(gold, self.wrong.get(gold["id"]))


def _claim(metric: str | None, claim_type: str) -> FinancialClaimExtraction:
    return FinancialClaimExtraction(
        claim_text="x",
        canonical_metric_name=metric,
        claim_type=claim_type,
        confidence=Decimal("0.9"),
        original_output={"inference_metadata": {"model": "fake-model", "created_at": "t"}},
    )


CATEGORY_TYPE = live.CATEGORY_TO_CLAIM_TYPE


class FakeClaimExtractor:
    model_name = "fake-model"
    model_version = "fake-model"
    prompt_version = "fake-claim-single"
    batch_prompt_version = "fake-claim-batch"

    def __init__(self) -> None:
        self.batch_calls: list[list[str]] = []

    def batch_fixed_overhead_tokens(self, allowed_metrics: list[str]) -> int:
        return 0

    def _answer(self, gold: dict) -> list[FinancialClaimExtraction]:
        if gold["metric"] is None:
            return []
        return [_claim(gold["metric"], CATEGORY_TYPE.get(gold["category"], "absolute_value"))]

    async def extract_claims_batch(self, items: list[ClaimBatchItem], allowed_metrics):
        self.batch_calls.append([item.item_id for item in items])
        return {item.item_id: self._answer(CLAIM_GOLD[item.item_id]) for item in items}

    async def extract_claims(self, text, section_metadata, allowed_metrics):
        gold = next(g for g in CLAIM_GOLD.values() if g["claim"] == text)
        return self._answer(gold)


def _settings() -> Settings:
    return Settings(
        ai_batch_max_items=8,
        ai_batch_multi_item_requests=True,
        ai_provider_chat_delay_seconds=0.0,
    )


async def _run(tmp_path: Path, change=None, claims=None, **kwargs):
    return await run_live_evaluation(
        settings=_settings(),
        change_classifier=change if change is not None else FakeChangeClassifier(),
        claim_extractor=claims if claims is not None else FakeClaimExtractor(),
        output_path=tmp_path / "results.json",
        on_message=lambda _message: None,
        **kwargs,
    )


# --- end-to-end behaviour -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_complete_run_scores_both_systems_and_persists_provenance(tmp_path) -> None:
    results = await _run(tmp_path)

    assert results["status"] == "completed"
    assert results["remaining_items"] == {CHANGE_TASK: 0, CLAIM_TASK: 0}
    change = results["tasks"][CHANGE_TASK]["metrics"]
    assert change["n_scored"] == 40
    assert change["gemini"]["change_type"]["accuracy"]["value"] == 1.0
    # The baseline number is the deterministic classifier's, the same 0.975 the checked-in
    # offline report shows for the same 40 fixtures.
    assert change["baseline"]["change_type"]["accuracy"]["value"] == 0.975
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == "live-provider-eval-v1"
    assert saved["datasets"][CHANGE_TASK]["version"] == "phase3-v1"
    assert saved["datasets"][CLAIM_TASK]["version"] == "phase4-v1"
    assert saved["tasks"][CHANGE_TASK]["model"] == "fake-model"
    assert saved["tasks"][CHANGE_TASK]["prompt_version"] == "fake-batch-prompt"
    item = saved["tasks"][CHANGE_TASK]["items"]["add-001"]
    assert item["gemini"]["run_at"] and item["gemini"]["inference"]["created_at"]
    assert item["gemini"]["prediction"]["change_type"] == "added"
    assert item["baseline"]["change_type"] == "added"


@pytest.mark.asyncio
async def test_secrets_and_unknown_inference_fields_are_never_persisted(tmp_path) -> None:
    await _run(tmp_path)

    text = (tmp_path / "results.json").read_text(encoding="utf-8")

    assert "must-not-be-persisted" not in text
    assert "api_key" not in text.lower()
    assert "Authorization" not in text


@pytest.mark.asyncio
async def test_claim_scores_use_the_gold_definitions_and_report_the_hybrid(tmp_path) -> None:
    results = await _run(tmp_path)

    systems = results["tasks"][CLAIM_TASK]["metrics"]["systems"]
    assert results["tasks"][CLAIM_TASK]["metrics"]["n_scored"] == 60
    assert systems["gemini"]["canonical_metric_accuracy"]["value"] == 1.0
    assert systems["gemini"]["claim_type_accuracy"]["n"] == 40  # 15 + 15 + 10 typed items
    assert systems["gemini"]["claim_type_accuracy"]["value"] == 1.0
    # The hybrid is deterministic-first, so it can never do worse than nothing and is bounded by
    # what the deterministic pass returned; it must differ from "Gemini alone" here.
    assert systems["hybrid"]["canonical_metric_accuracy"]["n"] == 60
    assert set(systems) == {"baseline", "gemini", "hybrid"}
    phase4 = results["phase4_metrics"]
    assert phase4["claim_extraction.canonical_metric_accuracy"]["status"] == "evaluated"
    assert phase4["claim_extraction.canonical_metric_accuracy"]["system"] == "gemini:fake-model"
    assert phase4["verification_status"]["status"] == "not_evaluated"
    assert phase4["xbrl_resolution.concept_selection_accuracy"]["status"] == "not_evaluated"


@pytest.mark.asyncio
async def test_a_gap_in_a_batch_is_retried_one_item_at_a_time(tmp_path) -> None:
    change = FakeChangeClassifier()
    change.drop_ids = {"add-001"}

    results = await _run(tmp_path, change=change, tasks=(CHANGE_TASK,))

    assert change.single_calls == ["add-001"]
    record = results["tasks"][CHANGE_TASK]["items"]["add-001"]["gemini"]
    assert record["status"] == "ok" and record["via"] == "single_retry"
    assert results["tasks"][CHANGE_TASK]["items"]["add-002"]["gemini"]["via"] == "batch"


@pytest.mark.asyncio
async def test_invalid_output_counts_as_a_wrong_answer_not_as_missing(tmp_path) -> None:
    change = FakeChangeClassifier()
    change.drop_ids = {"add-001"}
    change.invalid_ids = {"add-001"}

    results = await _run(tmp_path, change=change, tasks=(CHANGE_TASK,))

    record = results["tasks"][CHANGE_TASK]["items"]["add-001"]["gemini"]
    assert record["status"] == "invalid_output" and record["prediction"] is None
    metrics = results["tasks"][CHANGE_TASK]["metrics"]
    assert metrics["n_scored"] == 40  # it was answered (badly): it stays in the paired set
    matrix = metrics["gemini"]["change_type"]["confusion_matrix"]
    assert matrix["added"][live.NO_PREDICTION] == 1
    assert metrics["gemini"]["change_type"]["accuracy"]["value"] == 39 / 40
    assert results["status"] == "completed"


# --- quota, provider errors, request cap, resume --------------------------------------------------


@pytest.mark.asyncio
async def test_daily_quota_stops_immediately_saves_partial_results_and_resume_finishes(
    tmp_path,
) -> None:
    change = FakeChangeClassifier()
    change.batch_errors = {2: _quota_error()}
    claims = FakeClaimExtractor()

    partial = await _run(tmp_path, change=change, claims=claims)

    assert partial["status"] == "partial"
    assert partial["stop_reason"] == "daily_quota_exhausted"
    assert len(change.batch_calls) == 2  # stopped at the quota error: no third call, no retries
    assert claims.batch_calls == []  # the second task never started
    assert partial["remaining_items"][CHANGE_TASK] == 32
    assert partial["tasks"][CLAIM_TASK]["items"] == {}
    on_disk = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    on_disk_items = on_disk["tasks"][CHANGE_TASK]["items"].values()
    done = [i for i in on_disk_items if i["gemini"]["status"] == "ok"]
    assert len(done) == 8  # what was already paid for is kept
    failed = [
        i for i in on_disk["tasks"][CHANGE_TASK]["items"].values()
        if i["gemini"]["status"] == "provider_error"
    ]
    assert failed and failed[0]["gemini"]["error_subtype"] == QUOTA_EXHAUSTED_DAILY
    # Metrics on the partial file only use answered items, for both systems.
    assert partial["tasks"][CHANGE_TASK]["metrics"]["n_scored"] == 8

    resumed_change = FakeChangeClassifier()
    resumed_claims = FakeClaimExtractor()
    done_ids = {i["id"] for i in done}
    final = await run_live_evaluation(
        settings=_settings(),
        change_classifier=resumed_change,
        claim_extractor=resumed_claims,
        output_path=tmp_path / "results.json",
        resume=True,
        on_message=lambda _message: None,
    )

    requested = {item_id for call in resumed_change.batch_calls for item_id in call}
    assert requested.isdisjoint(done_ids)  # nothing already answered is requested again
    assert len(requested) == 32
    assert final["status"] == "completed"
    assert final["run_id"] == partial["run_id"] and len(final["resumed_at"]) == 1
    assert final["tasks"][CHANGE_TASK]["metrics"]["n_scored"] == 40
    assert final["tasks"][CLAIM_TASK]["metrics"]["n_scored"] == 60


@pytest.mark.asyncio
async def test_repeated_provider_errors_stop_after_two_instead_of_burning_retries(tmp_path) -> None:
    change = FakeChangeClassifier()
    change.always_error = _short_term_error()

    results = await _run(tmp_path, change=change, tasks=(CHANGE_TASK,))

    assert len(change.batch_calls) == 2
    assert results["status"] == "partial"
    assert results["stop_reason"].startswith("2_consecutive_provider_errors")
    assert results["tasks"][CHANGE_TASK]["metrics"]["n_scored"] == 0
    assert results["tasks"][CHANGE_TASK]["metrics"]["gemini"]["status"] == "not_evaluated"


@pytest.mark.asyncio
async def test_a_non_retryable_provider_error_stops_at_once(tmp_path) -> None:
    change = FakeChangeClassifier()
    change.always_error = ProviderRequestError(
        "bad request",
        provider="openai_compatible",
        provider_type="disclosure_change_classifier",
        model="fake-model",
        status_code=400,
        retry_count=0,
        retry_after_seconds=None,
        error_category="client_error",
    )

    results = await _run(tmp_path, change=change, tasks=(CHANGE_TASK,))

    assert len(change.batch_calls) == 1
    assert results["stop_reason"].startswith("non_retryable_provider_error")


@pytest.mark.asyncio
async def test_max_requests_is_a_hard_stop_with_partial_results(tmp_path) -> None:
    change = FakeChangeClassifier()

    results = await _run(tmp_path, change=change, tasks=(CHANGE_TASK,), max_requests=2)

    assert len(change.batch_calls) == 2
    assert results["stop_reason"] == "max_requests_reached (2)"
    assert results["status"] == "partial"
    assert results["remaining_items"][CHANGE_TASK] == 24


@pytest.mark.asyncio
async def test_resume_refuses_a_different_model(tmp_path) -> None:
    change = FakeChangeClassifier()
    change.batch_errors = {2: _quota_error()}
    await _run(tmp_path, change=change, tasks=(CHANGE_TASK,))

    other = FakeChangeClassifier()
    other.model_name = "some-other-model"
    with pytest.raises(EvaluationConfigError, match="some-other-model"):
        await run_live_evaluation(
            settings=_settings(),
            change_classifier=other,
            claim_extractor=None,
            tasks=(CHANGE_TASK,),
            output_path=tmp_path / "results.json",
            resume=True,
            on_message=lambda _message: None,
        )


@pytest.mark.asyncio
async def test_single_mode_makes_one_call_per_item(tmp_path) -> None:
    change = FakeChangeClassifier()

    results = await _run(tmp_path, change=change, tasks=(CHANGE_TASK,), mode="single")

    assert change.batch_calls == []
    assert len(change.single_calls) == 40
    assert results["tasks"][CHANGE_TASK]["mode"] == "single"


# --- scoring definitions (pure) ---------------------------------------------------------------


def test_metric_correctness_when_the_gold_metric_is_null_requires_no_asserted_metric() -> None:
    assert score_claim_item(None, None, [])["metric_correct"] is True
    assert score_claim_item(None, None, [{"canonical_metric_name": None}])["metric_correct"] is True
    invented = score_claim_item(None, None, [{"canonical_metric_name": "revenue"}])
    assert invented["metric_correct"] is False and invented["spurious_metric"] is True


def test_exact_match_needs_exactly_one_claim_with_the_right_metric_and_type() -> None:
    right = {"canonical_metric_name": "revenue", "claim_type": "percentage_change"}
    assert score_claim_item("revenue", "percentage_change", [right])["exact_match"] is True
    extra = [right, {"canonical_metric_name": "gross_profit", "claim_type": "absolute_value"}]
    scored = score_claim_item("revenue", "percentage_change", extra)
    assert scored["exact_match"] is False and scored["metric_correct"] is True
    wrong_type = {"canonical_metric_name": "revenue", "claim_type": "absolute_value"}
    wrong = score_claim_item("revenue", "percentage_change", [wrong_type])
    assert wrong["claim_type_correct"] is False
    assert score_claim_item("revenue", None, [right])["exact_match"] is None  # untyped item


def test_claim_type_gold_only_exists_for_the_three_categories_that_name_one() -> None:
    assert set(CATEGORY_TYPE) == {"absolute_value", "percentage_change", "percentage_point_change"}


@pytest.mark.asyncio
async def test_the_deterministic_baseline_runs_on_the_migration_seeded_metrics() -> None:
    definitions = live.load_seed_metric_definitions()
    assert "revenue" in {d.canonical_name for d in definitions}
    extractor = live.build_deterministic_extractor(_settings(), definitions)

    claims = await extractor.deterministic_extract("Revenue increased 12% year over year.")

    assert claims and claims[0].canonical_metric_name == "revenue"
    assert claims[0].claim_type == "percentage_change"


def test_the_real_sec_benchmark_cannot_score_claim_extraction_and_says_why() -> None:
    coverage = live.real_sec_claim_coverage()

    assert coverage["status"] == "not_evaluated"
    assert coverage["approved_financial_claim_records"] == 1
    assert coverage["records_with_stored_input_text"] == 0
    assert "locators" in coverage["reason"]


@pytest.mark.asyncio
async def test_markdown_states_the_caveats_and_the_incomplete_run(tmp_path) -> None:
    change = FakeChangeClassifier()
    change.batch_errors = {2: _quota_error()}
    results = await _run(tmp_path, change=change)

    markdown = render_markdown(results)

    assert "Read this first" in markdown
    assert "Incomplete run" in markdown and "daily_quota_exhausted" in markdown
    assert "| change_type accuracy |" in markdown
    assert "Confusion matrix - Gemini" in markdown
    assert "Phase 4 metrics" in markdown


# --- dev/held-out claim split -------------------------------------------------------------------


def test_the_dev_and_held_out_splits_are_disjoint_and_cover_every_example() -> None:
    all_examples = live.load_claim_examples()
    dev = live.load_claim_examples("dev")
    held_out = live.load_claim_examples("held_out")

    dev_ids = {example["id"] for example in dev}
    held_out_ids = {example["id"] for example in held_out}
    assert dev_ids.isdisjoint(held_out_ids)
    assert dev_ids | held_out_ids == {example["id"] for example in all_examples}
    assert len(dev) == len(held_out) == 30


def test_an_unknown_claim_split_is_refused() -> None:
    with pytest.raises(EvaluationConfigError, match="Unknown claim split"):
        live.load_claim_examples("nonexistent")


@pytest.mark.asyncio
async def test_a_held_out_only_run_only_ever_requests_held_out_items(tmp_path) -> None:
    claims = FakeClaimExtractor()
    held_out_ids = {example["id"] for example in live.load_claim_examples("held_out")}

    results = await _run(tmp_path, claims=claims, tasks=(CLAIM_TASK,), claim_split="held_out")

    assert set(results["tasks"][CLAIM_TASK]["items"]) == held_out_ids
    assert results["tasks"][CLAIM_TASK]["metrics"]["n_total"] == 30
    assert results["datasets"][CLAIM_TASK]["split"] == "held_out"
    requested = {item_id for call in claims.batch_calls for item_id in call}
    assert requested == held_out_ids  # never a dev-split item


# --- CLI guards -------------------------------------------------------------------------------


def test_live_mode_requires_the_explicit_paid_call_confirmation() -> None:
    with pytest.raises(SystemExit, match="confirm-paid-api-calls"):
        evaluate_providers.main(["--live"])


def test_live_mode_refuses_to_evaluate_the_deterministic_fake() -> None:
    # Isolated test settings default to the fake providers.
    with pytest.raises(SystemExit, match="deterministic fake"):
        evaluate_providers.main(["--live", "--confirm-paid-api-calls"])
