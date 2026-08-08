from __future__ import annotations

import re
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.financial_claims import ClaimExtractorProvider, FinancialClaimExtraction
from app.core.config import Settings
from app.db.models import FilingSection, FinancialClaim, PassageUnit
from app.repositories.financial_repository import FinancialRepository
from app.services.financial_metric_registry import FinancialMetricRegistry
from app.services.financial_number_parser import parse_all_financial_numbers
from app.services.financial_periods import parse_comparison_basis

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
INCREASE_TERMS = ("increase", "increased", "higher", "grew", "growth", "improved")
DECREASE_TERMS = ("decrease", "decreased", "lower", "declined", "reduced", "fell")
UNCHANGED_TERMS = ("unchanged", "flat", "consistent", "stable")
FINANCIAL_TERMS = (
    "revenue",
    "sales",
    "gross",
    "margin",
    "income",
    "cash",
    "debt",
    "borrowings",
    "eps",
    "earnings per share",
    "liquidity",
)


class FinancialClaimExtractionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        extractor: ClaimExtractorProvider,
    ) -> None:
        self.session = session
        self.settings = settings
        self.extractor = extractor
        self.repo = FinancialRepository(session)
        self.registry = FinancialMetricRegistry(session, settings)

    async def extract_from_passage(
        self,
        *,
        filing_id: uuid.UUID,
        source_section: FilingSection,
        passage: PassageUnit | None,
        text: str,
        comparison_id: uuid.UUID | None = None,
        disclosure_change_id: uuid.UUID | None = None,
    ) -> list[FinancialClaim]:
        metric_names = [
            metric.canonical_name
            for metric in await self.repo.list_metric_definitions(active_only=True)
        ]
        extracted = await self._hybrid_extract(
            text,
            {
                "section_type": source_section.section_type,
                "section_title": source_section.section_title,
            },
            metric_names,
        )
        claims = []
        for item in extracted:
            metric = (
                await self.repo.get_metric_by_name(item.canonical_metric_name)
                if item.canonical_metric_name
                else None
            )
            claim = FinancialClaim(
                filing_id=filing_id,
                comparison_id=comparison_id,
                disclosure_change_id=disclosure_change_id,
                source_section_id=source_section.id,
                source_passage_id=passage.id if passage is not None else None,
                claim_text=item.claim_text,
                canonical_metric_name=item.canonical_metric_name,
                metric_definition_id=metric.id if metric is not None else None,
                claim_type=item.claim_type,
                direction=item.direction,
                reported_value=item.reported_value,
                reported_unit=item.reported_unit,
                reported_change=item.reported_change,
                reported_change_unit=item.reported_change_unit,
                comparison_basis=item.comparison_basis,
                comparison_text=item.comparison_text,
                qualifiers=item.qualifiers,
                extraction_confidence=item.confidence,
                extraction_method="hybrid",
                original_model_output=item.model_dump(mode="json"),
                model_name=self.extractor.model_name,
                model_version=self.extractor.model_version,
                prompt_version=self.extractor.prompt_version,
            )
            stored, _ = await self.repo.upsert_claim(claim)
            claims.append(stored)
        return claims

    async def _hybrid_extract(
        self,
        text: str,
        section_metadata: dict[str, object],
        allowed_metrics: list[str],
    ) -> list[FinancialClaimExtraction]:
        deterministic = await self._deterministic_extract(text)
        model_outputs = await self.extractor.extract_claims(text, section_metadata, allowed_metrics)
        return deterministic or model_outputs

    async def _deterministic_extract(self, text: str) -> list[FinancialClaimExtraction]:
        claims: list[FinancialClaimExtraction] = []
        for sentence in _sentences(text):
            if not _looks_financial(sentence):
                continue
            resolution = await self.registry.resolve_metric(sentence)
            numbers = parse_all_financial_numbers(sentence)
            direction = _direction(sentence)
            comparison_basis = parse_comparison_basis(sentence)
            numeric = numbers[0] if numbers else None
            claim_type = _claim_type(sentence, numeric, direction, comparison_basis)
            reported_value = None
            reported_unit = None
            reported_change = None
            reported_change_unit = None
            if numeric is not None:
                if claim_type == "absolute_value":
                    reported_value = numeric.value
                    reported_unit = numeric.unit
                elif claim_type == "percentage_change":
                    reported_change = numeric.value
                    reported_change_unit = "percent"
                elif claim_type == "percentage_point_change":
                    reported_change = numeric.value
                    reported_change_unit = "percentage_points"
            confidence = (
                Decimal("0.95")
                if resolution.status == "resolved" and numeric
                else Decimal("0.70")
            )
            claims.append(
                FinancialClaimExtraction(
                    claim_text=sentence,
                    canonical_metric_name=(
                        resolution.metric.canonical_name if resolution.metric is not None else None
                    ),
                    claim_type=claim_type,
                    direction=direction,
                    reported_value=reported_value,
                    reported_unit=reported_unit,
                    reported_change=reported_change,
                    reported_change_unit=reported_change_unit,
                    comparison_basis=comparison_basis,
                    comparison_text=_comparison_text(sentence),
                    qualifiers={
                        "metric_resolution_status": resolution.status,
                        "metric_resolution_reason": resolution.reason,
                        "numbers": [
                            {
                                "text": item.original_text,
                                "value": str(item.value),
                                "unit": item.unit,
                            }
                            for item in numbers
                        ],
                    },
                    confidence=confidence,
                    original_output={"deterministic": True},
                )
            )
        return claims


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_RE.split(text.replace("\n", " ")) if part.strip()]


def _looks_financial(text: str) -> bool:
    value = text.lower()
    return any(term in value for term in FINANCIAL_TERMS)


def _direction(text: str) -> str | None:
    value = text.lower()
    if any(term in value for term in INCREASE_TERMS):
        return "increase"
    if any(term in value for term in DECREASE_TERMS):
        return "decrease"
    if any(term in value for term in UNCHANGED_TERMS):
        return "unchanged"
    return None


def _claim_type(
    text: str,
    numeric,
    direction: str | None,
    comparison_basis: str | None,
) -> str:
    if numeric is None:
        return "directional_change" if direction else "qualitative_financial_claim"
    if numeric.unit == "percent" and (direction or comparison_basis):
        return "percentage_change"
    if numeric.unit == "percentage_points":
        return "percentage_point_change"
    if direction and comparison_basis:
        return "comparative_statement"
    return "absolute_value"


def _comparison_text(text: str) -> str | None:
    lower = text.lower()
    for marker in ("compared with", "compared to", "versus", "vs.", "year over year"):
        index = lower.find(marker)
        if index >= 0:
            return text[index:]
    return None
