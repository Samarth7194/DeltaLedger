from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Filing


class FilingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, filing_id: uuid.UUID) -> Filing | None:
        return await self.session.get(Filing, filing_id)

    async def get_by_accession_number(self, accession_number: str) -> Filing | None:
        stmt = select(Filing).where(Filing.accession_number == accession_number)
        return await self.session.scalar(stmt)

    async def list_company_filings(
        self,
        company_id: uuid.UUID,
        *,
        form_type: str | None = "10-Q",
        ingestion_status: str | None = None,
        report_period_from: date | None = None,
        report_period_to: date | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Filing]:
        stmt = (
            select(Filing)
            .where(Filing.company_id == company_id)
            .order_by(Filing.report_period.desc().nullslast(), Filing.filing_date.desc())
        )
        if form_type:
            stmt = stmt.where(Filing.form_type == form_type)
        if ingestion_status:
            stmt = stmt.where(Filing.ingestion_status == ingestion_status)
        if report_period_from:
            stmt = stmt.where(Filing.report_period >= report_period_from)
        if report_period_to:
            stmt = stmt.where(Filing.report_period <= report_period_to)
        stmt = stmt.limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all())

    async def create_or_update_filing(
        self,
        *,
        company_id: uuid.UUID,
        accession_number: str,
        form_type: str,
        filing_date: date,
        report_period: date | None,
        primary_document: str,
        source_url: str,
        raw_metadata: dict[str, object],
    ) -> Filing:
        filing = await self.get_by_accession_number(accession_number)
        if filing is None:
            filing = Filing(
                company_id=company_id,
                accession_number=accession_number,
                form_type=form_type,
                filing_date=filing_date,
                report_period=report_period,
                primary_document=primary_document,
                source_url=source_url,
                raw_metadata=raw_metadata,
            )
            self.session.add(filing)
            return filing

        filing.form_type = form_type
        filing.filing_date = filing_date
        filing.report_period = report_period
        filing.primary_document = primary_document
        filing.source_url = source_url
        filing.raw_metadata = raw_metadata
        return filing

    async def mark_ingestion_failed(
        self,
        filing: Filing,
        error_code: str,
        error_message: str,
    ) -> None:
        filing.ingestion_status = "failed"
        filing.raw_metadata = {
            **filing.raw_metadata,
            "error_code": error_code,
            "error_message": error_message,
        }
