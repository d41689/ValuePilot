from datetime import date, datetime
from typing import Optional, Any, TYPE_CHECKING
from sqlalchemy import BigInteger, String, DateTime, Boolean, ForeignKey, Integer, Float, Date, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.db import Base

if TYPE_CHECKING:
    from app.models.users import User
    from app.models.stocks import Stock


def _default_parse_generation(context) -> Optional[int]:
    return 1 if context.get_current_parameters().get("source_type") == "parsed" else None

class MetricFact(Base):
    __tablename__ = "metric_facts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Public SEC actuals are shared canonical facts and therefore have no user
    # owner. Every other source remains strictly user-owned.
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    metric_key: Mapped[str] = mapped_column(String, index=True)
    value_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
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
    # Polymorphic durable source reference. A current manual val.fair_value fact
    # must identify the exact publishing research_case_revision.
    source_ref_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    parse_generation: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=_default_parse_generation
    )

    user: Mapped["User"] = relationship("User")
    stock: Mapped["Stock"] = relationship("Stock")

class Formula(Base):
    __tablename__ = "formulas"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String)
    output_key: Mapped[str] = mapped_column(String)
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
    output_key_snapshot: Mapped[str] = mapped_column(String)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    period: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    as_of_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    input_fact_ids_json: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
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
