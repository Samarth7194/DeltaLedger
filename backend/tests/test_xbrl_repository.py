from __future__ import annotations

from datetime import date

from app.repositories.xbrl_repository import _parse_date


def test_parse_date_accepts_iso_date_string() -> None:
    assert _parse_date("2024-03-31") == date(2024, 3, 31)


def test_parse_date_passes_through_date_objects() -> None:
    value = date(2024, 6, 30)

    assert _parse_date(value) == value


def test_parse_date_returns_none_for_missing_value() -> None:
    assert _parse_date(None) is None
    assert _parse_date("") is None

