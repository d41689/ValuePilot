from datetime import date, datetime
from typing import Optional, Any, TYPE_CHECKING
from sqlalchemy import String, DateTime, Boolean, ForeignKey, Integer, Float, Date, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.db import Base

if TYPE_CHECKING:
    from app.models.users import User
    from app.models.artifacts import PdfDocument, ParserTemplate

class MetricExtraction(Base):
    __tablename__ = "metric_extractions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    document_id: Mapped[int] = mapped_column(ForeignKey("pdf_documents.id"))
    page_number: Mapped[int] = mapped_column(Integer)
    field_key: Mapped[str] = mapped_column(String)
    raw_value_text: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    original_text_snippet: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parsed_value_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period_type: Mapped[Optional[str]] = mapped_column(String, nullable=True) # FY / Q / TTM
    period_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    as_of_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bbox_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    parser_template_id: Mapped[Optional[int]] = mapped_column(ForeignKey("parser_templates.id"), nullable=True)
    parser_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    corrected_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    corrected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    target_year_range: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    user: Mapped["User"] = relationship("User")
    document: Mapped["PdfDocument"] = relationship("PdfDocument")
    parser_template: Mapped[Optional["ParserTemplate"]] = relationship("ParserTemplate")