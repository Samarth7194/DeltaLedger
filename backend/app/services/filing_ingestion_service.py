from __future__ import annotations

import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import SecClientError
from app.integrations.sec import SecClient
from app.integrations.storage import ObjectStorageClient
from app.repositories.company_repository import CompanyRepository
from app.repositories.filing_repository import FilingRepository
from app.repositories.xbrl_repository import XbrlRepository


class FilingIngestionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        sec_client: SecClient | None = None,
        storage_client: ObjectStorageClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.sec_client = sec_client or SecClient(settings)
        self.storage_client = storage_client or ObjectStorageClient(settings)
        self.companies = CompanyRepository(session)
        self.filings = FilingRepository(session)
        self.xbrl = XbrlRepository(session)

    async def ingest_company(self, *, ticker: str, quarters: int = 4) -> dict[str, object]:
        cik, legal_name = await self.sec_client.lookup_cik(ticker)
        submissions = await self.sec_client.get_submissions(cik)
        company = await self.companies.upsert_company(
            cik=cik,
            ticker=ticker,
            legal_name=str(submissions.get("name", legal_name)),
            exchange=_first_or_none(submissions.get("exchanges")),
            industry=submissions.get("sicDescription"),
            fiscal_year_end=submissions.get("fiscalYearEnd"),
        )
        await self.session.flush()

        filing_metadata = await self.sec_client.list_recent_10q_filings(cik, quarters)
        filings_seen: list[str] = []
        for metadata in filing_metadata:
            filing = await self.filings.create_or_update_filing(
                company_id=company.id,
                accession_number=metadata.accession_number,
                form_type=metadata.form_type,
                filing_date=metadata.filing_date,
                report_period=metadata.report_period,
                primary_document=metadata.primary_document,
                source_url=metadata.source_url,
                raw_metadata=metadata.raw_metadata,
            )
            filings_seen.append(metadata.accession_number)
            try:
                content, content_type = await self.sec_client.get_filing_document(
                    metadata.source_url
                )
                if "html" not in content_type.lower() and "text" not in content_type.lower():
                    raise SecClientError(f"Unsupported SEC filing content type: {content_type}")
                content_hash = hashlib.sha256(content).hexdigest()
                storage_key = self._filing_storage_key(company.id, metadata.accession_number)
                stored_object = await self.storage_client.put_bytes(
                    bucket=self.settings.minio_bucket_filings,
                    key=storage_key,
                    content=content,
                    content_type=content_type,
                    checksum=content_hash,
                )
                filing.content_hash = content_hash
                filing.storage_key = stored_object.key
                filing.parser_version = self.settings.parser_version
                filing.ingestion_status = "downloaded"
                filing.raw_metadata = {
                    **filing.raw_metadata,
                    "content_type": content_type,
                    "content_length": len(content),
                }
            except Exception as exc:
                await self.filings.mark_ingestion_failed(filing, exc.__class__.__name__, str(exc))

        company_facts = await self.sec_client.get_company_facts(cik)
        flattened_facts = self.sec_client.flatten_company_facts(company_facts)
        fact_count = await self.xbrl.replace_company_facts(
            company_id=company.id,
            facts=flattened_facts,
        )
        await self.session.commit()

        return {
            "company_id": str(company.id),
            "ticker": company.ticker,
            "cik": company.cik,
            "filings_seen": filings_seen,
            "xbrl_facts_seen": fact_count,
        }

    def _filing_storage_key(self, company_id: uuid.UUID, accession_number: str) -> str:
        return f"sec-filings/{company_id}/{accession_number.replace('-', '')}.html"


def _first_or_none(value: object) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return None
