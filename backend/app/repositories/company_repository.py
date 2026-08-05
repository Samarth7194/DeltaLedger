from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company


class CompanyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, company_id: uuid.UUID) -> Company | None:
        return await self.session.get(Company, company_id)

    async def get_by_ticker(self, ticker: str) -> Company | None:
        stmt = select(Company).where(Company.ticker == ticker.upper())
        return await self.session.scalar(stmt)

    async def get_by_cik(self, cik: str) -> Company | None:
        stmt = select(Company).where(Company.cik == cik.zfill(10))
        return await self.session.scalar(stmt)

    async def upsert_company(
        self,
        *,
        cik: str,
        ticker: str | None,
        legal_name: str,
        exchange: str | None = None,
        industry: str | None = None,
        fiscal_year_end: str | None = None,
    ) -> Company:
        normalized_cik = cik.zfill(10)
        company = await self.get_by_cik(normalized_cik)
        if company is None:
            company = Company(
                cik=normalized_cik,
                ticker=ticker.upper() if ticker else None,
                legal_name=legal_name,
            )
            self.session.add(company)

        company.ticker = ticker.upper() if ticker else company.ticker
        company.legal_name = legal_name
        company.exchange = exchange
        company.industry = industry
        company.fiscal_year_end = fiscal_year_end
        return company
