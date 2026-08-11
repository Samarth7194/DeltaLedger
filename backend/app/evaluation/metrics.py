from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass

NOT_EVALUATED = "not_evaluated"
NO_DATA = "no_data"


@dataclass(frozen=True)
class LabelScore:
    label: str
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    precision: float | str
    recall: float | str
    f1: float | str


def metric(
    value: float | int | str,
    *,
    n: int,
    status: str = "evaluated",
) -> dict[str, object]:
    return {"value": _round(value), "n": n, "status": status}


def not_evaluated(reason: str, *, n: int = 0) -> dict[str, object]:
    return {"value": NOT_EVALUATED, "n": n, "status": NOT_EVALUATED, "reason": reason}


def no_data(reason: str) -> dict[str, object]:
    return {"value": NO_DATA, "n": 0, "status": NO_DATA, "reason": reason}


def classification_report(
    expected: list[str],
    predicted: list[str],
    *,
    labels: list[str] | None = None,
) -> dict[str, object]:
    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted lists must have the same length.")
    if not expected:
        return {"accuracy": no_data("No labelled examples."), "per_label": {}}
    label_values = labels or sorted(set(expected) | set(predicted))
    per_label = {}
    for label in label_values:
        tp = sum(
            1
            for exp, pred in zip(expected, predicted, strict=True)
            if exp == pred == label
        )
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
        tn = len(expected) - tp - fp - fn
        per_label[label] = asdict(
            LabelScore(
                label=label,
                true_positive=tp,
                false_positive=fp,
                false_negative=fn,
                true_negative=tn,
                precision=_ratio_or_status(tp, tp + fp),
                recall=_ratio_or_status(tp, tp + fn),
                f1=_f1(tp, fp, fn),
            )
        )
    matches = sum(1 for exp, pred in zip(expected, predicted, strict=True) if exp == pred)
    f1_values = [
        item["f1"] for item in per_label.values() if isinstance(item["f1"], int | float)
    ]
    weights = Counter(expected)
    weighted_numerator = 0.0
    weighted_denominator = 0
    for label, count in weights.items():
        value = per_label[label]["f1"]
        if isinstance(value, int | float):
            weighted_numerator += value * count
            weighted_denominator += count
    return {
        "accuracy": metric(matches / len(expected), n=len(expected)),
        "macro_f1": metric(
            sum(f1_values) / len(f1_values) if f1_values else NOT_EVALUATED,
            n=len(expected),
            status="evaluated" if f1_values else NOT_EVALUATED,
        ),
        "weighted_f1": metric(
            weighted_numerator / weighted_denominator if weighted_denominator else NOT_EVALUATED,
            n=len(expected),
            status="evaluated" if weighted_denominator else NOT_EVALUATED,
        ),
        "per_label": per_label,
        "confusion_matrix": confusion_matrix(expected, predicted, labels=label_values),
    }


def confusion_matrix(
    expected: list[str],
    predicted: list[str],
    *,
    labels: list[str] | None = None,
) -> dict[str, dict[str, int]]:
    label_values = labels or sorted(set(expected) | set(predicted))
    matrix = {label: {inner: 0 for inner in label_values} for label in label_values}
    for exp, pred in zip(expected, predicted, strict=True):
        matrix.setdefault(exp, {inner: 0 for inner in label_values})
        matrix[exp][pred] = matrix[exp].get(pred, 0) + 1
    return matrix


def false_positive_rate(expected: list[bool], predicted: list[bool]) -> dict[str, object]:
    if len(expected) != len(predicted):
        raise ValueError("Expected and predicted lists must have the same length.")
    tn = sum(1 for exp, pred in zip(expected, predicted, strict=True) if not exp and not pred)
    fp = sum(1 for exp, pred in zip(expected, predicted, strict=True) if not exp and pred)
    denominator = fp + tn
    if denominator == 0:
        return not_evaluated("Dataset has no negative controls.", n=len(expected))
    return metric(fp / denominator, n=len(expected))


