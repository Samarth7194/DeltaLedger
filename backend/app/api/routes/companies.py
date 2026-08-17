from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    CompanyDetailResponse,
    CompanySummaryResponse,
    FilingSummaryResponse,
    ResponseEnvelope,
    ResponseMeta,
)
from app.core.auth import AuthPrincipal, require_role
from app.db.session import get_session
from app.repositories.company_repository import CompanyRepository
from app.repositories.filing_repository import FilingRepository

router = APIRouter(prefix="/companies")
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AnalystDep = Annotated[AuthPrincipal, Depends(require_role("analyst"))]


@router.get("")
async def list_companies(
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
    search: str | None = None,
    ticker: str | None = None,
    industry: str | None = None,
    is_active: bool | None = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResponseEnvelope:
    repo = CompanyRepository(session)
    companies = await repo.list_companies(
        search=search,
        ticker=ticker,
        industry=industry,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    data = [await _company_summary(repo, company) for company in companies]
    return ResponseEnvelope(
        data=[item.model_dump() for item in data],
        meta=_meta(request, {"limit": limit, "offset": offset}),
    )


@router.get("/{company_id}")
async def get_company(
    company_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
) -> ResponseEnvelope:
    repo = CompanyRepository(session)
    company = await repo.get(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found.")
    summary = await _company_summary(repo, company)
    data = CompanyDetailResponse(
        **summary.model_dump(),
        recent_status_counts=await repo.filing_status_counts(company.id),
    )
    return ResponseEnvelope(data=data.model_dump(), meta=_meta(request))


@router.get("/{company_id}/filings")
async def list_company_filings(
    company_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _principal: AnalystDep,
    form_type: str | None = "10-Q",
    ingestion_status: str | None = None,
    report_period_from: date | None = None,
    report_period_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResponseEnvelope:
    company_repo = CompanyRepository(session)
    if await company_repo.get(company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found.")
    filings = await FilingRepository(session).list_company_filings(
        company_id,
        form_type=form_type,
        ingestion_status=ingestion_status,
        report_period_from=report_period_from,
        report_period_to=report_period_to,
        limit=limit,
        offset=offset,
    )
    return ResponseEnvelope(
        data=[_filing_summary(filing).model_dump() for filing in filings],
        meta=_meta(request, {"limit": limit, "offset": offset}),
    )


async def _company_summary(repo: CompanyRepository, company: object) -> CompanySummaryResponse:
    latest = await repo.latest_filing(company.id)
    return CompanySummaryResponse(
        id=company.id,
        cik=company.cik,
        ticker=company.ticker,
        legal_name=company.legal_name,
        exchange=company.exchange,
        industry=company.industry,
        fiscal_year_end=company.fiscal_year_end,
        is_active=company.is_active,
        filing_count=await repo.filing_count(company.id),
        latest_filing_date=latest.filing_date if latest else None,
        latest_report_period=latest.report_period if latest else None,
        latest_ingestion_status=latest.ingestion_status if latest else None,
    )


def _filing_summary(filing: object) -> FilingSummaryResponse:
    return FilingSummaryResponse(
        id=filing.id,
        company_id=filing.company_id,
        accession_number=filing.accession_number,
        form_type=filing.form_type,
        filing_date=filing.filing_date,
        report_period=filing.report_period,
        primary_document=filing.primary_document,
        source_url=filing.source_url,
        storage_key=filing.storage_key,
        content_hash=filing.content_hash,
        ingestion_status=filing.ingestion_status,
        parser_version=filing.parser_version,
        raw_metadata=filing.raw_metadata,
    )


def _meta(request: Request, pagination: dict[str, object] | None = None) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", None),
        pagination=pagination,
    )
