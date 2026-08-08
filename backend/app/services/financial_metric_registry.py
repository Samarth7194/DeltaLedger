from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.metric_resolution import MetricResolutionProvider
from app.core.config import Settings
from app.db.models import FinancialMetricConcept, FinancialMetricDefinition
from app.repositories.financial_repository import FinancialRepository


@dataclass(frozen=True)
class MetricResolution:
    status: str
    metric: FinancialMetricDefinition | None
    confidence: float
    reason: str


TOKEN_RE = re.compile(r"[^a-z0-9]+")


class FinancialMetricRegistry:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: MetricResolutionProvider | None = None,
    ) -> None:
        self.repo = FinancialRepository(session)
        self.settings = settings
        self.provider = provider

    async def resolve_metric(self, claim_text: str) -> MetricResolution:
        definitions = await self.repo.list_metric_definitions(active_only=True)
        normalized_text = _normalize(claim_text)
        exact_matches = []
        loose_matches = []
        for metric in definitions:
            aliases = [metric.canonical_name, *list(metric.aliases or [])]
            for alias in aliases:
                normalized_alias = _normalize(alias)
                if normalized_alias == normalized_text:
                    exact_matches.append(metric)
                elif _contains_phrase(normalized_text, normalized_alias):
                    loose_matches.append(metric)
        matches = exact_matches or _dedupe_metrics(loose_matches)
        if len(matches) == 1:
            return MetricResolution("resolved", matches[0], 1.0, "Resolved by metric alias.")
        if len(matches) > 1:
            return MetricResolution(
                "ambiguous",
                None,
                0.0,
                "Multiple metric aliases matched.",
            )
        if self.provider is not None:
            result = await self.provider.resolve(
                claim_text,
                [metric.canonical_name for metric in definitions],
            )
            if (
                result.canonical_name
                and result.confidence >= self.settings.metric_resolution_min_confidence
            ):
                metric = next(
                    item for item in definitions if item.canonical_name == result.canonical_name
                )
                return MetricResolution("resolved", metric, result.confidence, result.reason)
            if result.canonical_name:
                return MetricResolution("ambiguous", None, result.confidence, result.reason)
        return MetricResolution("unsupported", None, 0.0, "No registered metric matched.")

    async def concepts_for_metric(
        self, metric_definition_id
    ) -> list[FinancialMetricConcept]:
        return await self.repo.list_metric_concepts(metric_definition_id)


def _normalize(value: str) -> str:
    return TOKEN_RE.sub(" ", value.lower()).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _dedupe_metrics(
    metrics: list[FinancialMetricDefinition],
) -> list[FinancialMetricDefinition]:
    by_name = {metric.canonical_name: metric for metric in metrics}
    return list(by_name.values())
