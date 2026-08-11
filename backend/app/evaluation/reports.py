from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_report(report), encoding="utf-8")


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# DeltaLedger Evaluation Report",
        "",
        f"Run ID: `{report['run_id']}`",
        f"Status: `{report['status']}`",
        f"Evaluator version: `{report['evaluator_version']}`",
        f"Generated at: `{report['created_at']}`",
        f"Code version: `{report.get('code_version') or 'not_available'}`",
        "",
        "## Suites",
        "",
    ]
    for suite in report["suites"]:
        lines.extend(
            [
                f"### {suite['dataset_name']}",
                "",
                f"- Task: `{suite['suite']}`",
                f"- Dataset version: `{suite['dataset_version']}`",
                f"- Examples: `{suite['example_count']}`",
                "",
            ]
        )
        _append_metric_lines(lines, suite["metrics"])
        lines.append("")
    lines.extend(["## Quality Gates", ""])
    for gate in report.get("quality_gates", []):
        lines.append(f"- `{gate['status']}` {gate['gate']}: {gate['message']}")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Metrics are reported only when labelled data and evaluator predictions exist.",
            "- Label-only fixtures produce `not_evaluated` for prediction metrics "
            "that cannot be computed.",
            "- Offline benchmarks do not call live SEC endpoints or hosted model providers.",
            "- This report is a candidate artifact, not an approved baseline.",
            "",
        ]
    )
    return "\n".join(lines)


def _append_metric_lines(lines: list[str], payload: Any, prefix: str = "") -> None:
    if isinstance(payload, dict) and "status" in payload and "value" in payload:
        metric_name = prefix.rstrip(".") or "metric"
        value = payload["value"]
        n = payload.get("n", 0)
        status = payload["status"]
        reason = f" ({payload['reason']})" if payload.get("reason") else ""
        lines.append(
            f"- `{metric_name}`: `{value}` n={n} status=`{status}`{reason}"
        )
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"per_label", "confusion_matrix", "buckets", "errors", "failures"}:
                continue
            _append_metric_lines(lines, value, f"{prefix}{key}.")
