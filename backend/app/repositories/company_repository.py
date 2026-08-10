from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, Filing


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

    async def list_companies(
        self,
        *,
        search: str | None = None,
        ticker: str | None = None,
        industry: str | None = None,
        is_active: bool | None = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Company]:
        stmt = select(Company)
        if is_active is not None:
            stmt = stmt.where(Company.is_active.is_(is_active))
        if ticker:
            stmt = stmt.where(Company.ticker == ticker.upper())
        if industry:
            stmt = stmt.where(Company.industry.ilike(f"%{industry}%"))
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Company.legal_name.ilike(pattern),
                    Company.ticker.ilike(pattern),
                    Company.cik.ilike(pattern),
                )
            )
        stmt = stmt.order_by(Company.ticker.asc().nullslast(), Company.legal_name.asc())
        stmt = stmt.limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all())

    async def filing_count(self, company_id: uuid.UUID) -> int:
        stmt = select(func.count(Filing.id)).where(Filing.company_id == company_id)
        return int(await self.session.scalar(stmt) or 0)

    async def latest_filing(self, company_id: uuid.UUID) -> Filing | None:
        stmt = (
            select(Filing)
            .where(Filing.company_id == company_id)
            .order_by(Filing.report_period.desc().nullslast(), Filing.filing_date.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def filing_status_counts(self, company_id: uuid.UUID) -> dict[str, int]:
        stmt = (
            select(Filing.ingestion_status, func.count(Filing.id))
            .where(Filing.company_id == company_id)
            .group_by(Filing.ingestion_status)
        )
        rows = (await self.session.execute(stmt)).all()
        return {str(status): int(count) for status, count in rows}

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
