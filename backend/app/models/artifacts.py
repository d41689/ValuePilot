from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Date, DateTime, Boolean, ForeignKey, Integer, Text
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
