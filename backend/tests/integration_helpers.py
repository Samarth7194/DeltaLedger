from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Company,
    Filing,
    FilingChunk,
    FilingComparison,
    FilingSection,
    PassageUnit,
    SectionMatch,
    XbrlFact,
)


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


async def create_comparison_corpus(session: AsyncSession) -> dict[str, object]:
    await reset_corpus(session)
    company = Company(cik="0000000100", ticker="CMP", legal_name="Comparison Test Inc.")
    session.add(company)
    await session.flush()

    previous_filing = Filing(
        company_id=company.id,
        accession_number="0000000100-26-000001",
        form_type="10-Q",
        filing_date=date(2026, 5, 1),
        report_period=date(2026, 3, 31),
        primary_document="previous.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/100/1/previous.htm",
        ingestion_status="processed",
        raw_metadata={},
    )
    current_filing = Filing(
        company_id=company.id,
        accession_number="0000000100-26-000002",
        form_type="10-Q",
        filing_date=date(2026, 8, 1),
        report_period=date(2026, 6, 30),
        primary_document="current.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/100/2/current.htm",
        ingestion_status="processed",
        raw_metadata={},
    )
    session.add_all([previous_filing, current_filing])
    await session.flush()

    previous_text = (
        "We will maintain sufficient liquidity through the next quarter.\n\n"
        "Revenue may improve if enterprise demand recovers.\n\n"
        "A lawsuit could have an adverse effect."
    )
    current_text = (
        "We may maintain sufficient liquidity through the next quarter.\n\n"
        "Revenue will improve as enterprise demand recovers.\n\n"
        "A lawsuit could have an adverse effect.\n\n"
        "We identified new supplier concentration risk during the quarter."
    )
    previous_section = FilingSection(
        filing_id=previous_filing.id,
        section_type="mda",
        canonical_section_type="mda",
        part_number="I",
        item_number="2",
        section_title="Item 2. Management Discussion and Analysis",
        section_order=0,
        raw_text=previous_text,
        normalized_text=previous_text.lower(),
        text_hash="previous-mda",
        token_count=len(previous_text.split()),
        source_anchor="#previous-mda",
        metadata_={},
    )
    current_section = FilingSection(
        filing_id=current_filing.id,
        section_type="mda",
        canonical_section_type="mda",
        part_number="I",
        item_number="2",
        section_title="Item 2. Management Discussion and Analysis",
        section_order=0,
        raw_text=current_text,
        normalized_text=current_text.lower(),
        text_hash="current-mda",
        token_count=len(current_text.split()),
        source_anchor="#current-mda",
        metadata_={},
    )
    session.add_all([previous_section, current_section])
    await session.flush()

    chunks = [
        FilingChunk(
            filing_section_id=previous_section.id,
            chunk_index=0,
            text=previous_text,
            embedding=unit_vector(5),
            token_count=len(previous_text.split()),
            start_offset=0,
            end_offset=len(previous_text),
            source_reference="#previous-mda",
            content_hash="previous-mda-chunk",
            embedding_model="fake",
            embedding_version="fake-v1",
            metadata_={},
        ),
        FilingChunk(
            filing_section_id=current_section.id,
            chunk_index=0,
            text=current_text,
            embedding=unit_vector(5),
            token_count=len(current_text.split()),
            start_offset=0,
            end_offset=len(current_text),
            source_reference="#current-mda",
            content_hash="current-mda-chunk",
            embedding_model="fake",
            embedding_version="fake-v1",
            metadata_={},
        ),
    ]
    session.add_all(chunks)
    await session.commit()
    return {
        "company_id": company.id,
        "current_filing_id": current_filing.id,
        "comparison_filing_id": previous_filing.id,
        "current_section_id": current_section.id,
        "previous_section_id": previous_section.id,
    }


