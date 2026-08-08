from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MetricResolutionProviderResult:
    canonical_name: str | None
    confidence: float
    reason: str


class MetricResolutionProvider(Protocol):
    model_name: str
    model_version: str

    async def resolve(
        self,
        claim_text: str,
        candidate_metrics: list[str],
    ) -> MetricResolutionProviderResult: ...


class DeterministicFakeMetricResolver:
    model_name = "deterministic-metric-resolver"
    model_version = "phase4-v1"

    async def resolve(
        self,
        claim_text: str,
        candidate_metrics: list[str],
    ) -> MetricResolutionProviderResult:
        text = claim_text.lower()
        for metric in candidate_metrics:
            if metric.replace("_", " ") in text:
                return MetricResolutionProviderResult(
                    canonical_name=metric,
                    confidence=0.76,
                    reason="Metric phrase appeared in claim text.",
                )
        return MetricResolutionProviderResult(
            canonical_name=None,
            confidence=0.0,
            reason="No registered metric matched.",
        )
