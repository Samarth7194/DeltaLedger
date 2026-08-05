from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, Filing, FilingChunk, FilingSection


def unit_vector(index: int, dimension: int = 1024) -> list[float]:
    vector = [0.0] * dimension
    vector[index] = 1.0
    return vector


async def reset_corpus(session: AsyncSession) -> None:
    await session.execute(delete(Company))
    await session.commit()


async def create_retrieval_corpus(session: AsyncSession) -> dict[str, object]:
    await reset_corpus(session)
    active = Company(cik="0000000001", ticker="ACTV", legal_name="Active Test Inc.")
    inactive = Company(
        cik="0000000002",
        ticker="INAC",
        legal_name="Inactive Test Inc.",
        is_active=False,
    )
    session.add_all([active, inactive])
    await session.flush()

    filing = Filing(
        company_id=active.id,
        accession_number="0000000001-26-000001",
        form_type="10-Q",
        filing_date=date(2026, 5, 1),
        report_period=date(2026, 3, 31),
        primary_document="active.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/1/1/active.htm",
        ingestion_status="processed",
        raw_metadata={},
    )
    other_filing = Filing(
        company_id=active.id,
        accession_number="0000000001-26-000002",
        form_type="10-Q",
        filing_date=date(2026, 8, 1),
        report_period=date(2026, 6, 30),
        primary_document="active2.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/1/2/active2.htm",
        ingestion_status="processed",
        raw_metadata={},
    )
    failed_filing = Filing(
        company_id=active.id,
        accession_number="0000000001-26-000003",
        form_type="10-Q",
        filing_date=date(2026, 8, 2),
        report_period=date(2026, 6, 30),
        primary_document="failed.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/1/3/failed.htm",
        ingestion_status="failed",
        raw_metadata={},
    )
    inactive_filing = Filing(
        company_id=inactive.id,
        accession_number="0000000002-26-000001",
        form_type="10-Q",
        filing_date=date(2026, 5, 1),
        report_period=date(2026, 3, 31),
        primary_document="inactive.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/2/1/inactive.htm",
        ingestion_status="processed",
        raw_metadata={},
    )
    session.add_all([filing, other_filing, failed_filing, inactive_filing])
    await session.flush()

    mda = FilingSection(
        filing_id=filing.id,
        section_type="mda",
        canonical_section_type="mda",
        part_number="I",
        item_number="2",
        section_title="Part I, Item 2. Management Discussion",
        section_order=0,
        raw_text="Management discussion",
        normalized_text="Management discussion",
        text_hash="mda",
        token_count=2,
        metadata_={},
    )
    risk = FilingSection(
        filing_id=filing.id,
        section_type="risk_factors",
        canonical_section_type="risk_factors",
        part_number="II",
        item_number="1A",
        section_title="Part II, Item 1A. Risk Factors",
        section_order=1,
        raw_text="Risk factors",
        normalized_text="Risk factors",
        text_hash="risk",
        token_count=2,
        metadata_={},
    )
    other_section = FilingSection(
        filing_id=other_filing.id,
        section_type="mda",
        canonical_section_type="mda",
        part_number="I",
        item_number="2",
        section_title="Part I, Item 2. Other MDA",
        section_order=0,
        raw_text="Other MDA",
        normalized_text="Other MDA",
        text_hash="other",
        token_count=2,
        metadata_={},
    )
    failed_section = FilingSection(
        filing_id=failed_filing.id,
        section_type="mda",
        section_title="Failed",
        section_order=0,
        raw_text="Failed",
        normalized_text="Failed",
        text_hash="failed",
        token_count=1,
        metadata_={},
    )
    inactive_section = FilingSection(
        filing_id=inactive_filing.id,
        section_type="mda",
        section_title="Inactive",
        section_order=0,
        raw_text="Inactive",
        normalized_text="Inactive",
        text_hash="inactive",
        token_count=1,
        metadata_={},
    )
    session.add_all([mda, risk, other_section, failed_section, inactive_section])
    await session.flush()

    chunks = [
        FilingChunk(
            filing_section_id=risk.id,
            chunk_index=0,
            text="customer concentration increased during the quarter",
            embedding=unit_vector(0),
            token_count=6,
            start_offset=0,
            end_offset=53,
            source_reference="#risk",
            content_hash="risk-customer",
            parser_version="parser-test",
            chunker_version="chunker-test",
            embedding_model="fake",
            embedding_version="fake-v1",
            metadata_={"fixture_key": "customer"},
        ),
        FilingChunk(
            filing_section_id=mda.id,
            chunk_index=1,
            text="liquidity remained sufficient",
            embedding=unit_vector(1),
            token_count=3,
            start_offset=0,
            end_offset=29,
            source_reference="#mda",
            content_hash="mda-liquidity",
            parser_version="parser-test",
            chunker_version="chunker-test",
            embedding_model="fake",
            embedding_version="fake-v1",
            metadata_={"fixture_key": "liquidity"},
        ),
        FilingChunk(
            filing_section_id=mda.id,
            chunk_index=2,
            text="long-term debt decreased",
            embedding=unit_vector(2),
            token_count=3,
            start_offset=30,
            end_offset=54,
            source_reference="#mda-debt",
            content_hash="mda-debt",
            parser_version="parser-test",
            chunker_version="chunker-test",
            embedding_model="fake",
            embedding_version="fake-v1",
            metadata_={"fixture_key": "debt"},
        ),
        FilingChunk(
            filing_section_id=other_section.id,
            chunk_index=0,
            text="revenue guidance was withdrawn",
            embedding=unit_vector(3),
            token_count=4,
            start_offset=0,
            end_offset=30,
            source_reference="#other",
            content_hash="other-revenue",
            parser_version="parser-test",
            chunker_version="chunker-test",
            embedding_model="fake",
            embedding_version="fake-v1",
            metadata_={"fixture_key": "revenue"},
        ),
        FilingChunk(
            filing_section_id=failed_section.id,
            chunk_index=0,
            text="failed filing customer concentration",
            embedding=unit_vector(0),
            token_count=4,
            start_offset=0,
            end_offset=37,
            source_reference="#failed",
            content_hash="failed-customer",
            metadata_={},
        ),
        FilingChunk(
            filing_section_id=inactive_section.id,
            chunk_index=0,
            text="inactive company customer concentration",
            embedding=unit_vector(0),
            token_count=4,
            start_offset=0,
            end_offset=39,
            source_reference="#inactive",
            content_hash="inactive-customer",
            metadata_={},
        ),
    ]
    session.add_all(chunks)
    await session.commit()
    return {
        "company_id": active.id,
        "filing_id": filing.id,
        "other_filing_id": other_filing.id,
        "risk_section_id": risk.id,
        "mda_section_id": mda.id,
        "customer_chunk_id": chunks[0].id,
        "liquidity_chunk_id": chunks[1].id,
        "debt_chunk_id": chunks[2].id,
        "revenue_chunk_id": chunks[3].id,
    }


def stable_uuid(value: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, value)

