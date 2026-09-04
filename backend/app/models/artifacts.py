from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import BigInteger, CheckConstraint, String, Date, DateTime, Boolean, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.db import Base

if TYPE_CHECKING:
    from app.models.users import User
    from app.models.stocks import Stock

class ParserTemplate(Base):
    __tablename__ = "parser_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    vendor: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class PdfDocument(Base):
    __tablename__ = "pdf_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    file_name: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    upload_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    report_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    file_storage_key: Mapped[str] = mapped_column(String)
    parse_status: Mapped[str] = mapped_column(String) # pending / parsed / failed / unsupported_template / requires_ocr
    parser_template_id: Mapped[Optional[int]] = mapped_column(ForeignKey("parser_templates.id"), nullable=True)
    parser_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stock_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stocks.id"), nullable=True)
    identity_needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship("User")
    stock: Mapped[Optional["Stock"]] = relationship("Stock")
    parser_template: Mapped[Optional["ParserTemplate"]] = relationship("ParserTemplate")
    pages: Mapped[list["DocumentPage"]] = relationship(back_populates="document")

class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("pdf_documents.id"))
    page_number: Mapped[int] = mapped_column(Integer)
    page_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_image_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    text_extraction_method: Mapped[str] = mapped_column(String) # native_text / ocr

    document: Mapped["PdfDocument"] = relationship(back_populates="pages")


class ValueLineParseRun(Base):
    """Durable identity for one immutable Value Line extraction/fact set."""

    __tablename__ = "value_line_parse_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_value_line_parse_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_documents.id", ondelete="CASCADE"), nullable=False
    )
    parser_version: Mapped[str] = mapped_column(String, nullable=False)
    source_mapping_version: Mapped[str] = mapped_column(
        ForeignKey("value_line_mapping_policies.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_txid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ValueLineMappingPolicy(Base):
    """Migration-approved immutable Value Line semantic policy identity."""

    __tablename__ = "value_line_mapping_policies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('approved', 'superseded')",
            name="ck_value_line_mapping_policies_status",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    spec_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    retired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ValueLineFactExtractionInput(Base):
    """Append-only exact extraction input for one parsed Value Line fact."""

    __tablename__ = "value_line_fact_extraction_inputs"
    __table_args__ = (
        CheckConstraint(
            "input_role IN ('primary', 'supporting')",
            name="ck_value_line_fact_extraction_inputs_role",
        ),
        CheckConstraint(
            "input_ordinal > 0",
            name="ck_value_line_fact_extraction_inputs_ordinal",
        ),
    )

    fact_id: Mapped[int] = mapped_column(
        ForeignKey("metric_facts.id", ondelete="CASCADE"), primary_key=True
    )
    extraction_id: Mapped[int] = mapped_column(
        ForeignKey("metric_extractions.id", ondelete="CASCADE"), primary_key=True
    )
    value_line_parse_run_id: Mapped[int] = mapped_column(
        ForeignKey("value_line_parse_runs.id", ondelete="CASCADE"), nullable=False
    )
    input_role: Mapped[str] = mapped_column(String, nullable=False)
    input_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_txid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
