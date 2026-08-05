from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UuidPrimaryKeyMixin


class XbrlFact(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "xbrl_facts"
    __table_args__ = (
        Index(
            "ix_xbrl_company_concept_fy_fp",
            "company_id",
            "concept",
            "fiscal_year",
            "fiscal_period",
        ),
        Index("ix_xbrl_filing_concept", "filing_id", "concept"),
        Index("ix_xbrl_accession_concept_unit", "accession_number", "concept", "unit"),
        Index("ix_xbrl_frame", "frame"),
        Index("ix_xbrl_raw_fact_gin", "raw_fact", postgresql_using="gin"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
    )
    filing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("filings.id"),
        nullable=True,
    )
    taxonomy: Mapped[str] = mapped_column(String(64), nullable=False)
    concept: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(28, 6), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    instant_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    form_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    accession_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    frame: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_fact: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )

    company = relationship("Company", back_populates="xbrl_facts")
    filing = relationship("Filing", back_populates="xbrl_facts")
