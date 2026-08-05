from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import XbrlFact


class XbrlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_company_facts(
        self,
        *,
        company_id: uuid.UUID,
        facts: list[dict[str, object]],
    ) -> int:
        await self.session.execute(delete(XbrlFact).where(XbrlFact.company_id == company_id))
        for fact in facts:
            value = fact.get("val")
            numeric_value = (
                Decimal(str(value)) if isinstance(value, int | float | Decimal) else None
            )
            self.session.add(
                XbrlFact(
                    company_id=company_id,
                    filing_id=None,
                    taxonomy=str(fact.get("taxonomy", "")),
                    concept=str(fact.get("concept", "")),
                    label=fact.get("label") if isinstance(fact.get("label"), str) else None,
                    unit=fact.get("unit") if isinstance(fact.get("unit"), str) else None,
                    value_numeric=numeric_value,
                    value_text=str(value) if numeric_value is None and value is not None else None,
                    start_date=_parse_date(fact.get("start")),
                    end_date=_parse_date(fact.get("end")),
                    instant_date=_parse_date(fact.get("instant")),
                    fiscal_year=fact.get("fy") if isinstance(fact.get("fy"), int) else None,
                    fiscal_period=fact.get("fp") if isinstance(fact.get("fp"), str) else None,
                    form_type=fact.get("form") if isinstance(fact.get("form"), str) else None,
                    accession_number=(
                        fact.get("accn") if isinstance(fact.get("accn"), str) else None
                    ),
                    frame=fact.get("frame") if isinstance(fact.get("frame"), str) else None,
                    raw_fact=fact,
                )
            )
        return len(facts)

    async def list_company_concept_facts(
        self, company_id: uuid.UUID, concept: str, limit: int = 50
    ) -> list[XbrlFact]:
        stmt = (
            select(XbrlFact)
            .where(XbrlFact.company_id == company_id, XbrlFact.concept == concept)
            .order_by(
                XbrlFact.end_date.desc().nullslast(),
                XbrlFact.instant_date.desc().nullslast(),
            )
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    return None
