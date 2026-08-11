from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import ClaimVerification, FilingComparison
from app.repositories.financial_repository import FinancialRepository
from app.services.financial_periods import comparison_period_supported
from app.services.xbrl_fact_resolution_service import (
    FactResolutionResult,
    XbrlFactResolutionService,
)


class FinancialClaimVerificationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = FinancialRepository(session)
        self.resolver = XbrlFactResolutionService(session, settings)

    async def verify_claim(self, claim_id: uuid.UUID) -> ClaimVerification:
        claim = await self.repo.get_claim(claim_id)
        if claim is None:
            raise ValueError(f"Financial claim not found: {claim_id}")
        if claim.metric_definition_id is None:
            return await self._store_status(claim, "unsupported_metric", "Metric is unresolved.")
        filing = await self.repo.get_filing(claim.filing_id)
        metric = await self.repo.get_metric_by_name(claim.canonical_metric_name or "")
        if filing is None or metric is None:
            return await self._store_status(claim, "insufficient_data", "Missing filing or metric.")
        concepts = await self.repo.list_metric_concepts(metric.id)
        expected_period = _expected_period_type(metric.period_behavior, claim.comparison_basis)
        current = await self.resolver.resolve_fact(
            claim=claim,
            metric_concepts=concepts,
            target_filing=filing,
            role="current",
            expected_period_type=expected_period,
        )
        if current.status != "selected":
            return await self._store_status(claim, current.status, current.reason)
        comparison = None
        if claim.claim_type in {
            "percentage_change",
            "percentage_point_change",
            "directional_change",
            "comparative_statement",
            "ratio_change",
        }:
            comparison = await self._resolve_comparison(claim.id, claim.comparison_basis)
            if comparison is None:
                return await self._store_status(
                    claim,
                    "insufficient_data",
                    "Comparison basis or comparison filing is unresolved.",
                    current=current,
                )
        result = await self._calculate(claim, current, comparison)
        return await self.repo.upsert_verification(result)

    async def _resolve_comparison(
        self,
        claim_id: uuid.UUID,
        comparison_basis: str | None,
    ) -> FactResolutionResult | None:
        claim = await self.repo.get_claim(claim_id)
        if (
            claim is None
            or claim.comparison_id is None
            or not comparison_period_supported(comparison_basis)
        ):
            return None
        comparison = await self.session.get(FilingComparison, claim.comparison_id)
        if comparison is None:
            return None
        comparison_filing = await self.repo.get_filing(comparison.comparison_filing_id)
        if comparison_filing is None or claim.metric_definition_id is None:
            return None
        metric = await self.repo.get_metric_by_name(claim.canonical_metric_name or "")
        if metric is None:
            return None
        concepts = await self.repo.list_metric_concepts(metric.id)
        expected_period = _expected_period_type(metric.period_behavior, comparison_basis)
        resolved = await self.resolver.resolve_fact(
            claim=claim,
            metric_concepts=concepts,
            target_filing=comparison_filing,
            role="comparison",
            expected_period_type=expected_period,
        )
        return resolved if resolved.status == "selected" else resolved

    async def _calculate(
        self,
        claim,
        current: FactResolutionResult,
        comparison: FactResolutionResult | None,
    ) -> ClaimVerification:
        current_value = current.selected_fact.value_numeric if current.selected_fact else None
        comparison_value = (
            comparison.selected_fact.value_numeric
            if comparison and comparison.selected_fact
            else None
        )
        if current_value is None:
            return _verification(
                self.settings,
                claim,
                current,
                comparison,
                "insufficient_data",
                "Missing current numeric fact.",
            )
        if claim.claim_type == "absolute_value":
            reported = claim.reported_value
            diff = (
                abs((reported or Decimal("0")) - current_value)
                if reported is not None
                else None
            )
            tolerance = Decimal(str(self.settings.claim_absolute_tolerance))
            if diff is None:
                status = "insufficient_data"
            elif diff <= tolerance:
                status = "verified"
            else:
                status = "contradicted"
            return _verification(
                self.settings,
                claim,
                current,
                comparison,
                status,
                "Absolute claim compared with selected current fact.",
                current_value=current_value,
                reported_change=reported,
                difference=diff,
                tolerance=tolerance,
                calculation_type="absolute_value",
                formula="current_value",
            )
        if comparison is not None and comparison.status != "selected":
            return _verification(
                self.settings,
                claim,
                current,
                comparison,
                comparison.status,
                comparison.reason,
                current_value=current_value,
            )
        if comparison_value is None:
            return _verification(
                self.settings,
                claim,
                current,
                comparison,
                "insufficient_data",
                "Missing comparison numeric fact.",
                current_value=current_value,
            )
        absolute_change = current_value - comparison_value
        if claim.claim_type == "percentage_point_change":
            point_change = absolute_change.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            reported = claim.reported_change
            difference = (
                abs((reported or Decimal("0")) - point_change)
                if reported is not None
                else None
            )
            tolerance = Decimal(str(self.settings.claim_percentage_point_tolerance))
            direction_ok = _direction_ok(claim.direction, point_change)
            if difference is None:
                status = "insufficient_data"
            elif not direction_ok:
                status = "contradicted"
            elif difference == 0:
                status = "verified"
            elif difference is not None and difference <= tolerance:
                status = "approximately_verified"
            else:
                status = "contradicted"
            return _verification(
                self.settings,
                claim,
                current,
                comparison,
                status,
                "Percentage-point change calculated from selected facts.",
                current_value=current_value,
                comparison_value=comparison_value,
                absolute_change=absolute_change,
                percentage_point_change=point_change,
                reported_change=reported,
                difference=difference,
                tolerance=tolerance,
                calculation_type="percentage_point_change",
                formula="current_percentage - comparison_percentage",
            )
        if comparison_value == 0:
            return _verification(
                self.settings,
                claim,
                current,
                comparison,
                "zero_denominator",
                "Cannot calculate percentage change with zero comparison value.",
                current_value=current_value,
                comparison_value=comparison_value,
                absolute_change=absolute_change,
            )
        percentage_change = ((absolute_change / comparison_value) * Decimal("100")).quantize(
            Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )
        if claim.claim_type == "percentage_change":
            return _verify_change(
                self.settings,
                claim,
                current,
                comparison,
                current_value,
                comparison_value,
                absolute_change,
                percentage_change,
            )
        return _verification(
            self.settings,
            claim,
            current,
            comparison,
            "verified",
            "Directional claim matched selected facts.",
            current_value=current_value,
            comparison_value=comparison_value,
            absolute_change=absolute_change,
            percentage_change=percentage_change,
            calculation_type="directional_change",
            formula="current_value - comparison_value",
        )

    async def _store_status(
        self,
        claim,
        status: str,
        reason: str,
        *,
        current: FactResolutionResult | None = None,
    ) -> ClaimVerification:
        return await self.repo.upsert_verification(
            _verification(self.settings, claim, current, None, status, reason)
        )


