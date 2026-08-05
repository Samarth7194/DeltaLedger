from __future__ import annotations

from pathlib import Path

from app.services.chunking_service import ChunkingService
from app.services.document_parser_service import DocumentParserService

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_chunker_respects_sections_and_creates_table_chunks() -> None:
    parsed = DocumentParserService(
        parser_version="parser-test",
        table_extraction_version="table-test",
    ).parse((FIXTURE_DIR / "technology_10q.html").read_text())
    chunker = ChunkingService(max_tokens=25, overlap_tokens=5, chunker_version="chunker-test")

    chunks = chunker.chunk_sections(sections=parsed.sections, tables=parsed.tables)

    assert chunks
    assert any(chunk.metadata["chunk_kind"] == "table" for chunk in chunks)
    assert all(chunk.content_hash for chunk in chunks)
    assert all(
        chunk.token_count <= 25 or chunk.metadata["chunk_kind"] == "table"
        for chunk in chunks
    )


def test_chunker_adds_overlap_when_section_exceeds_limit() -> None:
    parsed = DocumentParserService(
        parser_version="parser-test",
        table_extraction_version="table-test",
    ).parse((FIXTURE_DIR / "technology_10q.html").read_text())
    chunker = ChunkingService(max_tokens=12, overlap_tokens=3, chunker_version="chunker-test")

    chunks = [
        chunk
        for chunk in chunker.chunk_sections(sections=parsed.sections, tables=[])
        if chunk.filing_section_order == 1
    ]

    assert len(chunks) >= 2
    assert chunks[0].content_hash != chunks[1].content_hash
    assert chunks[1].metadata["local_chunk_index"] == 1
