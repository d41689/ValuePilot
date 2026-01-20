from datetime import date, datetime
from typing import Optional, Any, TYPE_CHECKING
from sqlalchemy import String, DateTime, Boolean, ForeignKey, Integer, Float, Date, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.db import Base

if TYPE_CHECKING:
    from app.models.users import User
    from app.models.stocks import Stock

class MetricFact(Base):
    __tablename__ = "metric_facts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    metric_key: Mapped[str] = mapped_column(String, index=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    value_numeric: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    value_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    as_of_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source_document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pdf_documents.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String) # parsed / calculated / manual
    source_ref_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) # ID of extraction or formula run
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user: Mapped["User"] = relationship("User")
    stock: Mapped["Stock"] = relationship("Stock")

class Formula(Base):
    __tablename__ = "formulas"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String)
    expression: Mapped[str] = mapped_column(Text)
    dependencies_json: Mapped[list[str]] = mapped_column(JSON)
    compiled_ast_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user: Mapped["User"] = relationship("User")

class CalculatedRun(Base):
    __tablename__ = "calculated_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    formula_id: Mapped[int] = mapped_column(ForeignKey("formulas.id"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    period: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    as_of_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    result_value_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_dirty: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user: Mapped["User"] = relationship("User")
    formula: Mapped["Formula"] = relationship("Formula")
    stock: Mapped["Stock"] = relationship("Stock")

class ScreeningRule(Base):
    __tablename__ = "screening_rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String)
    rule_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user: Mapped["User"] = relationship("User")