async def create_financial_verification_corpus(session: AsyncSession) -> dict[str, object]:
    await reset_corpus(session)
    company = Company(cik="0000000200", ticker="FIN", legal_name="Financial Test Inc.")
    session.add(company)
    await session.flush()

    previous_filing = Filing(
        company_id=company.id,
        accession_number="0000000200-25-000001",
        form_type="10-Q",
        filing_date=date(2025, 8, 1),
        report_period=date(2025, 6, 30),
        primary_document="previous.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/200/1/previous.htm",
        ingestion_status="processed",
        raw_metadata={},
    )
    current_filing = Filing(
        company_id=company.id,
        accession_number="0000000200-26-000002",
        form_type="10-Q",
        filing_date=date(2026, 8, 1),
        report_period=date(2026, 6, 30),
        primary_document="current.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/200/2/current.htm",
        ingestion_status="processed",
        raw_metadata={},
    )
    session.add_all([previous_filing, current_filing])
    await session.flush()

    previous_text = "Revenue was $100 million for the quarter."
    current_text = (
        "Revenue increased 12% compared with the same period last year. "
        "Revenue was $112 million for the quarter. "
        "Gross profit was $44.8 million for the quarter."
    )
    previous_section = FilingSection(
        filing_id=previous_filing.id,
        section_type="mda",
        canonical_section_type="mda",
        part_number="I",
        item_number="2",
        section_title="Item 2. Management Discussion and Analysis",
        section_order=0,
        raw_text=previous_text,
        normalized_text=previous_text.lower(),
        text_hash="financial-previous-mda",
        token_count=len(previous_text.split()),
        source_anchor="#previous-mda",
        metadata_={},
    )
    current_section = FilingSection(
        filing_id=current_filing.id,
        section_type="mda",
        canonical_section_type="mda",
        part_number="I",
        item_number="2",
        section_title="Item 2. Management Discussion and Analysis",
        section_order=0,
        raw_text=current_text,
        normalized_text=current_text.lower(),
        text_hash="financial-current-mda",
        token_count=len(current_text.split()),
        source_anchor="#current-mda",
        metadata_={},
    )
    session.add_all([previous_section, current_section])
    await session.flush()

    current_passage = PassageUnit(
        filing_section_id=current_section.id,
        unit_type="paragraph",
        unit_index=0,
        text=current_text,
        normalized_text=current_text.lower(),
        raw_char_start=0,
        raw_char_end=len(current_text),
        normalized_char_start=0,
        normalized_char_end=len(current_text),
        source_anchor="#current-p0",
        content_hash="financial-current-p0",
        segmentation_version="test-v1",
        metadata_={},
    )
    previous_passage = PassageUnit(
        filing_section_id=previous_section.id,
        unit_type="paragraph",
        unit_index=0,
        text=previous_text,
        normalized_text=previous_text.lower(),
        raw_char_start=0,
        raw_char_end=len(previous_text),
        normalized_char_start=0,
        normalized_char_end=len(previous_text),
        source_anchor="#previous-p0",
        content_hash="financial-previous-p0",
        segmentation_version="test-v1",
        metadata_={},
    )
    session.add_all([current_passage, previous_passage])
    await session.flush()

    comparison = FilingComparison(
        company_id=company.id,
        current_filing_id=current_filing.id,
        comparison_filing_id=previous_filing.id,
        status="completed",
        comparison_version="phase3-v1",
        processing_metrics={},
    )
    session.add(comparison)
    await session.flush()
    section_match = SectionMatch(
        comparison_id=comparison.id,
        current_section_id=current_section.id,
        previous_section_id=previous_section.id,
        match_type="exact_structural",
        combined_score=1.0,
        confidence=1.0,
        match_reason={"fixture": True},
    )
    session.add(section_match)

    current_revenue = XbrlFact(
        company_id=company.id,
        filing_id=current_filing.id,
        taxonomy="us-gaap",
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
        label="Revenue",
        unit="USD",
        value_numeric=Decimal("112000000"),
        start_date=date(2026, 4, 1),
        end_date=date(2026, 6, 30),
        fiscal_year=2026,
        fiscal_period="Q2",
        form_type="10-Q",
        accession_number=current_filing.accession_number,
        frame="CY2026Q2",
        raw_fact={"fixture": "current_revenue"},
    )
    previous_revenue = XbrlFact(
        company_id=company.id,
        filing_id=previous_filing.id,
        taxonomy="us-gaap",
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
        label="Revenue",
        unit="USD",
        value_numeric=Decimal("100000000"),
        start_date=date(2025, 4, 1),
        end_date=date(2025, 6, 30),
        fiscal_year=2025,
        fiscal_period="Q2",
        form_type="10-Q",
        accession_number=previous_filing.accession_number,
        frame="CY2025Q2",
        raw_fact={"fixture": "previous_revenue"},
    )
    lower_priority_current_revenue = XbrlFact(
        company_id=company.id,
        filing_id=current_filing.id,
        taxonomy="us-gaap",
        concept="Revenues",
        label="Revenue fallback",
        unit="USD",
        value_numeric=Decimal("111000000"),
        start_date=date(2026, 4, 1),
        end_date=date(2026, 6, 30),
        fiscal_year=2026,
        fiscal_period="Q2",
        form_type="10-Q",
        accession_number="0000000200-26-999999",
        frame="CY2026Q2",
        raw_fact={"fixture": "fallback_revenue"},
    )
    current_gross_profit = XbrlFact(
        company_id=company.id,
        filing_id=current_filing.id,
        taxonomy="us-gaap",
        concept="GrossProfit",
        label="Gross profit",
        unit="USD",
        value_numeric=Decimal("44800000"),
        start_date=date(2026, 4, 1),
        end_date=date(2026, 6, 30),
        fiscal_year=2026,
        fiscal_period="Q2",
        form_type="10-Q",
        accession_number=current_filing.accession_number,
        frame="CY2026Q2",
        raw_fact={"fixture": "gross_profit"},
    )
    session.add_all(
        [
            current_revenue,
            previous_revenue,
            lower_priority_current_revenue,
            current_gross_profit,
        ]
    )
    await session.commit()
    return {
        "company_id": company.id,
        "current_filing_id": current_filing.id,
        "previous_filing_id": previous_filing.id,
        "comparison_id": comparison.id,
        "current_section_id": current_section.id,
        "current_passage_id": current_passage.id,
        "previous_passage_id": previous_passage.id,
        "current_revenue_fact_id": current_revenue.id,
        "previous_revenue_fact_id": previous_revenue.id,
        "current_gross_profit_fact_id": current_gross_profit.id,
    }


def stable_uuid(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, value)
