from datetime import date

from app.services.financial_periods import (
    classify_fact_period,
    comparison_period_supported,
    parse_comparison_basis,
)


def test_parse_comparison_basis_distinguishes_quarterly_ytd_and_prior_year() -> None:
    assert parse_comparison_basis("Revenue increased year over year.") == (
        "same_period_prior_year"
    )
    assert parse_comparison_basis("Revenue increased sequentially.") == "prior_quarter"
    assert parse_comparison_basis("Revenue for the six months ended June 30 grew.") == (
        "year_to_date"
    )


def test_classify_fact_period_distinguishes_instant_quarterly_ytd_and_annual() -> None:
    assert (
        classify_fact_period(
            start_date=None,
            end_date=None,
            instant_date=date(2026, 6, 30),
            fiscal_period="Q2",
        )
        == "instant"
    )
    assert (
        classify_fact_period(
            start_date=date(2026, 4, 1),
            end_date=date(2026, 6, 30),
            instant_date=None,
            fiscal_period="Q2",
        )
        == "quarterly_duration"
    )
    assert (
        classify_fact_period(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 6, 30),
            instant_date=None,
            fiscal_period="Q2",
        )
        == "year_to_date_duration"
    )
    assert (
        classify_fact_period(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            instant_date=None,
            fiscal_period="FY",
        )
        == "annual_duration"
    )


def test_comparison_period_supported_excludes_unspecified() -> None:
    assert comparison_period_supported("same_period_prior_year") is True
    assert comparison_period_supported("unspecified") is False
    assert comparison_period_supported(None) is False
