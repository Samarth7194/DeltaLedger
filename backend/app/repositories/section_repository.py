from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import FilingSection, FilingTable
from app.services.document_parser_service import ParsedSection, ParsedTable


class SectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_sections(self, filing_id: uuid.UUID) -> list[FilingSection]:
        stmt = (
            select(FilingSection)
            .where(FilingSection.filing_id == filing_id)
            .order_by(FilingSection.section_order)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_section(
        self,
        filing_id: uuid.UUID,
        section_id: uuid.UUID,
    ) -> FilingSection | None:
        stmt = select(FilingSection).where(
            FilingSection.filing_id == filing_id,
            FilingSection.id == section_id,
        )
        return await self.session.scalar(stmt)

    async def list_tables(self, filing_id: uuid.UUID) -> list[FilingTable]:
        stmt = (
            select(FilingTable)
            .where(FilingTable.filing_id == filing_id)
            .order_by(FilingTable.table_index)
        )
        return list((await self.session.scalars(stmt)).all())

    async def replace_sections_and_tables(
        self,
        *,
        filing_id: uuid.UUID,
        sections: list[ParsedSection],
        tables: list[ParsedTable],
    ) -> dict[int, FilingSection]:
        existing_sections = await self.list_sections(filing_id)
        if self._sections_unchanged(existing_sections, sections):
            return {section.section_order: section for section in existing_sections}

        await self.session.execute(delete(FilingTable).where(FilingTable.filing_id == filing_id))
        await self.session.execute(
            delete(FilingSection).where(FilingSection.filing_id == filing_id)
        )
        await self.session.flush()

        by_order: dict[int, FilingSection] = {}
        for parsed in sections:
            section = FilingSection(
                filing_id=filing_id,
                section_type=parsed.canonical_section_type,
                part_number=parsed.part_number,
                item_number=parsed.item_number,
                canonical_section_type=parsed.canonical_section_type,
                section_title=parsed.section_title,
                section_order=parsed.section_order,
                raw_text=parsed.raw_text,
                normalized_text=parsed.normalized_text,
                text_hash=parsed.section_text_hash,
                raw_start_offset=parsed.raw_start_offset,
                raw_end_offset=parsed.raw_end_offset,
                normalized_start_offset=parsed.normalized_start_offset,
                normalized_end_offset=parsed.normalized_end_offset,
                token_count=parsed.token_count,
                source_anchor=parsed.source_anchor,
                native_element_id=parsed.native_element_id,
                dom_path=parsed.dom_path,
                source_text_hash=parsed.source_text_hash,
                parser_version=parsed.parser_version,
                metadata_=parsed.metadata,
            )
            self.session.add(section)
            by_order[parsed.section_order] = section

        await self.session.flush()

        for parsed_table in tables:
            section = (
                by_order.get(parsed_table.section_order)
                if parsed_table.section_order is not None
                else None
            )
            self.session.add(
                FilingTable(
                    filing_id=filing_id,
                    filing_section_id=section.id if section is not None else None,
                    table_index=parsed_table.table_index,
                    caption=parsed_table.caption,
                    raw_html=parsed_table.raw_html,
                    normalized_json=parsed_table.normalized_json,
                    content_hash=parsed_table.content_hash,
                    source_anchor=parsed_table.source_anchor,
                    native_element_id=parsed_table.native_element_id,
                    dom_path=parsed_table.dom_path,
                    extraction_version=parsed_table.extraction_version,
                    metadata_=parsed_table.metadata,
                )
            )
        return by_order

    def _sections_unchanged(
        self,
        existing_sections: list[FilingSection],
        parsed_sections: list[ParsedSection],
    ) -> bool:
        if len(existing_sections) != len(parsed_sections):
            return False
        by_order = {section.section_order: section for section in existing_sections}
        for parsed in parsed_sections:
            existing = by_order.get(parsed.section_order)
            if existing is None:
                return False
            if existing.text_hash != parsed.section_text_hash:
                return False
            if existing.parser_version != parsed.parser_version:
                return False
            if existing.section_type != parsed.canonical_section_type:
                return False
        return True

    async def get_sections_with_chunks(self, filing_id: uuid.UUID) -> list[FilingSection]:
        stmt = (
            select(FilingSection)
            .options(selectinload(FilingSection.chunks))
            .where(FilingSection.filing_id == filing_id)
            .order_by(FilingSection.section_order)
        )
        return list((await self.session.scalars(stmt)).all())
