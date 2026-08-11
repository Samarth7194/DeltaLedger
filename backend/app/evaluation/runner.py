from __future__ import annotations

import asyncio
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evaluation.datasets import (
    EVALUATION_ROOT,
    evaluation_manifests,
    load_dataset_examples,
    load_manifest,
    validate_examples,
)
from app.evaluation.evaluators import (
    evaluate_manifest,
    human_review_metrics,
    workflow_operational_metrics,
)
from app.evaluation.gates import evaluate_quality_gates
from app.evaluation.reports import write_json_report, write_markdown_report

EVALUATOR_VERSION = "phase8-evaluator-v1"


async def run_benchmark(
    *,
    suite: str = "all",
    offline: bool = True,
    output_dir: Path | None = None,
    baseline_path: Path | None = None,
) -> dict[str, Any]:
    if not offline:
        raise ValueError("Real-model benchmark mode is not configured for automatic local runs.")
    dataset_errors = []
    suite_results = []
    manifests = [load_manifest(path) for path in evaluation_manifests()]
    selected = [manifest for manifest in manifests if suite == "all" or manifest.task == suite]
    if not selected:
        raise ValueError(f"No evaluation suite matched: {suite}")
    for manifest in selected:
        try:
            validate_examples(manifest, load_dataset_examples(manifest))
            suite_results.append((await evaluate_manifest(manifest)).__dict__)
        except Exception as exc:  # record per-suite evaluation failure
            dataset_errors.append(
                {
                    "dataset_name": manifest.dataset_name,
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                }
            )
    report: dict[str, Any] = {
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "status": "completed" if not dataset_errors else "partial",
        "offline": offline,
        "evaluator_version": EVALUATOR_VERSION,
        "code_version": _git_revision(),
        "suite_filter": suite,
        "dataset_errors": dataset_errors,
        "suites": sorted(suite_results, key=lambda item: item["suite"]),
        "human_review": human_review_metrics([]),
        "workflow_operations": workflow_operational_metrics([]),
        "model_cost": {
            "status": "not_evaluated",
            "reason": "Offline fake-provider run has no model cost data.",
        },
        "latency": {
            "status": "not_evaluated",
            "reason": "Offline runner does not create stable latency gates.",
        },
    }
    baseline = _load_json(baseline_path) if baseline_path and baseline_path.exists() else None
    report["quality_gates"] = evaluate_quality_gates(report, baseline=baseline)
    if output_dir is not None:
        write_json_report(report, output_dir / "phase8_candidate_report.json")
        write_markdown_report(report, output_dir / "phase8_candidate_report.md")
    return report


def run_benchmark_sync(**kwargs) -> dict[str, Any]:
    return asyncio.run(run_benchmark(**kwargs))


def default_report_dir() -> Path:
    return EVALUATION_ROOT / "reports"


def _git_revision() -> str | None:
    repo_root = Path(__file__).resolve().parents[3]
    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                "core.excludesfile=",
                "-c",
                f"safe.directory={repo_root.as_posix()}",
                "rev-parse",
                "--short",
                "HEAD",
            ],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return completed.stdout.strip() or None


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))
