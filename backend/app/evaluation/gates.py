from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: str
    message: str
    metric_path: str | None = None


DEFAULT_TOLERANCE = 0.0001


def evaluate_quality_gates(
    report: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[dict[str, str | None]]:
    gates = [
        _hard_gate_not_failed(report, "dataset_validation"),
        _hard_gate_metric_zero_if_evaluated(
            report,
            "phase4_financial_verification",
            ["metrics", "unsafe_period_match_rate"],
            "unsafe_period_match_rate",
        ),
        _hard_gate_metric_zero_if_evaluated(
            report,
            "phase4_financial_verification",
            ["metrics", "unsafe_unit_acceptance_rate"],
            "unsafe_unit_acceptance_rate",
        ),
    ]
    if baseline is None:
        gates.append(
            GateResult(
                gate="semantic_regression",
                status="not_evaluated",
                message="No approved baseline supplied; semantic regressions are reported only.",
            )
        )
    else:
        gates.extend(compare_against_baseline(baseline, report, tolerance=tolerance))
    return [gate.__dict__ for gate in gates]


def compare_against_baseline(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[GateResult]:
    results = []
    baseline_metrics = _flatten_metrics(baseline)
    candidate_metrics = _flatten_metrics(candidate)
    for path, baseline_value in sorted(baseline_metrics.items()):
        candidate_value = candidate_metrics.get(path)
        if not isinstance(baseline_value, int | float) or not isinstance(
            candidate_value,
            int | float,
        ):
            continue
        delta = candidate_value - baseline_value
        if delta < -tolerance:
            status = "regressed"
        elif delta > tolerance:
            status = "improved"
        else:
            status = "unchanged"
        results.append(
            GateResult(
                gate="baseline_comparison",
                status=status,
                message=(
                    f"{path}: baseline={baseline_value}, candidate={candidate_value}, "
                    f"delta={round(delta, 4)}"
                ),
                metric_path=path,
            )
        )
    return results


def _hard_gate_not_failed(report: dict[str, Any], name: str) -> GateResult:
    errors = report.get("dataset_errors", [])
    if errors:
        return GateResult(name, "failed", f"Dataset validation errors: {errors}")
    return GateResult(name, "passed", "Dataset manifests and examples are valid.")


def _hard_gate_metric_zero_if_evaluated(
    report: dict[str, Any],
    suite: str,
    path: list[str],
    gate_name: str,
) -> GateResult:
    value = _suite_metric(report, suite, path)
    if not isinstance(value, dict) or value.get("status") != "evaluated":
        return GateResult(
            gate_name,
            "not_evaluated",
            "Metric was not evaluated.",
            ".".join(path),
        )
    if value.get("value") == 0:
        return GateResult(gate_name, "passed", "Evaluated unsafe rate is zero.", ".".join(path))
    return GateResult(
        gate_name,
        "failed",
        f"Expected zero, observed {value.get('value')}.",
        ".".join(path),
    )


def _suite_metric(report: dict[str, Any], suite: str, path: list[str]) -> Any:
    for suite_result in report.get("suites", []):
        if suite_result.get("suite") == suite:
            current: Any = suite_result
            for key in path:
                if not isinstance(current, dict):
                    return None
                current = current.get(key)
            return current
    return None


def _flatten_metrics(payload: dict[str, Any], prefix: str = "") -> dict[str, float]:
    values: dict[str, float] = {}
    if isinstance(payload, dict):
        if payload.get("status") == "evaluated" and isinstance(payload.get("value"), int | float):
            values[prefix.rstrip(".")] = float(payload["value"])
        for key, value in payload.items():
            values.update(_flatten_metrics(value, f"{prefix}{key}."))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            values.update(_flatten_metrics(item, f"{prefix}{index}."))
    return values
