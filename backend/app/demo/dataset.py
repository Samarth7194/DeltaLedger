from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

DEMO_TICKER = "DLTA"


@dataclass(frozen=True)
class DemoFiling:
    accession_number: str
    filing_date: date
    report_period: date
    liquidity_text: str
    revenue_text: str
    revenue: Decimal


def build_demo_manifest() -> dict[str, Any]:
    previous = DemoFiling(
        accession_number="0000000000-25-000001",
        filing_date=date(2025, 5, 7),
        report_period=date(2025, 3, 31),
        liquidity_text="We expect existing cash resources to be sufficient.",
        revenue_text="Revenue increased 8% compared with the prior-year quarter.",
        revenue=Decimal("1000.000000"),
    )
    current = DemoFiling(
        accession_number="0000000000-25-000002",
        filing_date=date(2025, 8, 7),
        report_period=date(2025, 6, 30),
        liquidity_text=(
            "We expect existing cash resources and access to external financing to be "
            "sufficient, subject to market conditions."
        ),
        revenue_text="Revenue increased 12% compared with the prior-year quarter.",
        revenue=Decimal("1040.000000"),
    )
    return {
        "dataset_name": "deltaledger_demo_v1",
        "description": "Reduced-real style deterministic demo scenario for local walkthroughs.",
        "company": {
            "ticker": DEMO_TICKER,
            "cik": "0000000000",
            "legal_name": "DeltaLedger Demo Corporation",
            "industry": "Application Software",
        },
        "filings": {
            "previous": _filing_payload(previous),
            "current": _filing_payload(current),
        },
        "expected_outputs": {
            "disclosure_change": {
                "change_type": "weakened",
                "risk_category": "liquidity",
                "summary": (
                    "Current liquidity language adds external financing and "
                    "market-condition dependency."
                ),
            },
            "financial_claim": {
                "canonical_metric_name": "revenue",
                "claim_text": current.revenue_text,
                "reported_change": "12.000000",
                "reported_change_unit": "percent",
            },
            "xbrl_verification": {
                "current_revenue": "1040.000000",
                "previous_revenue": "1000.000000",
                "calculated_change_percent": "4.000000",
                "verification_status": "contradicted",
            },
            "potential_inconsistency": {
                "contradiction_type": "magnitude_overstatement",
                "severity": "high",
                "requires_human_review": True,
            },
            "report": {
                "status": "finalized",
                "evidence_backed": True,
            },
        },
        "limitations": [
            "Synthetic/reduced-real demo data for product walkthroughs.",
            "Not a real issuer filing and not an investment recommendation.",
        ],
    }


def _filing_payload(filing: DemoFiling) -> dict[str, str]:
    return {
        "accession_number": filing.accession_number,
        "filing_date": filing.filing_date.isoformat(),
        "report_period": filing.report_period.isoformat(),
        "liquidity_text": filing.liquidity_text,
        "revenue_text": filing.revenue_text,
        "revenue": str(filing.revenue),
    }
