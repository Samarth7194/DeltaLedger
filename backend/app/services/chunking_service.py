from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.document_parser_service import ParsedSection, ParsedTable


@dataclass(frozen=True)
class ChunkSpec:
    filing_section_order: int
    chunk_index: int
    text: str
    token_count: int
    start_offset: int
    end_offset: int
    source_reference: str
    content_hash: str
    source_text_hash: str
    parser_version: str
    chunker_version: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ChunkingService:
    def __init__(self, *, max_tokens: int, overlap_tokens: int, chunker_version: str) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive.")
        if overlap_tokens < 0 or overlap_tokens >= max_tokens:
            raise ValueError("overlap_tokens must be non-negative and less than max_tokens.")
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.chunker_version = chunker_version

    def chunk_sections(
        self,
        *,
        sections: list[ParsedSection],
        tables: list[ParsedTable],
    ) -> list[ChunkSpec]:
        chunks: list[ChunkSpec] = []
        tables_by_section: dict[int, list[ParsedTable]] = {}
        for table in tables:
            if table.section_order is not None:
                tables_by_section.setdefault(table.section_order, []).append(table)

        for section in sections:
            section_chunks = self._chunk_section_text(section)
            for local_index, chunk in enumerate(section_chunks):
                chunks.append(chunk.with_index(len(chunks), local_index))
            for table in tables_by_section.get(section.section_order, []):
                text = self._table_to_text(table)
                if not text.strip():
                    continue
                chunks.append(
                    ChunkSpec(
                        filing_section_order=section.section_order,
                        chunk_index=len(chunks),
                        text=text,
                        token_count=_count_tokens(text),
                        start_offset=section.normalized_start_offset,
                        end_offset=section.normalized_end_offset,
                        source_reference=table.source_anchor
                        or section.source_anchor
                        or section.dom_path,
                        content_hash=_sha256(text),
                        source_text_hash=table.content_hash,
                        parser_version=section.parser_version,
                        chunker_version=self.chunker_version,
                        metadata={
                            "chunk_kind": "table",
                            "table_index": table.table_index,
                            "section_title": section.section_title,
                            "part_number": section.part_number,
                            "item_number": section.item_number,
                            "canonical_section_type": section.canonical_section_type,
                        },
                    )
                )
        return chunks

    def _chunk_section_text(self, section: ParsedSection) -> list[_MutableChunk]:
        paragraphs = _split_paragraphs(section.normalized_text)
        chunks: list[_MutableChunk] = []
        current_parts: list[str] = []
        current_start = section.normalized_start_offset
        current_token_count = 0
        cursor = section.normalized_start_offset

        for paragraph in paragraphs:
            paragraph_tokens = _count_tokens(paragraph)
            if paragraph_tokens == 0:
                cursor += len(paragraph) + 2
                continue
            if paragraph_tokens > self.max_tokens:
                for sentence_chunk in self._split_large_paragraph(paragraph):
                    current_parts, current_token_count, current_start = self._append_or_flush(
                        chunks,
                        section,
                        current_parts,
                        current_token_count,
                        current_start,
                        cursor,
                        sentence_chunk,
                    )
                    cursor += len(sentence_chunk) + 1
                continue
            current_parts, current_token_count, current_start = self._append_or_flush(
                chunks,
                section,
                current_parts,
                current_token_count,
                current_start,
                cursor,
                paragraph,
            )
            cursor += len(paragraph) + 2

        if current_parts:
            chunks.append(self._make_text_chunk(section, current_parts, current_start, cursor))
        return chunks

    def _append_or_flush(
        self,
        chunks: list[_MutableChunk],
        section: ParsedSection,
        current_parts: list[str],
        current_token_count: int,
        current_start: int,
        cursor: int,
        text: str,
    ) -> tuple[list[str], int, int]:
        text_tokens = _count_tokens(text)
        if current_parts and current_token_count + text_tokens > self.max_tokens:
            chunks.append(self._make_text_chunk(section, current_parts, current_start, cursor))
            overlap = _last_words(" ".join(current_parts), self.overlap_tokens)
            current_parts = [overlap] if overlap else []
            current_token_count = _count_tokens(overlap)
            current_start = max(section.normalized_start_offset, cursor - len(overlap))
        if not current_parts:
            current_start = cursor
        current_parts.append(text)
        current_token_count += text_tokens
        return current_parts, current_token_count, current_start

    def _make_text_chunk(
        self,
        section: ParsedSection,
        parts: list[str],
        start_offset: int,
        end_offset: int,
    ) -> _MutableChunk:
        text = "\n\n".join(part for part in parts if part.strip()).strip()
        return _MutableChunk(
            filing_section_order=section.section_order,
            text=text,
            token_count=_count_tokens(text),
            start_offset=start_offset,
            end_offset=end_offset,
            source_reference=section.source_anchor or section.dom_path,
            content_hash=_sha256(text),
            source_text_hash=section.source_text_hash,
            parser_version=section.parser_version,
            chunker_version=self.chunker_version,
            metadata={
                "chunk_kind": "text",
                "section_title": section.section_title,
                "part_number": section.part_number,
                "item_number": section.item_number,
                "canonical_section_type": section.canonical_section_type,
            },
        )

    def _split_large_paragraph(self, paragraph: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        chunks: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for sentence in sentences:
            tokens = _count_tokens(sentence)
            if current and current_tokens + tokens > self.max_tokens:
                chunks.append(" ".join(current).strip())
                current = []
                current_tokens = 0
            if tokens > self.max_tokens:
                words = sentence.split()
                for index in range(0, len(words), self.max_tokens):
                    chunks.append(" ".join(words[index : index + self.max_tokens]))
                continue
            current.append(sentence)
            current_tokens += tokens
        if current:
            chunks.append(" ".join(current).strip())
        return chunks

    def _table_to_text(self, table: ParsedTable) -> str:
        headers = [str(header) for header in table.normalized_json.get("headers", [])]
        rows = table.normalized_json.get("rows", [])
        lines: list[str] = []
        if table.caption:
            lines.append(table.caption)
        if headers:
            lines.append(" | ".join(headers))
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, list):
                lines.append(" | ".join(str(cell) for cell in row))
        return "\n".join(lines)


@dataclass(frozen=True)
class _MutableChunk:
    filing_section_order: int
    text: str
    token_count: int
    start_offset: int
    end_offset: int
    source_reference: str
    content_hash: str
    source_text_hash: str
    parser_version: str
    chunker_version: str
    metadata: dict[str, Any]

    def with_index(self, global_index: int, local_index: int) -> ChunkSpec:
        metadata = {**self.metadata, "local_chunk_index": local_index}
        return ChunkSpec(
            filing_section_order=self.filing_section_order,
            chunk_index=global_index,
            text=self.text,
            token_count=self.token_count,
            start_offset=self.start_offset,
            end_offset=self.end_offset,
            source_reference=self.source_reference,
            content_hash=self.content_hash,
            source_text_hash=self.source_text_hash,
            parser_version=self.parser_version,
            chunker_version=self.chunker_version,
            metadata=metadata,
        )


def _split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]


def _count_tokens(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _last_words(text: str, count: int) -> str:
    if count <= 0:
        return ""
    words = text.split()
    return " ".join(words[-count:])


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
