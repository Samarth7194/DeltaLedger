from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.config import Settings
from app.db.models import FinancialMetricDefinition
from app.services.financial_metric_registry import FinancialMetricRegistry


@dataclass
class FakeRepo:
    definitions: list[FinancialMetricDefinition]

    async def list_metric_definitions(
        self, *, active_only: bool = True
    ) -> list[FinancialMetricDefinition]:
        return self.definitions


def metric(canonical_name: str, aliases: list[str]) -> FinancialMetricDefinition:
    return FinancialMetricDefinition(
        canonical_name=canonical_name,
        display_name=canonical_name.replace("_", " ").title(),
        metric_type="monetary",
        period_behavior="duration",
        preferred_unit_category="monetary",
        description="test metric",
        aliases=aliases,
    )


@pytest.mark.asyncio
async def test_metric_registry_resolves_aliases() -> None:
    registry = FinancialMetricRegistry(None, Settings(app_profile="local-cloud"))
    registry.repo = FakeRepo([metric("revenue", ["revenue", "net sales"])])

    result = await registry.resolve_metric("Net sales increased 12% year over year.")

    assert result.status == "resolved"
    assert result.metric is not None
    assert result.metric.canonical_name == "revenue"


@pytest.mark.asyncio
async def test_metric_registry_marks_multiple_alias_matches_ambiguous() -> None:
    registry = FinancialMetricRegistry(None, Settings(app_profile="local-cloud"))
    registry.repo = FakeRepo(
        [
            metric("revenue", ["sales"]),
            metric("gross_profit", ["profit"]),
        ]
    )

    result = await registry.resolve_metric("Sales profit increased.")

    assert result.status == "ambiguous"
    assert result.metric is None


@pytest.mark.asyncio
async def test_metric_registry_marks_unknown_claim_unsupported() -> None:
    registry = FinancialMetricRegistry(None, Settings(app_profile="local-cloud"))
    registry.repo = FakeRepo([metric("revenue", ["revenue"])])

    result = await registry.resolve_metric("Headcount changed modestly.")

    assert result.status == "unsupported"
    assert result.metric is None
