from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

CANONICAL_SECTION_TYPES = {
    ("I", "1"): "financial_statements",
    ("I", "2"): "mda",
    ("I", "3"): "quantitative_disclosures",
    ("I", "4"): "controls",
    ("II", "1"): "legal_proceedings",
    ("II", "1A"): "risk_factors",
}

BLOCK_TAGS = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "li"}
REMOVE_TAGS = {"script", "style", "noscript", "head", "meta", "link"}
PART_RE = re.compile(r"\bpart\s+(i{1,2})\b", re.IGNORECASE)
ITEM_RE = re.compile(r"^\s*item\s+([1-4]|1a)\b\s*[.\-:]*\s*(.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedTable:
    table_index: int
    section_order: int | None
    caption: str | None
    raw_html: str
    normalized_json: dict[str, Any]
    content_hash: str
    source_anchor: str | None
    native_element_id: str | None
    dom_path: str
    extraction_version: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedSection:
    part_number: str | None
    item_number: str | None
    canonical_section_type: str
    section_title: str
    section_order: int
    raw_text: str
    normalized_text: str
    raw_start_offset: int | None
    raw_end_offset: int | None
    normalized_start_offset: int
    normalized_end_offset: int
    source_anchor: str | None
    native_element_id: str | None
    dom_path: str
    source_text_hash: str
    section_text_hash: str
    token_count: int
    parser_version: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    sections: list[ParsedSection]
    tables: list[ParsedTable]
    parser_version: str
    document_hash: str


@dataclass
class _Block:
    kind: str
    text: str
    tag: Tag
    raw_html: str
    raw_start_offset: int | None
    raw_end_offset: int | None


class DocumentParserService:
    def __init__(self, *, parser_version: str, table_extraction_version: str) -> None:
        self.parser_version = parser_version
        self.table_extraction_version = table_extraction_version

    def parse(self, html: bytes | str) -> ParsedDocument:
        html_text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
        soup = BeautifulSoup(html_text, "html.parser")
        self._remove_boilerplate(soup)
        body = soup.body or soup
        blocks = self._collect_blocks(body, html_text)
        sections, table_assignments = self._build_sections(blocks)
        tables = self._extract_tables(blocks, table_assignments)
        return ParsedDocument(
            sections=sections,
            tables=tables,
            parser_version=self.parser_version,
            document_hash=_sha256(_normalize_text(body.get_text(" ", strip=True))),
        )

    def _remove_boilerplate(self, soup: BeautifulSoup) -> None:
        for tag in soup.find_all(REMOVE_TAGS):
            tag.decompose()
        for tag in soup.find_all(True):
            if tag.name and tag.name.lower().startswith("ix:") and tag.name.lower() == "ix:hidden":
                tag.decompose()
            text = _normalize_text(tag.get_text(" ", strip=True))
            if tag.name not in {"html", "body"} and text.lower().startswith(
                "edgar submission header"
            ):
                tag.decompose()

    def _collect_blocks(self, root: Tag, html_text: str) -> list[_Block]:
        blocks: list[_Block] = []

        def visit(tag: Tag) -> None:
            if tag.name == "table":
                blocks.append(self._make_block("table", tag, html_text))
                return
            child_block_tags = [
                child
                for child in tag.children
                if isinstance(child, Tag) and child.name in BLOCK_TAGS | {"table"}
            ]
            if tag.name in BLOCK_TAGS:
                text = _normalize_text(tag.get_text(" ", strip=True))
                if text and (not child_block_tags or self._looks_like_heading(text)):
                    blocks.append(self._make_block("text", tag, html_text))
                    return
            for child in tag.children:
                if isinstance(child, Tag):
                    visit(child)

        visit(root)
        return self._dedupe_adjacent_blocks(blocks)

    def _make_block(self, kind: str, tag: Tag, html_text: str) -> _Block:
        raw_html = str(tag)
        raw_start = html_text.find(raw_html)
        raw_start_offset = raw_start if raw_start >= 0 else None
        raw_end_offset = raw_start + len(raw_html) if raw_start >= 0 else None
        text = _normalize_text(tag.get_text(" ", strip=True))
        return _Block(
            kind=kind,
            text=text,
            tag=tag,
            raw_html=raw_html,
            raw_start_offset=raw_start_offset,
            raw_end_offset=raw_end_offset,
        )

    def _dedupe_adjacent_blocks(self, blocks: list[_Block]) -> list[_Block]:
        deduped: list[_Block] = []
        for block in blocks:
            if not block.text and block.kind != "table":
                continue
            if deduped and deduped[-1].kind == block.kind and deduped[-1].text == block.text:
                continue
            deduped.append(block)
        return deduped

    def _build_sections(
        self, blocks: list[_Block]
    ) -> tuple[list[ParsedSection], dict[int, int | None]]:
        current_part: str | None = None
        active: dict[str, Any] | None = None
        sections: list[ParsedSection] = []
        normalized_cursor = 0
        table_assignments: dict[int, int | None] = {}
        seen_real_part = False

        for index, block in enumerate(blocks):
            if block.kind == "table":
                table_assignments[index] = active["section_order"] if active else None
                continue
            if self._is_toc_like(block):
                continue

            part = self._detect_part(block.text)
            item = self._detect_item(block.text)
            lower_text = block.text.lower()
            if part and (
                "financial information" in lower_text or "other information" in lower_text
            ):
                current_part = part
                seen_real_part = True
                continue
            if item and current_part and seen_real_part:
                if active is not None:
                    sections.append(self._finalize_section(active, normalized_cursor))
                    normalized_cursor += len(sections[-1].normalized_text) + 2
                item_number, heading_tail = item
                canonical = CANONICAL_SECTION_TYPES.get((current_part, item_number), "other")
                title = self._section_title(current_part, item_number, heading_tail, canonical)
                active = {
                    "part_number": current_part,
                    "item_number": item_number,
                    "canonical_section_type": canonical,
                    "section_title": title,
                    "section_order": len(sections),
                    "blocks": [block],
                    "first_block": block,
                }
                continue

            if active is not None:
                active["blocks"].append(block)

        if active is not None:
            sections.append(self._finalize_section(active, normalized_cursor))
        return sections, table_assignments

    def _finalize_section(self, active: dict[str, Any], normalized_start: int) -> ParsedSection:
        blocks: list[_Block] = active["blocks"]
        raw_text = "\n\n".join(block.text for block in blocks if block.text)
        normalized_text = _normalize_body_text(raw_text)
        first = blocks[0]
        last = blocks[-1]
        source_text_hash = _sha256(first.raw_html)
        section_text_hash = _sha256(normalized_text)
        return ParsedSection(
            part_number=active["part_number"],
            item_number=active["item_number"],
            canonical_section_type=active["canonical_section_type"],
            section_title=active["section_title"],
            section_order=active["section_order"],
            raw_text=raw_text,
            normalized_text=normalized_text,
            raw_start_offset=first.raw_start_offset,
            raw_end_offset=last.raw_end_offset,
            normalized_start_offset=normalized_start,
            normalized_end_offset=normalized_start + len(normalized_text),
            source_anchor=_source_anchor(first.tag),
            native_element_id=_element_id(first.tag),
            dom_path=_dom_path(first.tag),
            source_text_hash=source_text_hash,
            section_text_hash=section_text_hash,
            token_count=_count_tokens(normalized_text),
            parser_version=self.parser_version,
            metadata={"block_count": len(blocks)},
        )

    def _extract_tables(
        self, blocks: list[_Block], table_assignments: dict[int, int | None]
    ) -> list[ParsedTable]:
        tables: list[ParsedTable] = []
        for block_index, section_order in table_assignments.items():
            block = blocks[block_index]
            if self._is_decorative_table(block.tag):
                continue
            normalized = self._normalize_table(block.tag, section_order)
            if not normalized["rows"]:
                continue
            tables.append(
                ParsedTable(
                    table_index=len(tables),
                    section_order=section_order,
                    caption=normalized.get("caption"),
                    raw_html=block.raw_html,
                    normalized_json=normalized,
                    content_hash=_sha256(block.text + block.raw_html),
                    source_anchor=_source_anchor(block.tag),
                    native_element_id=_element_id(block.tag),
                    dom_path=_dom_path(block.tag),
                    extraction_version=self.table_extraction_version,
                    metadata={"row_count": len(normalized["rows"])},
                )
            )
        return tables

    def _normalize_table(self, table: Tag, section_order: int | None) -> dict[str, Any]:
        caption_tag = table.find("caption")
        rows: list[list[str]] = []
        span_map: dict[tuple[int, int], str] = {}
        for row_index, tr in enumerate(table.find_all("tr")):
            row: list[str] = []
            col_index = 0
            for cell in tr.find_all(["th", "td"], recursive=False):
                while (row_index, col_index) in span_map:
                    row.append(span_map[(row_index, col_index)])
                    col_index += 1
                text = _normalize_text(cell.get_text(" ", strip=True))
                colspan = int(cell.get("colspan", 1) or 1)
                rowspan = int(cell.get("rowspan", 1) or 1)
                for offset in range(colspan):
                    row.append(text)
                    if rowspan > 1:
                        for span_row in range(row_index + 1, row_index + rowspan):
                            span_map[(span_row, col_index + offset)] = text
                col_index += colspan
            while (row_index, col_index) in span_map:
                row.append(span_map[(row_index, col_index)])
                col_index += 1
            if any(row):
                rows.append(row)
        header_rows = [
            index for index, tr in enumerate(table.find_all("tr")) if tr.find("th") is not None
        ]
        header_index = header_rows[-1] if header_rows else 0
        headers = rows[header_index] if rows else []
        data_rows = rows[header_index + 1 :] if rows else []
        return {
            "headers": headers,
            "rows": data_rows,
            "caption": (
                _normalize_text(caption_tag.get_text(" ", strip=True)) if caption_tag else None
            ),
            "source": {
                "element_id": _element_id(table),
                "section_order": section_order,
                "dom_path": _dom_path(table),
            },
        }

    def _is_decorative_table(self, table: Tag) -> bool:
        text = _normalize_text(table.get_text(" ", strip=True))
        if len(text) < 20:
            return True
        cells = table.find_all(["td", "th"])
        if len(cells) < 2:
            return True
        return False

    def _looks_like_heading(self, text: str) -> bool:
        return self._detect_part(text) is not None or self._detect_item(text) is not None

    def _detect_part(self, text: str) -> str | None:
        normalized = _normalize_heading(text)
        match = PART_RE.search(normalized)
        if not match:
            return None
        value = match.group(1).upper()
        return "II" if value == "II" else "I"

    def _detect_item(self, text: str) -> tuple[str, str] | None:
        normalized = _normalize_heading(text)
        match = ITEM_RE.search(normalized)
        if not match:
            return None
        heading_tail = match.group(2).strip()
        if heading_tail.startswith("of "):
            return None
        return match.group(1).upper(), heading_tail

    def _is_toc_like(self, block: _Block) -> bool:
        text = block.text.lower()
        if "table of contents" in text:
            return True
        if re.search(r"\.{3,}\s*\d+$", text):
            return True
        links = block.tag.find_all("a")
        if links and len(block.text) < 120:
            return True
        return False

    def _section_title(self, part: str, item: str, heading_tail: str, canonical: str) -> str:
        tail = heading_tail.strip(" .:-")
        if tail:
            return f"Part {part}, Item {item}. {tail}"
        return f"Part {part}, Item {item}. {canonical.replace('_', ' ').title()}"


def _element_id(tag: Tag) -> str | None:
    value = tag.get("id") or tag.get("name")
    return str(value) if value else None


def _source_anchor(tag: Tag) -> str | None:
    value = _element_id(tag)
    return f"#{value}" if value else None


def _dom_path(tag: Tag) -> str:
    parts: list[str] = []
    current: Tag | None = tag
    while current is not None and isinstance(current, Tag) and current.name != "[document]":
        if current.parent:
            siblings = [sib for sib in current.parent.find_all(current.name, recursive=False)]
            index = siblings.index(current) + 1 if current in siblings else 1
        else:
            index = 1
        parts.append(f"{current.name}:nth-of-type({index})")
        current = current.parent if isinstance(current.parent, Tag) else None
    return " > ".join(reversed(parts))


def _normalize_heading(text: str) -> str:
    text = re.sub(r"[\u00a0\s]+", " ", text)
    text = re.sub(r"[|]", " ", text)
    return text.strip().lower()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _normalize_body_text(text: str) -> str:
    lines = [_normalize_text(line) for line in text.splitlines()]
    return "\n\n".join(line for line in lines if line)


def _count_tokens(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
