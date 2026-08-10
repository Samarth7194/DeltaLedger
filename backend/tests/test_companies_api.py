from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import create_app


@dataclass(frozen=True)
class FakeCompany:
    id: uuid.UUID
    cik: str
    ticker: str | None
    legal_name: str
    exchange: str | None
    industry: str | None
    fiscal_year_end: str | None
    is_active: bool


@dataclass(frozen=True)
class FakeFiling:
    id: uuid.UUID
    company_id: uuid.UUID
    accession_number: str
    form_type: str
    filing_date: date
    report_period: date | None
    primary_document: str
    source_url: str
    storage_key: str | None
    content_hash: str | None
    ingestion_status: str
    parser_version: str | None
    raw_metadata: dict[str, Any]


def test_companies_endpoint_returns_browse_metadata(monkeypatch) -> None:
    company_id = uuid.uuid4()
    company = FakeCompany(
        id=company_id,
        cik="0000320193",
        ticker="AAPL",
        legal_name="Apple Inc.",
        exchange="NASDAQ",
        industry="Technology",
        fiscal_year_end="0930",
        is_active=True,
    )
    filing = _filing(company_id, date(2024, 8, 2), date(2024, 6, 29), "processed")

    async def fake_list_companies(self, **_kwargs):
        return [company]

    async def fake_latest_filing(self, _company_id):
        return filing

    async def fake_filing_count(self, _company_id):
        return 3

    monkeypatch.setattr(
        "app.api.routes.companies.CompanyRepository.list_companies",
        fake_list_companies,
    )
    monkeypatch.setattr(
        "app.api.routes.companies.CompanyRepository.latest_filing",
        fake_latest_filing,
    )
    monkeypatch.setattr(
        "app.api.routes.companies.CompanyRepository.filing_count",
        fake_filing_count,
    )

    with _client() as client:
        response = client.get("/api/v1/companies?search=apple")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"][0]["ticker"] == "AAPL"
    assert payload["data"][0]["filing_count"] == 3
    assert payload["data"][0]["latest_ingestion_status"] == "processed"


def test_company_filings_endpoint_returns_valid_selection_rows(monkeypatch) -> None:
    company_id = uuid.uuid4()
    company = FakeCompany(
        id=company_id,
        cik="0000789019",
        ticker="MSFT",
        legal_name="Microsoft Corporation",
        exchange="NASDAQ",
        industry="Technology",
        fiscal_year_end="0630",
        is_active=True,
    )
    filings = [
        _filing(company_id, date(2024, 10, 30), date(2024, 9, 30), "processed"),
        _filing(company_id, date(2024, 7, 30), date(2024, 6, 30), "processed"),
    ]

    async def fake_get(self, _company_id):
        return company

    async def fake_list_company_filings(self, _company_id, **_kwargs):
        return filings

    monkeypatch.setattr("app.api.routes.companies.CompanyRepository.get", fake_get)
    monkeypatch.setattr(
        "app.api.routes.companies.FilingRepository.list_company_filings",
        fake_list_company_filings,
    )

    with _client() as client:
        response = client.get(f"/api/v1/companies/{company_id}/filings?form_type=10-Q")

    assert response.status_code == 200
    payload = response.json()
    assert [item["report_period"] for item in payload["data"]] == ["2024-09-30", "2024-06-30"]
    assert payload["data"][0]["ingestion_status"] == "processed"


def _filing(
    company_id: uuid.UUID,
    filing_date: date,
    report_period: date,
    ingestion_status: str,
) -> FakeFiling:
    return FakeFiling(
        id=uuid.uuid4(),
        company_id=company_id,
        accession_number=f"0000000000-{report_period:%y%m%d}",
        form_type="10-Q",
        filing_date=filing_date,
        report_period=report_period,
        primary_document="form10q.htm",
        source_url="https://www.sec.gov/Archives/example",
        storage_key="filings/example.htm",
        content_hash="abc123",
        ingestion_status=ingestion_status,
        parser_version="phase2",
        raw_metadata={},
    )


def _client() -> TestClient:
    app = create_app()

    async def override_session():
        yield object()

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)