def _verify_change(
    settings: Settings,
    claim,
    current: FactResolutionResult,
    comparison: FactResolutionResult | None,
    current_value: Decimal,
    comparison_value: Decimal,
    absolute_change: Decimal,
    percentage_change: Decimal,
) -> ClaimVerification:
    reported = claim.reported_change
    difference = (
        abs((reported or Decimal("0")) - percentage_change)
        if reported is not None
        else None
    )
    tolerance = Decimal(str(settings.claim_percent_tolerance))
    direction_ok = _direction_ok(claim.direction, percentage_change)
    if not direction_ok:
        status = "contradicted"
    elif difference is None:
        status = "insufficient_data"
    elif difference == 0:
        status = "verified"
    elif difference <= tolerance:
        status = "approximately_verified"
    else:
        status = "contradicted"
    return _verification(
        settings,
        claim,
        current,
        comparison,
        status,
        "Percentage change calculated from selected current and comparison facts.",
        current_value=current_value,
        comparison_value=comparison_value,
        absolute_change=absolute_change,
        percentage_change=percentage_change,
        reported_change=reported,
        difference=difference,
        tolerance=tolerance,
        calculation_type="percentage_change",
        formula="((current_value - comparison_value) / comparison_value) * 100",
    )


def _verification(
    settings: Settings,
    claim,
    current: FactResolutionResult | None,
    comparison: FactResolutionResult | None,
    status: str,
    reason: str,
    *,
    current_value: Decimal | None = None,
    comparison_value: Decimal | None = None,
    absolute_change: Decimal | None = None,
    percentage_change: Decimal | None = None,
    percentage_point_change: Decimal | None = None,
    reported_change: Decimal | None = None,
    difference: Decimal | None = None,
    tolerance: Decimal | None = None,
    calculation_type: str = "none",
    formula: str = "not_applicable",
) -> ClaimVerification:
    confidence = _confidence(current, comparison, status)
    return ClaimVerification(
        financial_claim_id=claim.id,
        current_xbrl_fact_id=(
            current.selected_fact.id if current and current.selected_fact else None
        ),
        comparison_xbrl_fact_id=(
            comparison.selected_fact.id if comparison and comparison.selected_fact else None
        ),
        verification_status=status,
        current_value=current_value,
        comparison_value=comparison_value,
        absolute_change=absolute_change,
        percentage_change=percentage_change,
        percentage_point_change=percentage_point_change,
        reported_change=reported_change,
        reported_vs_calculated_difference=difference,
        calculation_type=calculation_type,
        formula=formula,
        calculation_inputs={
            "current_fact_id": (
                str(current.selected_fact.id) if current and current.selected_fact else None
            ),
            "comparison_fact_id": (
                str(comparison.selected_fact.id)
                if comparison and comparison.selected_fact
                else None
            ),
            "current_value": str(current_value) if current_value is not None else None,
            "comparison_value": str(comparison_value) if comparison_value is not None else None,
        },
        calculation_output={
            "absolute_change": str(absolute_change) if absolute_change is not None else None,
            "percentage_change": str(percentage_change) if percentage_change is not None else None,
            "percentage_point_change": (
                str(percentage_point_change) if percentage_point_change is not None else None
            ),
            "difference": str(difference) if difference is not None else None,
        },
        tolerance_used=tolerance,
        verification_reason=reason,
        confidence=confidence,
        verification_version=settings.financial_verification_version,
    )


def _expected_period_type(period_behavior: str, comparison_basis: str | None) -> str | None:
    if period_behavior == "instant":
        return "instant"
    if comparison_basis in {"year_to_date", "prior_year_ytd"}:
        return "year_to_date_duration"
    return "quarterly_duration"


def _direction_ok(direction: str | None, calculated_change: Decimal) -> bool:
    if direction == "increase":
        return calculated_change > 0
    if direction == "decrease":
        return calculated_change < 0
    if direction == "unchanged":
        return calculated_change == 0
    return True


def _confidence(
    current: FactResolutionResult | None,
    comparison: FactResolutionResult | None,
    status: str,
) -> Decimal:
    base = Decimal("0.50")
    if current and current.selected_fact:
        base += current.confidence * Decimal("0.30")
    if comparison and comparison.selected_fact:
        base += comparison.confidence * Decimal("0.20")
    if status in {"verified", "approximately_verified"}:
        base += Decimal("0.05")
    return min(base, Decimal("0.9900")).quantize(Decimal("0.0001"))
