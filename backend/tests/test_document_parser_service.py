from __future__ import annotations

from pathlib import Path

import pytest

from app.services.chunking_service import ChunkingService
from app.services.document_parser_service import DocumentParserService

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _parser() -> DocumentParserService:
    return DocumentParserService(
        parser_version="parser-test",
        table_extraction_version="table-test",
    )


def test_parser_detects_parts_items_and_ignores_table_of_contents() -> None:
    html = (FIXTURE_DIR / "technology_10q.html").read_text()

    parsed = _parser().parse(html)

    section_types = [section.canonical_section_type for section in parsed.sections]
    assert section_types == [
        "financial_statements",
        "mda",
        "quantitative_disclosures",
        "controls",
        "legal_proceedings",
        "risk_factors",
    ]
    assert parsed.sections[0].source_anchor == "#item1"
    assert "Table of Contents" not in parsed.sections[0].normalized_text


def test_parser_preserves_inline_xbrl_text_and_not_applicable_sections() -> None:
    html = (FIXTURE_DIR / "technology_10q.html").read_text()

    parsed = _parser().parse(html)
    mda = next(section for section in parsed.sections if section.canonical_section_type == "mda")
    market_risk = next(
        section
        for section in parsed.sections
        if section.canonical_section_type == "quantitative_disclosures"
    )

    assert "sales improved" in mda.normalized_text
    assert "Not applicable." in market_risk.normalized_text


def test_parser_extracts_complex_tables_with_colspan_and_rowspan() -> None:
    html = (FIXTURE_DIR / "complex_tables_10q.html").read_text()

    parsed = _parser().parse(html)

    assert len(parsed.tables) == 1
    table = parsed.tables[0]
    assert table.section_order == 0
    assert table.normalized_json["headers"] == ["Metric", "March 31 2026", "December 31 2025"]
    assert ["Cash", "$2,000", "$1,500"] in table.normalized_json["rows"]
    assert table.content_hash


def test_parser_handles_missing_sections_and_repeated_headings() -> None:
    html = (FIXTURE_DIR / "financial_issuer_10q.html").read_text()

    parsed = _parser().parse(html)

    section_types = [section.canonical_section_type for section in parsed.sections]
    assert "quantitative_disclosures" not in section_types
    assert section_types.count("risk_factors") == 2
    assert all(section.section_text_hash for section in parsed.sections)


@pytest.mark.parametrize(
    "fixture_name,expected_types",
    [
        (
            "realistic_technology_10q_reduced.html",
            {"financial_statements", "mda", "quantitative_disclosures", "controls", "risk_factors"},
        ),
        ("realistic_table_heavy_10q_reduced.html", {"financial_statements", "mda", "risk_factors"}),
        (
            "realistic_financial_10q_reduced.html",
            {"financial_statements", "mda", "quantitative_disclosures", "controls", "risk_factors"},
        ),
    ],
)
def test_realistic_reduced_fixtures_parse_deterministically(
    fixture_name: str,
    expected_types: set[str],
) -> None:
    html = (FIXTURE_DIR / fixture_name).read_text()

    first = _parser().parse(html)
    second = _parser().parse(html)

    assert {section.canonical_section_type for section in first.sections} >= expected_types
    assert [section.section_text_hash for section in first.sections] == [
        section.section_text_hash for section in second.sections
    ]
    assert all(section.dom_path for section in first.sections)
    assert all(table.content_hash for table in first.tables)


def test_full_real_apple_10q_parses_with_stable_sections_tables_and_chunks() -> None:
    html = (FIXTURE_DIR / "aapl_2024q2_10q_full.htm").read_text(encoding="utf-8")

    first = _parser().parse(html)
    second = _parser().parse(html)
    chunks = ChunkingService(
        max_tokens=450,
        overlap_tokens=60,
        chunker_version="chunker-test",
    ).chunk_sections(sections=first.sections, tables=first.tables)

    assert [section.canonical_section_type for section in first.sections] == [
        "financial_statements",
        "mda",
        "quantitative_disclosures",
        "controls",
        "legal_proceedings",
        "risk_factors",
        "other",
        "other",
        "other",
    ]
    assert [section.part_number for section in first.sections[:4]] == ["I", "I", "I", "I"]
    assert [section.part_number for section in first.sections[4:]] == ["II", "II", "II", "II", "II"]
    assert [section.item_number for section in first.sections] == [
        "1",
        "2",
        "3",
        "4",
        "1",
        "1A",
        "2",
        "3",
        "4",
    ]

    mda = next(section for section in first.sections if section.canonical_section_type == "mda")
    risk = next(
        section for section in first.sections if section.canonical_section_type == "risk_factors"
    )
    financials = first.sections[0]

    assert "Discussion and Analysis" in mda.normalized_text
    assert "Risk Factors" in risk.normalized_text
    assert "CONDENSED CONSOLIDATED STATEMENTS" in financials.normalized_text
    assert "Item 1A. of the 2023 form 10-k" not in {
        section.section_title for section in first.sections
    }
    assert len(first.tables) >= 20
    assert any(table.section_order == financials.section_order for table in first.tables)
    assert all(section.dom_path for section in first.sections)
    assert [section.section_text_hash for section in first.sections] == [
        section.section_text_hash for section in second.sections
    ]
    assert any(chunk.metadata["chunk_kind"] == "table" for chunk in chunks)
    assert any(chunk.metadata["canonical_section_type"] == "mda" for chunk in chunks)
