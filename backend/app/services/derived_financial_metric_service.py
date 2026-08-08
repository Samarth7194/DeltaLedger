from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import DerivedFinancialMetric, Filing, XbrlFact
from app.repositories.financial_repository import FinancialRepository
from app.services.financial_periods import classify_fact_period
from app.services.xbrl_fact_resolution_service import units_compatible


class DerivedFinancialMetricService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.repo = FinancialRepository(session)
        self.settings = settings

    async def calculate_gross_margin(
        self,
        *,
        filing: Filing,
        revenue_fact: XbrlFact | None,
        gross_profit_fact: XbrlFact | None,
    ) -> DerivedFinancialMetric:
        metric = await self.repo.get_metric_by_name("gross_margin")
        if metric is None:
            raise ValueError("gross_margin metric definition is missing.")
        status = _gross_margin_status(filing, revenue_fact, gross_profit_fact)
        value = None
        inputs = {}
        if status == "calculated" and revenue_fact and gross_profit_fact:
            value = (
                (gross_profit_fact.value_numeric / revenue_fact.value_numeric) * Decimal("100")
            ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            inputs = {
                "gross_profit": str(gross_profit_fact.value_numeric),
                "revenue": str(revenue_fact.value_numeric),
            }
        metric_row = DerivedFinancialMetric(
            metric_definition_id=metric.id,
            filing_id=filing.id,
            calculation_status=status,
            formula="GrossProfit / Revenue * 100",
            input_fact_ids=[
                str(fact.id)
                for fact in (gross_profit_fact, revenue_fact)
                if fact is not None
            ],
            calculation_inputs_snapshot=inputs,
            calculated_value=value,
            unit="percent" if value is not None else None,
            period_type=(
                classify_fact_period(
                    start_date=revenue_fact.start_date,
                    end_date=revenue_fact.end_date,
                    instant_date=revenue_fact.instant_date,
                    fiscal_period=revenue_fact.fiscal_period,
                )
                if revenue_fact is not None
                else None
            ),
            period_start=revenue_fact.start_date if revenue_fact is not None else None,
            period_end=revenue_fact.end_date if revenue_fact is not None else None,
            calculation_version=self.settings.financial_verification_version,
            assumptions={"requires_same_accession_period_and_usd_units": True},
        )
        return await self.repo.upsert_derived_metric(metric_row)


def _gross_margin_status(
    filing: Filing,
    revenue_fact: XbrlFact | None,
    gross_profit_fact: XbrlFact | None,
) -> str:
    if revenue_fact is None or gross_profit_fact is None:
        return "insufficient_inputs"
    if not units_compatible("monetary", revenue_fact.unit) or not units_compatible(
        "monetary", gross_profit_fact.unit
    ):
        return "unit_mismatch"
    if revenue_fact.accession_number != filing.accession_number or (
        gross_profit_fact.accession_number != filing.accession_number
    ):
        return "ambiguous_inputs"
    if revenue_fact.start_date != gross_profit_fact.start_date or (
        revenue_fact.end_date != gross_profit_fact.end_date
    ):
        return "period_mismatch"
    if revenue_fact.value_numeric in {None, Decimal("0")}:
        return "zero_denominator"
    if gross_profit_fact.value_numeric is None:
        return "insufficient_inputs"
    return "calculated"
