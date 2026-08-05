from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UuidPrimaryKeyMixin


class Filing(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "filings"
    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_filings_accession_number"),
        UniqueConstraint(
            "company_id",
            "form_type",
            "report_period",
            "accession_number",
            name="uq_filings_company_form_period_accession",
        ),
        Index("ix_filings_company_form_period", "company_id", "form_type", "report_period"),
        Index("ix_filings_ingestion_status_created", "ingestion_status", "created_at"),
        Index("ix_filings_raw_metadata_gin", "raw_metadata", postgresql_using="gin"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
    )
    accession_number: Mapped[str] = mapped_column(String(32), nullable=False)
    form_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_period: Mapped[date | None] = mapped_column(Date, nullable=True)
    primary_document: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingestion_status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )

    company = relationship("Company", back_populates="filings")
    sections = relationship("FilingSection", back_populates="filing", cascade="all, delete-orphan")
    tables = relationship("FilingTable", back_populates="filing", cascade="all, delete-orphan")
    processing_stages = relationship(
        "FilingProcessingStage",
        back_populates="filing",
        cascade="all, delete-orphan",
    )
    xbrl_facts = relationship("XbrlFact", back_populates="filing")


class FilingSection(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "filing_sections"
    __table_args__ = (
        UniqueConstraint("filing_id", "section_order", name="uq_filing_sections_order"),
        Index("ix_filing_sections_filing_type_order", "filing_id", "section_type", "section_order"),
        Index("ix_filing_sections_text_hash", "text_hash"),
        Index("ix_filing_sections_part_item", "filing_id", "part_number", "item_number"),
    )

    filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("filings.id"),
        nullable=False,
    )
    section_type: Mapped[str] = mapped_column(String(64), nullable=False)
    part_number: Mapped[str | None] = mapped_column(String(8), nullable=True)
    item_number: Mapped[str | None] = mapped_column(String(8), nullable=True)
    canonical_section_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section_title: Mapped[str] = mapped_column(String(512), nullable=False)
    section_order: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_sections.id"), nullable=True
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized_start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized_end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    page_or_anchor_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_anchor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    native_element_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dom_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )

    filing = relationship("Filing", back_populates="sections")
    tables = relationship("FilingTable", back_populates="filing_section")
    chunks = relationship(
        "FilingChunk",
        back_populates="filing_section",
        cascade="all, delete-orphan",
    )


class FilingChunk(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "filing_chunks"
    __table_args__ = (
        UniqueConstraint("filing_section_id", "chunk_index", name="uq_filing_chunks_section_index"),
        Index("ix_filing_chunks_section_index", "filing_section_id", "chunk_index"),
        Index("ix_filing_chunks_metadata_gin", "metadata", postgresql_using="gin"),
    )

    filing_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("filing_sections.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    source_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunker_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    search_vector: Mapped[object | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(text, ''))", persisted=True),
        nullable=True,
    )
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )

    filing_section = relationship("FilingSection", back_populates="chunks")


class FilingTable(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "filing_tables"
    __table_args__ = (
        UniqueConstraint("filing_id", "table_index", name="uq_filing_tables_index"),
        Index("ix_filing_tables_filing_section", "filing_id", "filing_section_id"),
        Index("ix_filing_tables_content_hash", "content_hash"),
        Index("ix_filing_tables_metadata_gin", "metadata", postgresql_using="gin"),
    )

    filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("filings.id"),
        nullable=False,
    )
    filing_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("filing_sections.id"),
        nullable=True,
    )
    table_index: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    raw_html: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_anchor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    native_element_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dom_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    extraction_version: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )

    filing = relationship("Filing", back_populates="tables")
    filing_section = relationship("FilingSection", back_populates="tables")


class FilingProcessingStage(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "filing_processing_stages"
    __table_args__ = (
        UniqueConstraint("filing_id", "stage_name", name="uq_processing_stage_filing_name"),
        Index("ix_processing_stage_filing_status", "filing_id", "status"),
    )

    filing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("filings.id"),
        nullable=False,
    )
    stage_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )

    filing = relationship("Filing", back_populates="processing_stages")
