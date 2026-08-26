from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class ManualPortfolio(Base):
    __tablename__ = "manual_portfolios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_manual_portfolios_status"),
        Index("ix_manual_portfolios_user_status", "user_id", "status", "updated_at"),
    )


class ManualPosition(Base):
    __tablename__ = "manual_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("manual_portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    average_unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 6))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    research_case_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("research_cases.id", ondelete="SET NULL")
    )
    research_revision_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("research_case_revisions.id", ondelete="SET NULL")
    )
    opened_on: Mapped[date] = mapped_column(Date, nullable=False)
    closed_on: Mapped[Optional[date]] = mapped_column(Date)
    last_reviewed_on: Mapped[Optional[date]] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "((state = 'open' AND quantity > 0 AND closed_on IS NULL) OR "
            "(state = 'closed' AND quantity = 0 AND closed_on IS NOT NULL))",
            name="ck_manual_positions_state_shape",
        ),
        CheckConstraint(
            "average_unit_cost IS NULL OR average_unit_cost > 0",
            name="ck_manual_positions_average_cost",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_manual_positions_currency"),
        Index(
            "uq_manual_positions_open_portfolio_stock",
            "portfolio_id",
            "stock_id",
            unique=True,
            postgresql_where=text("state = 'open'"),
        ),
        Index("ix_manual_positions_user_state", "user_id", "state", "updated_at"),
        Index("ix_manual_positions_portfolio_created", "portfolio_id", "created_at"),
    )


class PositionJournalEvent(Base):
    __tablename__ = "position_journal_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("manual_positions.id", ondelete="RESTRICT"), nullable=False
    )
    portfolio_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("manual_portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    effective_on: Mapped[date] = mapped_column(Date, nullable=False)
    prior_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 8))
    new_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 8))
    prior_average_unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 6))
    new_average_unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 6))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    research_case_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("research_cases.id", ondelete="SET NULL")
    )
    research_revision_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("research_case_revisions.id", ondelete="SET NULL")
    )
    recorded_stock_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False
    )
    recorded_ticker: Mapped[str] = mapped_column(String(40), nullable=False)
    recorded_company_name: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_exchange: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "position_id", "sequence_number", name="uq_position_journal_events_sequence"
        ),
        CheckConstraint(
            "event_type IN ('open', 'resize', 'close', 'review')",
            name="ck_position_journal_events_type",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_position_journal_events_currency"),
        Index("ix_position_journal_events_position_created", "position_id", "created_at"),
        Index("ix_position_journal_events_user_effective", "user_id", "effective_on"),
    )
