from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.models import Filing, XbrlFact
from app.services.derived_financial_metric_service import _gross_margin_status


def filing(accession_number: str = "0000000100-26-000002") -> Filing:
    return Filing(
        company_id=uuid4(),
        accession_number=accession_number,
        form_type="10-Q",
        filing_date=date(2026, 8, 1),
        report_period=date(2026, 6, 30),
        primary_document="current.htm",
        source_url="https://example.test/current.htm",
        raw_metadata={},
    )


def fact(
    *,
    concept: str,
    value: Decimal,
    unit: str = "USD",
    accession_number: str = "0000000100-26-000002",
    start_date: date = date(2026, 4, 1),
    end_date: date = date(2026, 6, 30),
) -> XbrlFact:
    return XbrlFact(
        company_id=uuid4(),
        taxonomy="us-gaap",
        concept=concept,
        unit=unit,
        value_numeric=value,
        start_date=start_date,
        end_date=end_date,
        fiscal_year=2026,
        fiscal_period="Q2",
        form_type="10-Q",
        accession_number=accession_number,
        raw_fact={},
    )


def test_gross_margin_requires_same_units_accession_and_period() -> None:
    base_filing = filing()
    revenue = fact(
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
        value=Decimal("100"),
    )
    gross_profit = fact(concept="GrossProfit", value=Decimal("40"))

    assert _gross_margin_status(base_filing, revenue, gross_profit) == "calculated"
    assert _gross_margin_status(base_filing, None, gross_profit) == "insufficient_inputs"
    assert (
        _gross_margin_status(
            base_filing,
            revenue,
            fact(concept="GrossProfit", value=Decimal("40"), unit="shares"),
        )
        == "unit_mismatch"
    )
    assert (
        _gross_margin_status(
            base_filing,
            revenue,
            fact(
                concept="GrossProfit",
                value=Decimal("40"),
                accession_number="0000000100-26-000099",
            ),
        )
        == "ambiguous_inputs"
    )
    assert (
        _gross_margin_status(
            base_filing,
            revenue,
            fact(
                concept="GrossProfit",
                value=Decimal("40"),
                start_date=date(2026, 1, 1),
                end_date=date(2026, 6, 30),
            ),
        )
        == "period_mismatch"
    )
    assert (
        _gross_margin_status(
            base_filing,
            fact(
                concept="RevenueFromContractWithCustomerExcludingAssessedTax",
                value=Decimal("0"),
            ),
            gross_profit,
        )
        == "zero_denominator"
    )
