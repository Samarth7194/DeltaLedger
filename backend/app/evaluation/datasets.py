from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
EVALUATION_ROOT = BACKEND_ROOT / "evaluation"
TEST_FIXTURE_ROOT = BACKEND_ROOT / "tests" / "fixtures"


@dataclass(frozen=True)
class DatasetManifest:
    dataset_name: str
    dataset_version: str
    task: str
    description: str
    source_type: str
    example_count: int
    annotation_method: str
    review_status: str
    created_at: str
    labels: list[str]
    supported_metrics: list[str]
    limitations: list[str]
    examples_path: str | None = None
    adapter: str | None = None


def load_manifest(path: Path) -> DatasetManifest:
    data = load_json(path)
    required = {
        "dataset_name",
        "dataset_version",
        "task",
        "description",
        "source_type",
        "example_count",
        "annotation_method",
        "review_status",
        "created_at",
        "labels",
        "supported_metrics",
        "limitations",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"Dataset manifest {path} is missing fields: {missing}")
    return DatasetManifest(**data)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluation_manifests(root: Path = EVALUATION_ROOT / "datasets") -> list[Path]:
    return sorted(root.glob("*/manifest.json"))


def load_dataset_examples(manifest: DatasetManifest) -> list[dict[str, Any]]:
    if manifest.adapter == "phase3_fixture":
        return list(load_json(TEST_FIXTURE_ROOT / "comparison" / "phase3_examples.json"))
    if manifest.adapter == "phase4_fixture":
        return list(load_json(TEST_FIXTURE_ROOT / "financial_claims" / "phase4_examples.json"))
    if manifest.adapter == "phase5_fixture":
        payload = load_json(TEST_FIXTURE_ROOT / "contradictions" / "phase5_examples.json")
        return list(payload["examples"])
    if not manifest.examples_path:
        return []
    path = EVALUATION_ROOT / "datasets" / manifest.examples_path
    data = load_json(path)
    if isinstance(data, dict) and "examples" in data:
        return list(data["examples"])
    return list(data)


def validate_examples(manifest: DatasetManifest, examples: list[dict[str, Any]]) -> None:
    if manifest.example_count != len(examples):
        raise ValueError(
            f"{manifest.dataset_name} manifest declares {manifest.example_count} examples, "
            f"loaded {len(examples)}."
        )
    seen: set[str] = set()
    for example in examples:
        example_id = str(example.get("id") or example.get("query_id") or "")
        if not example_id:
            raise ValueError(f"{manifest.dataset_name} has an example without an id.")
        if example_id in seen:
            raise ValueError(f"{manifest.dataset_name} has duplicate example id {example_id}.")
        seen.add(example_id)


def validate_all_manifests() -> list[DatasetManifest]:
    manifests = [load_manifest(path) for path in evaluation_manifests()]
    for manifest in manifests:
        validate_examples(manifest, load_dataset_examples(manifest))
    return manifests
