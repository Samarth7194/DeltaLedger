from __future__ import annotations

import uuid

from app.services.filing_ingestion_service import FilingIngestionService, _first_or_none


def test_first_or_none_handles_sec_exchange_lists() -> None:
    assert _first_or_none(["Nasdaq", "NYSE"]) == "Nasdaq"
    assert _first_or_none("NYSE") == "NYSE"
    assert _first_or_none([]) is None
    assert _first_or_none(None) is None


def test_filing_storage_key_is_stable_and_uses_accession_without_dashes() -> None:
    service = object.__new__(FilingIngestionService)
    company_id = uuid.UUID("00000000-0000-0000-0000-000000000123")

    key = service._filing_storage_key(company_id, "0000320193-24-000123")

    assert key == "sec-filings/00000000-0000-0000-0000-000000000123/000032019324000123.html"

