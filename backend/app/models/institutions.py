from datetime import date, datetime
from typing import Optional, List
from sqlalchemy import (
    String, Text, Boolean, ForeignKey, BigInteger, Date,
    DateTime, Integer, Index, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.db import Base


class InstitutionManager(Base):
    __tablename__ = "institution_managers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cik: Mapped[Optional[str]] = mapped_column(String(10), unique=True, nullable=True)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    name_normalized: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_manager_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("institution_managers.id"), nullable=True,
    )
    dataroma_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    match_status: Mapped[str] = mapped_column(String(20), nullable=False, default="seeded")
    is_superinvestor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dataroma_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    filings: Mapped[List["Filing13F"]] = relationship(back_populates="manager")

    __table_args__ = (
        Index("idx_institution_managers_parent_manager_id", "parent_manager_id"),
    )


class RawSourceDocument(Base):
    __tablename__ = "raw_source_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_system: Mapped[str] = mapped_column(String(20), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    cik: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    accession_no: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    etag: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    body_path: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("uq_raw_source_documents_system_url", "source_system", "source_url", unique=True),
    )


class Filing13F(Base):
    __tablename__ = "filings_13f"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("institution_managers.id"), nullable=False)
    accession_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    period_of_report: Mapped[date] = mapped_column(Date, nullable=False)
    filed_at: Mapped[date] = mapped_column(Date, nullable=False)
    form_type: Mapped[str] = mapped_column(String(10), nullable=False)
    amends_accession_no: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    version_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_latest_for_period: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    has_confidential_treatment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reported_total_value_thousands: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    computed_total_value_thousands: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    raw_primary_doc_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_source_documents.id"), nullable=True
    )
    raw_infotable_doc_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_source_documents.id"), nullable=True
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    manager: Mapped["InstitutionManager"] = relationship(back_populates="filings")
    holdings: Mapped[List["Holding13F"]] = relationship(back_populates="filing")
    raw_primary_doc: Mapped[Optional["RawSourceDocument"]] = relationship(
        foreign_keys=[raw_primary_doc_id]
    )
    raw_infotable_doc: Mapped[Optional["RawSourceDocument"]] = relationship(
        foreign_keys=[raw_infotable_doc_id]
    )


class Holding13F(Base):
    __tablename__ = "holdings_13f"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filing_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("filings_13f.id"), nullable=False)
    row_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    cusip: Mapped[str] = mapped_column(String(9), nullable=False)
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False)
    title_of_class: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_thousands: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shares: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    share_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    put_call: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    investment_discretion: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    voting_sole: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    voting_shared: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    voting_none: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    stock_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("stocks.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    filing: Mapped["Filing13F"] = relationship(back_populates="holdings")

    __table_args__ = (
        UniqueConstraint("filing_id", "row_fingerprint", name="uq_holdings_13f_filing_fingerprint"),
    )


class CusipTickerMap(Base):
    __tablename__ = "cusip_ticker_map"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cusip: Mapped[str] = mapped_column(String(9), nullable=False)
    ticker: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    issuer_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    security_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    exchange: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    is_13f_reportable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    mapping_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("cusip", "valid_from", name="uq_cusip_ticker_map_cusip_valid_from"),
    )
