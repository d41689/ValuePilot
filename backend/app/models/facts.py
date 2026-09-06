from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Any, TYPE_CHECKING
from sqlalchemy import BigInteger, String, DateTime, Boolean, ForeignKey, Integer, Float, Date, Text, JSON, Numeric
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
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    metric_key: Mapped[str] = mapped_column(String, index=True)
    value_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    value_numeric: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(38, 12), nullable=True, index=True
    )
    value_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    as_of_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pdf_documents.id", ondelete="CASCADE"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String) # parsed / calculated / manual
    # Polymorphic durable source reference. For manual val.fair_value facts this
    # may identify the publishing research_case_revision.
    source_ref_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # Exact immutable extraction-set identity for newly parsed Value Line facts.
    # Legacy parsed rows remain nullable and are treated conservatively.
    value_line_parse_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("value_line_parse_runs.id"), nullable=True, index=True
    )
    # PostgreSQL stamps this only for rows that predate parse-run authority.
    # New runless rows remain false and comparison-identity-incomplete.
    value_line_legacy_revision: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # DB-bound immutable report identity for parsed Value Line facts. The
    # migration binds provably consistent retained rows; an explicit document
    # stock must agree, while NULL is the supported multi-company-container
    # identity. Tenant or explicit-stock mismatches remain null and fail closed.
    value_line_report_identity_revision_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(
            "value_line_document_report_identity_revisions.id", ondelete="CASCADE"
        ),
        nullable=True,
        index=True,
    )
    # Conservative database observation time for retained parsed facts and the
    # exact database creation time for new parsed facts. A cutoff before this
    # stamp cannot claim point-in-time visibility from caller-provided times.
    value_line_fact_known_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Non-null only when PostgreSQL observed the fact's creating transaction.
    # Retained pre-authority facts remain NULL and use the conservative
    # value_line_fact_known_at observation boundary instead.
    value_line_created_txid: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user: Mapped[Optional["User"]] = relationship("User")
    stock: Mapped["Stock"] = relationship("Stock")


class MetricFactCurrentnessRevision(Base):
    """Append-only, database-owned history of the canonical projection flag."""

    __tablename__ = "metric_fact_currentness_revisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fact_id: Mapped[int] = mapped_column(
        ForeignKey("metric_facts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    stock_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metric_key: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_document_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_ref_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    period_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    period_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    as_of_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_txid: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_backfill: Mapped[bool] = mapped_column(Boolean, nullable=False)
    prior_revision_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("metric_fact_currentness_revisions.id", ondelete="RESTRICT"),
        nullable=True,
    )

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
