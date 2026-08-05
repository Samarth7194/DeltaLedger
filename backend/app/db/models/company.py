from __future__ import annotations

from sqlalchemy import Boolean, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class Company(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_active_ticker", "is_active", "ticker"),
        Index(
            "uq_companies_ticker_not_null",
            "ticker",
            unique=True,
            postgresql_where=text("ticker IS NOT NULL"),
        ),
    )

    cik: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(64), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fiscal_year_end: Mapped[str | None] = mapped_column(String(8), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    filings = relationship("Filing", back_populates="company", cascade="all, delete-orphan")
    xbrl_facts = relationship("XbrlFact", back_populates="company", cascade="all, delete-orphan")
