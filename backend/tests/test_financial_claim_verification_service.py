from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.financial_claim_verification_service import FinancialClaimVerificationService
from app.services.xbrl_fact_resolution_service import FactResolutionResult


@pytest.mark.asyncio
async def test_absolute_claim_without_reported_value_is_insufficient_data() -> None:
    service = _service()
    claim = _claim(claim_type="absolute_value", reported_value=None)

    result = await service._calculate(claim, _resolved_fact("100.00"), None)

    assert result.verification_status == "insufficient_data"
    assert result.reported_vs_calculated_difference is None


@pytest.mark.asyncio
async def test_percentage_point_claim_without_reported_change_is_insufficient_data() -> None:
    service = _service()
    claim = _claim(
        claim_type="percentage_point_change",
        reported_change=None,
        direction="increase",
    )

    result = await service._calculate(
        claim,
        _resolved_fact("42.00"),
        _resolved_fact("40.00"),
    )

    assert result.verification_status == "insufficient_data"
    assert result.percentage_point_change == Decimal("2.0000")
    assert result.reported_vs_calculated_difference is None


def _service() -> FinancialClaimVerificationService:
    service = FinancialClaimVerificationService.__new__(FinancialClaimVerificationService)
    service.settings = Settings(app_profile="local-cloud")
    return service


def _claim(
    *,
    claim_type: str,
    reported_value: Decimal | None = None,
    reported_change: Decimal | None = None,
    direction: str | None = None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        claim_type=claim_type,
        reported_value=reported_value,
        reported_change=reported_change,
        direction=direction,
    )


def _resolved_fact(value: str) -> FactResolutionResult:
    fact = SimpleNamespace(id=uuid.uuid4(), value_numeric=Decimal(value))
    return FactResolutionResult(
        status="selected",
        selected_fact=fact,
        candidates=[],
        confidence=Decimal("0.9000"),
        reason="Selected for unit test.",
    )
