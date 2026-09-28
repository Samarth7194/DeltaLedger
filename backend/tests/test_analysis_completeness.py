"""The completeness guard, the progress API shape, report data-quality, and the
real-Gemini canary helper (without contacting any provider)."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.batching import BatchingConfig
from app.api.routes.analyses import _progress_percent
from app.api.schemas import AnalysisProgressResponse
from app.core.config import Settings
from app.db.models.workflow import (
    BATCH_STAGE_DISCLOSURE_COMPARISON as DISCLOSURE,
)
from app.db.models.workflow import (
    BATCH_STAGE_FINANCIAL_CLAIMS as CLAIMS,
)
from app.repositories.stage_batch_repository import PartProgress, StageProgress
from app.services import analysis_workflow_service as workflow_module
from app.services.analysis_completeness import evaluate_readiness
from app.services.analysis_progress import build_stage_progress, current_stage_fraction
from app.services.analysis_report_service import _data_quality, _summary
from app.services.analysis_workflow_service import AnalysisWorkflowService, WorkflowError

ALL_NODES = [
    "validate_analysis_request",
    "run_disclosure_comparison",
    "extract_financial_claims",
    "verify_financial_claims",
    "analyze_contradictions",
    "validate_evidence",
]


def _progress(stage, total, completed, *, failed=0, review=0, **kwargs) -> StageProgress:
    return StageProgress(
        stage=stage,
        total=total,
        completed=completed,
        processing=1 if completed + failed < total and completed else 0,
        failed=failed,
        pending=total - completed - failed,
        provider_calls=kwargs.pop("provider_calls", completed),
        retries=0,
        requires_review_items=review,
        **kwargs,
    )


def _both(disclosure, claims):
    return {DISCLOSURE: disclosure, CLAIMS: claims}


def _ready_kwargs(**overrides):
    base = {
        "completed_nodes": ALL_NODES,
        "batches": {DISCLOSURE: _progress(DISCLOSURE, 17, 17), CLAIMS: _progress(CLAIMS, 6, 6)},
        "comparison_status": "completed",
        "comparison_metrics": {"classification_batches_total": 17},
        "claim_metrics": {"claim_batches_total": 6},
        "verification_complete": True,
        "contradiction_complete": True,
        "evidence_valid": True,
    }
    return {**base, **overrides}


# --- the guard ---------------------------------------------------------------------------


def test_a_fully_finished_analysis_is_ready() -> None:
    report = evaluate_readiness(**_ready_kwargs())

    assert report.is_ready and report.blockers == [] and report.data_quality == []


def test_some_batches_completed_is_not_enough_to_advance() -> None:
    report = evaluate_readiness(
        **_ready_kwargs(batches=_both(_progress(DISCLOSURE, 17, 8), _progress(CLAIMS, 6, 6)))
    )

    assert not report.is_ready
    (blocker,) = report.blockers
    assert (blocker.stage, blocker.code) == ("disclosure_classification", "batches_unfinished")
    assert "9 of 17" in blocker.message


def test_a_failed_or_missing_batch_blocks_and_counts_must_match_the_plan() -> None:
    failed = evaluate_readiness(
        **_ready_kwargs(
            batches=_both(_progress(DISCLOSURE, 17, 16, failed=1), _progress(CLAIMS, 6, 6))
        )
    )
    assert [b.code for b in failed.blockers] == ["batches_unfinished"]

    short = evaluate_readiness(
        **_ready_kwargs(batches=_both(_progress(DISCLOSURE, 17, 17), _progress(CLAIMS, 5, 5)))
    )
    assert [b.code for b in short.blockers] == ["batch_count_mismatch"]

    no_ledger = evaluate_readiness(
        **_ready_kwargs(batches={DISCLOSURE: _progress(DISCLOSURE, 17, 17)})
    )
    # claims planned 6 batches, none recorded
    assert [b.code for b in no_ledger.blockers] == ["batches_missing"]


def test_a_comparison_reused_from_an_earlier_run_needs_no_ledger_of_its_own() -> None:
    report = evaluate_readiness(**_ready_kwargs(batches={CLAIMS: _progress(CLAIMS, 6, 6)}))

    assert report.is_ready  # comparison status "completed" is the proof for that stage


def test_stages_that_never_ran_block_advancement() -> None:
    for missing, stage in [
        ("run_disclosure_comparison", "disclosure_classification"),
        ("extract_financial_claims", "financial_claims"),
        ("verify_financial_claims", "xbrl_verification"),
        ("analyze_contradictions", "contradiction_analysis"),
        ("validate_evidence", "evidence_validation"),
    ]:
        nodes = [node for node in ALL_NODES if node != missing]
        report = evaluate_readiness(**_ready_kwargs(completed_nodes=nodes))
        assert not report.is_ready
        assert stage in {b.stage for b in report.blockers}, missing

    assert not evaluate_readiness(**_ready_kwargs(comparison_status="failed")).is_ready
    assert not evaluate_readiness(**_ready_kwargs(verification_complete=False)).is_ready
    assert not evaluate_readiness(**_ready_kwargs(contradiction_complete=False)).is_ready


def test_unanalysed_items_do_not_block_but_must_be_reported() -> None:
    report = evaluate_readiness(
        **_ready_kwargs(
            batches={
                DISCLOSURE: _progress(DISCLOSURE, 17, 17, review=3),
                CLAIMS: _progress(CLAIMS, 6, 6, review=2),
            }
        )
    )

    assert report.is_ready
    assert len(report.data_quality) == 2
    assert "3 passage(s)" in report.data_quality[0] and "2 passage(s)" in report.data_quality[1]


def test_the_report_stage_also_requires_the_human_review_outcome() -> None:
    pending = evaluate_readiness(
        **_ready_kwargs(for_report=True, requires_human_review=True, review_status="pending")
    )
    assert [b.stage for b in pending.blockers] == ["human_review"]
    none_yet = evaluate_readiness(
        **_ready_kwargs(for_report=True, requires_human_review=True, review_status=None)
    )
    assert not none_yet.is_ready
    approved = evaluate_readiness(
        **_ready_kwargs(for_report=True, requires_human_review=True, review_status="approved")
    )
    assert approved.is_ready
    not_required = evaluate_readiness(
        **_ready_kwargs(for_report=True, requires_human_review=False, review_status=None)
    )
    assert not_required.is_ready


class _Comparisons:
    def __init__(self, status="completed", metrics=None) -> None:
        self._comparison = SimpleNamespace(
            status=status, processing_metrics=metrics or {"classification_batches_total": 17}
        )

    async def get_comparison(self, _comparison_id):
        return self._comparison


class _Workflow:
    def __init__(self, review_status=None) -> None:
        self._review = SimpleNamespace(status=review_status) if review_status else None

    async def get_latest_review(self, _run_id):
        return self._review


def _service(monkeypatch, progress, *, comparison=None, workflow=None) -> AnalysisWorkflowService:
    class _Repo:
        def __init__(self, _session) -> None:
            pass

        async def stage_progress(self, _run_id):
            return progress

    monkeypatch.setattr(workflow_module, "StageBatchRepository", _Repo)
    service = AnalysisWorkflowService(
        object(), Settings(_env_file=None, app_profile="local-cloud", environment="local")
    )
    service.comparisons = comparison or _Comparisons()
    service.workflow = workflow or _Workflow()
    return service


def _state(**overrides):
    base = {
        "analysis_run_id": "44444444-4444-4444-8444-444444444444",
        "comparison_id": "55555555-5555-4555-8555-555555555555",
        "completed_nodes": ALL_NODES,
        "counts": {"financial_claim_extraction": {"claim_batches_total": 6}},
        "financial_verification_complete": True,
        "contradiction_analysis_complete": True,
        "evidence_valid": True,
    }
    return {**base, **overrides}


@pytest.mark.asyncio
async def test_the_workflow_refuses_to_advance_with_unfinished_batches(monkeypatch) -> None:
    service = _service(
        monkeypatch, {DISCLOSURE: _progress(DISCLOSURE, 17, 8), CLAIMS: _progress(CLAIMS, 6, 6)}
    )

    with pytest.raises(WorkflowError) as info:
        await service._require_ready(_state())

    assert info.value.code == "analysis_incomplete"
    assert info.value.category == "incomplete_analysis"
    assert "9 of 17" in info.value.public_message


@pytest.mark.asyncio
async def test_the_workflow_advances_when_complete_and_hands_back_data_quality(monkeypatch) -> None:
    service = _service(
        monkeypatch,
        {DISCLOSURE: _progress(DISCLOSURE, 17, 17, review=1), CLAIMS: _progress(CLAIMS, 6, 6)},
    )

    readiness = await service._require_ready(_state())

    assert readiness.is_ready and len(readiness.data_quality) == 1


@pytest.mark.asyncio
async def test_report_generation_is_blocked_until_the_review_is_resolved(monkeypatch) -> None:
    progress = {DISCLOSURE: _progress(DISCLOSURE, 17, 17), CLAIMS: _progress(CLAIMS, 6, 6)}
    state = _state(requires_human_review=True)

    pending = _service(monkeypatch, progress, workflow=_Workflow("pending"))
    with pytest.raises(WorkflowError) as info:
        await pending._require_ready(state, for_report=True)
    assert "human_review" in info.value.public_message

    resumed = _service(monkeypatch, progress, workflow=_Workflow("pending"))
    ok = await resumed._require_ready(
        {**state, "review_result": {"status": "approved"}}, for_report=True
    )
    assert ok.is_ready


# --- progress API -------------------------------------------------------------------------


def _part(index, status, **kwargs) -> PartProgress:
    base = {
        "index": index,
        "status": status,
        "item_count": 8,
        "estimated_input_tokens": 4000,
        "actual_input_tokens": None,
        "actual_output_tokens": None,
        "actual_total_tokens": None,
        "provider_calls": 1,
        "retry_count": 0,
        "successful_items": 0,
        "zero_result_items": 0,
        "requires_review_items": 0,
        "last_provider_error_type": None,
        "last_retry_after_seconds": None,
        "last_provider_error_at": None,
    }
    return PartProgress(**{**base, **kwargs})


def _stages(batches, **kwargs):
    defaults = {
        "completed_nodes": ["validate_analysis_request"],
        "current_node": "run_disclosure_comparison",
        "run_status": "comparing_disclosures",
        "failure_node": None,
        "batches": batches,
        "batching": BatchingConfig(8, 12_000, 0.25),
    }
    return {e["stage"]: e for e in build_stage_progress(**{**defaults, **kwargs})}


def test_progress_shows_real_parts_tokens_and_budgets() -> None:
    parts = tuple(
        _part(i, "completed" if i <= 8 else "pending", actual_input_tokens=3900 if i <= 8 else None)
        for i in range(1, 18)
    )
    disclosure = _progress(
        DISCLOSURE,
        17,
        8,
        provider_calls=9,
        estimated_input_tokens=68_000,
        actual_input_tokens=31_200,
        parts=parts,
    )

    stages = _stages({DISCLOSURE: disclosure, CLAIMS: _progress(CLAIMS, 6, 2)})

    entry = stages["disclosure_comparison"]
    assert entry["label"] == "Disclosure Classification"
    assert entry["status"] == "processing"
    assert (entry["completed_units"], entry["total_units"]) == (8, 17)
    assert entry["current_unit"] == 9
    assert entry["provider_calls"] == 9
    assert entry["estimated_input_tokens"] == 68_000
    assert entry["actual_input_tokens"] == 31_200
    assert entry["actual_output_tokens"] is None  # never reported -> null, not estimated
    assert entry["actual_total_tokens"] is None
    # Our own planning limits - not the provider's quota.
    assert (entry["configured_input_budget"], entry["effective_input_budget"]) == (12_000, 9_000)
    assert len(entry["parts"]) == 17 and entry["parts"][8]["status"] == "pending"
    claims = stages["financial_claims"]
    assert (claims["completed_units"], claims["total_units"]) == (2, 6)
    for name in ("xbrl_verification", "contradiction_analysis", "human_review", "final_report"):
        assert stages[name]["status"] == "pending"
        assert stages[name]["configured_input_budget"] is None  # not a batched stage
    assert "remaining" not in json.dumps(stages).lower()  # nothing invents remaining quota


def test_progress_statuses_distinguish_failed_retryable_and_requires_review() -> None:
    rate_limited = _progress(
        DISCLOSURE,
        17,
        8,
        failed=1,
        last_provider_error_type="rate_limited_short_term",
        last_retry_after_seconds=21.5,
        last_provider_error_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    stages = _stages(
        {DISCLOSURE: rate_limited},
        run_status="failed",
        current_node=None,
        failure_node="run_disclosure_comparison",
        failure_code="rate_limited",
    )
    failed = stages["disclosure_comparison"]
    assert (failed["status"], failed["retryable"]) == ("failed", True)
    assert failed["last_provider_error_type"] == "rate_limited_short_term"
    assert failed["retry_after_seconds"] == 21.5

    rejected = _progress(DISCLOSURE, 17, 8, failed=1, last_provider_error_type="provider_rejected")
    assert _stages(
        {DISCLOSURE: rejected},
        run_status="failed",
        current_node=None,
        failure_node="run_disclosure_comparison",
    )["disclosure_comparison"]["retryable"] is False

    finished_with_review = _stages(
        {DISCLOSURE: _progress(DISCLOSURE, 17, 17, review=2)},
        completed_nodes=ALL_NODES,
        current_node=None,
        run_status="analyzing_contradictions",
    )
    assert finished_with_review["disclosure_comparison"]["status"] == "requires_review"
    assert finished_with_review["disclosure_comparison"]["requires_review_items"] == 2


def test_overall_percent_comes_from_real_work_never_from_time() -> None:
    stages = list(_stages({DISCLOSURE: _progress(DISCLOSURE, 10, 5)}).values())
    fraction = current_stage_fraction(stages)

    assert fraction == 0.5
    assert _progress_percent(["validate_analysis_request"], "comparing_disclosures", 0.0) == 8
    assert _progress_percent(["validate_analysis_request"], "comparing_disclosures", fraction) == 12
    assert _progress_percent([], "failed", 0.0) == 0
    assert _progress_percent(ALL_NODES, "completed", 0.0) == 100
    assert _progress_percent(ALL_NODES * 3, "queued", 1.0) == 95  # capped below "done"


def test_the_progress_payload_validates_against_the_public_schema() -> None:
    stages = list(
        _stages(
            {DISCLOSURE: _progress(DISCLOSURE, 4, 2, parts=(_part(1, "completed"),))}
        ).values()
    )

    payload = AnalysisProgressResponse(
        status="comparing_disclosures",
        current_node="run_disclosure_comparison",
        completed_nodes=[],
        progress_percent=10,
        retryable=None,
        stages=stages,
    )

    assert payload.stages[0].parts[0].estimated_input_tokens == 4000
    assert payload.stages[0].actual_total_tokens is None


# --- report data quality -----------------------------------------------------------------------


def test_the_report_states_what_the_model_could_not_analyse() -> None:
    kinds = ("weakened", "requires_review", "requires_review")
    changes = [SimpleNamespace(change_type=kind) for kind in kinds]
    quality = _data_quality(changes, {CLAIMS: _progress(CLAIMS, 6, 6, review=2)})

    assert quality["complete"] is False
    assert quality["disclosure_passages_requires_review"] == 2
    assert quality["claim_passages_requires_review"] == 2
    assert len(quality["notes"]) == 2
    summary = _summary({"weakened": 1}, {"verified": 1}, {"total_candidates": 0}, quality)
    assert "Data-quality warning" in summary and "2 disclosure passage(s)" in summary

    clean = _data_quality([SimpleNamespace(change_type="weakened")], {})
    assert clean["complete"] is True and clean["notes"] == []
    assert "Data-quality" not in _summary({}, {}, {}, clean)


# --- canary helper (no provider contact) -------------------------------------------------


def _load_canary():
    path = Path(__file__).resolve().parents[2] / "scripts" / "gemini_multi_item_canary.py"
    spec = importlib.util.spec_from_file_location("gemini_multi_item_canary", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CanaryClassifier:
    model_name = "gemini-test"
    batch_prompt_version = "batch-v1"
    batch_fixed_overhead_tokens = 100

    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour

    async def classify_batch(self, items):
        from app.ai.inference import record_usage
        from app.ai.openai_compatible import ProviderRequestError
        from app.ai.semantic_change import ChangeClassificationResult

        if self.behaviour == "429":
            raise ProviderRequestError(
                "request failed Bearer sk-secret-token",
                provider="p",
                provider_type="t",
                model="m",
                status_code=429,
                retry_count=3,
                retry_after_seconds=12.0,
                error_category="rate_limited",
                error_subtype="rate_limited_short_term",
            )
        record_usage({"prompt_tokens": 500, "completion_tokens": 90, "total_tokens": 590})
        result = ChangeClassificationResult(
            change_type="weakened",
            summary="s",
            explanation="e",
            confidence=0.8,
            risk_category="liquidity",
            materiality_reason="m",
        )
        ids = [item_id for item_id, _ in items]
        if self.behaviour == "missing":
            return {ids[0]: result, ids[1]: None, **({ids[2]: result} if len(ids) > 2 else {})}
        return {item_id: result for item_id in ids}


@pytest.mark.asyncio
async def test_the_canary_reports_a_safe_summary_of_mapping_schema_and_usage() -> None:
    canary = _load_canary()

    summary = await canary.run_canary(_CanaryClassifier("ok"), 3)

    assert summary["ok"] is True and summary["items_requested"] == 3
    assert [item["valid"] for item in summary["items"]] == [True, True, True]
    assert summary["actual_usage"] == {
        "input_tokens": 500,
        "output_tokens": 90,
        "total_tokens": 590,
        "requests_reporting_usage": 1,
    }
    assert summary["estimated_input_tokens"] > 100


@pytest.mark.asyncio
async def test_the_canary_fails_on_a_missing_item_and_never_leaks_secrets() -> None:
    canary = _load_canary()

    missing = await canary.run_canary(_CanaryClassifier("missing"), 3)
    assert missing["ok"] is False
    assert [item["valid"] for item in missing["items"]] == [True, False, True]

    limited = await canary.run_canary(_CanaryClassifier("429"), 2)
    assert limited["ok"] is False
    assert limited["error"]["subtype"] == "rate_limited_short_term"
    assert limited["error"]["retryable"] is True and limited["actual_usage"] is None
    dumped = json.dumps(limited)
    assert "sk-secret-token" not in dumped and "Bearer" not in dumped
