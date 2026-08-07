from __future__ import annotations

import re

from app.core.config import Settings
from app.db.models import FilingSection, PassageUnit
from app.services.comparison_utils import content_hash, normalize_for_comparison

BOUNDARY_RE = re.compile(r"(?:\n\s*\n|(?:^|\n)\s*[-*]\s+)")


class PassageSegmentationService:
    def __init__(self, settings: Settings) -> None:
        self.version = settings.passage_segmentation_version

    def segment_section(self, section: FilingSection) -> list[PassageUnit]:
        text = section.raw_text or section.normalized_text
        parts = self._paragraphs(text)
        units: list[PassageUnit] = []
        cursor = 0
        for part in parts:
            start = text.find(part, cursor)
            if start < 0:
                start = cursor
            end = start + len(part)
            cursor = end
            normalized = normalize_for_comparison(part)
            if not normalized:
                continue
            units.append(
                PassageUnit(
                    filing_section_id=section.id,
                    unit_type="paragraph",
                    unit_index=len(units),
                    text=part,
                    normalized_text=normalized,
                    raw_char_start=start,
                    raw_char_end=end,
                    normalized_char_start=0,
                    normalized_char_end=len(normalized),
                    source_anchor=section.source_anchor,
                    source_element_id=section.native_element_id,
                    content_hash=content_hash(f"{self.version}:{normalized}"),
                    segmentation_version=self.version,
                    metadata_={
                        "section_order": section.section_order,
                        "part_number": section.part_number,
                        "item_number": section.item_number,
                    },
                )
            )
        return units

    def _paragraphs(self, text: str) -> list[str]:
        normalized = text.replace("\r\n", "\n")
        if "\n\n" in normalized or re.search(r"(?:^|\n)\s*[-*]\s+", normalized):
            parts = [part.strip(" \n-*") for part in BOUNDARY_RE.split(normalized)]
        else:
            parts = [normalized.strip()]
        return [part for part in parts if part and normalize_for_comparison(part)]