def ranking_metrics(
    examples: list[dict[str, object]],
    *,
    system_name: str,
    ks: Iterable[int] = (1, 5, 10),
) -> dict[str, object]:
    evaluable = [example for example in examples if example.get("relevant_documents")]
    if not evaluable:
        return {"status": NOT_EVALUATED, "reason": "No examples with relevance labels."}
    k_values = sorted(set(ks))
    recalls = {k: [] for k in k_values}
    precisions = {k: [] for k in k_values if k != 1}
    ndcgs = {k: [] for k in k_values if k != 1}
    reciprocal_ranks = []
    hit_rates = {k: [] for k in k_values}
    for example in evaluable:
        relevant = example["relevant_documents"]
        if isinstance(relevant, list):
            grades = {str(item): 1.0 for item in relevant}
        else:
            grades = {str(key): float(value) for key, value in dict(relevant).items()}
        ranking = [str(item) for item in dict(example["rankings"]).get(system_name, [])]
        first_rank = next(
            (index for index, doc_id in enumerate(ranking, start=1) if doc_id in grades),
            None,
        )
        reciprocal_ranks.append(0.0 if first_rank is None else 1.0 / first_rank)
        for k in k_values:
            top = ranking[:k]
            hits = sum(1 for doc_id in top if doc_id in grades)
            recalls[k].append(hits / len(grades))
            hit_rates[k].append(1.0 if hits else 0.0)
            if k in precisions:
                precisions[k].append(hits / k)
            if k in ndcgs:
                ndcgs[k].append(_ndcg(top, grades, k))
    result: dict[str, object] = {
        "system": system_name,
        "query_count": len(evaluable),
        "mrr": metric(_mean(reciprocal_ranks), n=len(evaluable)),
    }
    for k in k_values:
        result[f"recall@{k}"] = metric(_mean(recalls[k]), n=len(evaluable))
        result[f"hit_rate@{k}"] = metric(_mean(hit_rates[k]), n=len(evaluable))
        if k in precisions:
            result[f"precision@{k}"] = metric(_mean(precisions[k]), n=len(evaluable))
        if k in ndcgs:
            result[f"ndcg@{k}"] = metric(_mean(ndcgs[k]), n=len(evaluable))
    return result


def brier_score(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return no_data("No confidence-labelled predictions.")
    values = []
    for row in rows:
        confidence = float(row["confidence"])
        correct = 1.0 if bool(row["correct"]) else 0.0
        values.append((confidence - correct) ** 2)
    return metric(_mean(values), n=len(rows))


def expected_calibration_error(
    rows: list[dict[str, object]],
    *,
    bucket_count: int = 10,
) -> dict[str, object]:
    if not rows:
        return no_data("No confidence-labelled predictions.")
    buckets = [[] for _ in range(bucket_count)]
    for row in rows:
        confidence = max(0.0, min(1.0, float(row["confidence"])))
        index = min(bucket_count - 1, int(confidence * bucket_count))
        buckets[index].append((confidence, 1.0 if bool(row["correct"]) else 0.0))
    total = len(rows)
    ece = 0.0
    details = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            details.append({"bucket": index, "count": 0})
            continue
        avg_conf = _mean([item[0] for item in bucket])
        accuracy = _mean([item[1] for item in bucket])
        ece += (len(bucket) / total) * abs(accuracy - avg_conf)
        details.append(
            {
                "bucket": index,
                "count": len(bucket),
                "avg_confidence": _round(avg_conf),
                "accuracy": _round(accuracy),
            }
        )
    return {"value": _round(ece), "n": total, "status": "evaluated", "buckets": details}


def _ndcg(
    ranking: list[str],
    grades: dict[str, float],
    k: int,
) -> float:
    dcg = sum(
        (2 ** grades.get(doc_id, 0.0) - 1) / math.log2(index + 1)
        for index, doc_id in enumerate(ranking[:k], start=1)
    )
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum((2**grade - 1) / math.log2(index + 1) for index, grade in enumerate(ideal, start=1))
    return 0.0 if idcg == 0 else dcg / idcg


def _f1(tp: int, fp: int, fn: int) -> float | str:
    precision = _ratio_or_status(tp, tp + fp)
    recall = _ratio_or_status(tp, tp + fn)
    if not isinstance(precision, int | float) or not isinstance(recall, int | float):
        return NOT_EVALUATED
    return _ratio_or_status(2 * precision * recall, precision + recall)


def _ratio_or_status(numerator: float, denominator: float) -> float | str:
    if denominator == 0:
        return NOT_EVALUATED
    return _round(numerator / denominator)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _round(value: float | int | str) -> float | int | str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    return round(value, 4)
