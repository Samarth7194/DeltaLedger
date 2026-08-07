from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class LabelMetrics:
    label: str
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    f1: float


def precision_recall_f1(
    expected: list[str],
    predicted: list[str],
    *,
    labels: list[str] | None = None,
) -> dict[str, LabelMetrics]:
    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted label lists must have equal length.")
    label_values = labels or sorted(set(expected) | set(predicted))
    metrics: dict[str, LabelMetrics] = {}
    for label in label_values:
        tp = sum(1 for exp, pred in zip(expected, predicted, strict=True) if exp == pred == label)
        fp = sum(
            1
            for exp, pred in zip(expected, predicted, strict=True)
            if exp != label and pred == label
        )
        fn = sum(
            1
            for exp, pred in zip(expected, predicted, strict=True)
            if exp == label and pred != label
        )
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        f1 = _ratio(2 * precision * recall, precision + recall)
        metrics[label] = LabelMetrics(
            label=label,
            true_positive=tp,
            false_positive=fp,
            false_negative=fn,
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1=round(f1, 4),
        )
    return metrics


def macro_f1(metrics: dict[str, LabelMetrics]) -> float:
    if not metrics:
        return 0.0
    return round(sum(item.f1 for item in metrics.values()) / len(metrics), 4)


def phase3_metrics(examples: list[dict[str, object]]) -> dict[str, object]:
    expected_types = [str(example["expected_change_type"]) for example in examples]
    predicted_types = [str(example["predicted_change_type"]) for example in examples]
    expected_risks = [str(example["expected_risk_category"]) for example in examples]
    predicted_risks = [str(example["predicted_risk_category"]) for example in examples]
    type_metrics = precision_recall_f1(expected_types, predicted_types)
    risk_metrics = precision_recall_f1(expected_risks, predicted_risks)
    return {
        "count": len(examples),
        "change_type_distribution": dict(Counter(expected_types)),
        "risk_category_distribution": dict(Counter(expected_risks)),
        "change_type_macro_f1": macro_f1(type_metrics),
        "risk_category_macro_f1": macro_f1(risk_metrics),
        "change_type": {label: metric.__dict__ for label, metric in type_metrics.items()},
        "risk_category": {label: metric.__dict__ for label, metric in risk_metrics.items()},
    }


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0
