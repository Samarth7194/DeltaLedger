from __future__ import annotations

from pathlib import Path

import pytest

from app.evaluation.datasets import load_dataset_examples, load_manifest, validate_all_manifests
from app.evaluation.evaluators import evaluate_manifest
from app.evaluation.gates import evaluate_quality_gates
from app.evaluation.reports import markdown_report
from app.evaluation.runner import run_benchmark


def test_phase8_dataset_manifests_validate() -> None:
    manifests = validate_all_manifests()

    assert {manifest.task for manifest in manifests} >= {
        "retrieval",
        "phase3_disclosure_change",
        "phase4_financial_verification",
        "phase4_number_normalization",
        "phase5_contradiction",
        "evidence_quality",
        "real_sec_benchmark",
    }


@pytest.mark.asyncio
async def test_phase3_fixture_adapter_runs_real_deterministic_classifier() -> None:
    manifest = load_manifest(Path("evaluation/datasets/phase3/manifest.json"))
    examples = load_dataset_examples(manifest)
    result = await evaluate_manifest(manifest)

    assert len(examples) == 40
    assert result.metrics["change_detection"]["accuracy"]["status"] == "evaluated"
    assert result.metrics["section_matching"]["status"] == "not_evaluated"


@pytest.mark.asyncio
async def test_phase8_runner_writes_json_and_markdown_candidate_reports(tmp_path) -> None:
    report = await run_benchmark(output_dir=tmp_path)

    assert report["status"] == "completed"
    assert (tmp_path / "phase8_candidate_report.json").exists()
    assert (tmp_path / "phase8_candidate_report.md").exists()
    assert "not_evaluated" in (tmp_path / "phase8_candidate_report.md").read_text(
        encoding="utf-8"
    )


def test_quality_gates_do_not_fail_without_baseline_or_missing_metrics() -> None:
    report = {"dataset_errors": [], "suites": []}
    gates = evaluate_quality_gates(report, baseline=None)

    assert {gate["status"] for gate in gates} == {"passed", "not_evaluated"}


def test_markdown_report_includes_candidate_baseline_warning() -> None:
    markdown = markdown_report(
        {
            "run_id": "run",
            "status": "completed",
            "evaluator_version": "test",
            "created_at": "2026-08-09T00:00:00Z",
            "code_version": "abc",
            "suites": [],
            "quality_gates": [],
        }
    )

    assert "candidate artifact" in markdown
