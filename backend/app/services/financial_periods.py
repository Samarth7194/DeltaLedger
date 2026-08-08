from __future__ import annotations

from datetime import date


def parse_comparison_basis(text: str) -> str | None:
    value = text.lower()
    if any(
        phrase in value
        for phrase in ("prior quarter", "sequentially", "quarter over quarter", "qoq")
    ):
        return "prior_quarter"
    if any(
        phrase in value
        for phrase in (
            "same quarter last year",
            "prior-year quarter",
            "prior year quarter",
        )
    ):
        return "prior_year_quarter"
    if any(
        phrase in value
        for phrase in (
            "same period last year",
            "same period prior year",
            "year over year",
            "year-over-year",
            "yoy",
        )
    ):
        return "same_period_prior_year"
    if any(
        phrase in value
        for phrase in ("prior-year ytd", "prior year ytd", "prior-year year to date")
    ):
        return "prior_year_ytd"
    if any(
        phrase in value
        for phrase in ("six months ended", "nine months ended", "year to date", "ytd")
    ):
        return "year_to_date"
    return None


def classify_fact_period(
    *,
    start_date: date | None,
    end_date: date | None,
    instant_date: date | None,
    fiscal_period: str | None = None,
) -> str:
    if instant_date is not None and start_date is None:
        return "instant"
    if start_date is None or end_date is None:
        return "other_duration"
    days = (end_date - start_date).days + 1
    fp = (fiscal_period or "").upper()
    if 75 <= days <= 105 and fp in {"Q1", "Q2", "Q3", "Q4"}:
        return "quarterly_duration"
    if 150 <= days <= 205 and fp in {"Q2", "Q3"}:
        return "year_to_date_duration"
    if 240 <= days <= 290 and fp == "Q3":
        return "year_to_date_duration"
    if 330 <= days <= 380 and fp in {"FY", "Q4"}:
        return "annual_duration"
    if 75 <= days <= 105:
        return "quarterly_duration"
    if 150 <= days <= 290:
        return "year_to_date_duration"
    if 330 <= days <= 380:
        return "annual_duration"
    return "other_duration"


def comparison_period_supported(basis: str | None) -> bool:
    return basis in {
        "prior_quarter",
        "prior_year_quarter",
        "same_period_prior_year",
        "year_to_date",
        "prior_year_ytd",
    }
