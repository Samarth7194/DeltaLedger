from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.financial_claims import create_claim_extractor
from app.core.config import Settings
from app.db.models import DisclosureChange
from app.repositories.comparison_repository import ComparisonRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.section_repository import SectionRepository
from app.services.financial_claim_extraction_service import FinancialClaimExtractionService
from app.services.financial_claim_verification_service import FinancialClaimVerificationService


class FinancialVerificationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = FinancialRepository(session)
        self.sections = SectionRepository(session)
        self.comparisons = ComparisonRepository(session)
        self.extractor = FinancialClaimExtractionService(
            session,
            settings,
            create_claim_extractor(settings.claim_extractor_provider),
        )
        self.verifier = FinancialClaimVerificationService(session, settings)

    async def extract_claims_for_filing(self, filing_id: uuid.UUID) -> dict[str, int]:
        lock_acquired = await self.repo.try_acquire_verification_lock(filing_id)
        if not lock_acquired:
            return {"claims": 0, "status": 0}
        try:
            sections = await self.sections.list_sections(filing_id)
            count = 0
            for section in sections:
                claims = await self.extractor.extract_from_passage(
                    filing_id=filing_id,
                    source_section=section,
                    passage=None,
                    text=section.raw_text,
                )
                count += len(claims)
            await self.session.commit()
            return {"claims": count, "status": 1}
        finally:
            await self.repo.release_verification_lock(filing_id)

    async def verify_claim(self, claim_id: uuid.UUID):
        verification = await self.verifier.verify_claim(claim_id)
        await self.session.commit()
        return verification

    async def verify_claims_for_comparison(self, comparison_id: uuid.UUID) -> dict[str, int]:
        lock_acquired = await self.repo.try_acquire_verification_lock(comparison_id)
        if not lock_acquired:
            return {"claims": 0, "verifications": 0, "status": 0}
        try:
            comparison = await self.comparisons.get_comparison(comparison_id)
            if comparison is None:
                raise ValueError(f"Comparison not found: {comparison_id}")
            changes = await self.comparisons.list_changes(comparison_id, limit=500)
            claim_count = 0
            for change in changes:
                claim_count += len(await self._extract_from_change(change, "current"))
                claim_count += len(await self._extract_from_change(change, "previous"))
            claims = await self.repo.list_claims(comparison_id=comparison_id, limit=1000)
            verification_count = 0
            for claim in claims:
                await self.verifier.verify_claim(claim.id)
                verification_count += 1
            await self.session.commit()
            return {"claims": claim_count, "verifications": verification_count, "status": 1}
        except Exception:
            await self.session.rollback()
            raise
        finally:
            await self.repo.release_verification_lock(comparison_id)

    async def _extract_from_change(
        self,
        change: DisclosureChange,
        side: str,
    ) -> list[object]:
        evidence = change.supporting_evidence.get(side)
        text = change.current_text if side == "current" else change.previous_text
        if not isinstance(evidence, dict) or not text:
            return []
        section_id = evidence.get("section_id")
        passage_id = evidence.get("passage_id")
        filing_id = evidence.get("filing_id")
        if not section_id or not filing_id:
            return []
        section = await self.repo.get_section(uuid.UUID(str(section_id)))
        passage = await self.repo.get_passage(uuid.UUID(str(passage_id))) if passage_id else None
        if section is None:
            return []
        return await self.extractor.extract_from_passage(
            filing_id=uuid.UUID(str(filing_id)),
            source_section=section,
            passage=passage,
            text=text,
            comparison_id=change.comparison_id,
            disclosure_change_id=change.id,
        )
