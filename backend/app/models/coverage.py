from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates
from sqlalchemy.sql import func

from app.core.db import Base


COVERAGE_KINDS = {
    "eod_price",
    "value_line_current_report",
    "valuation_input",
    "identity_review",
    "cusip_review",
}
COVERAGE_STATES = {
    "ready",
    "missing",
    "stale",
    "blocked",
    "in_progress",
    "failed",
}


class ResearchCoverageRequirement(Base):
    """User-scoped current readiness projection with versioned reasoning."""

    __tablename__ = "research_coverage_requirements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stocks.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    priority_policy_version: Mapped[str] = mapped_column(String(48), nullable=False)
    matched_rule: Mapped[str] = mapped_column(String(80), nullable=False)
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    rank_components: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    source_ref_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    observed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    freshness_policy_version: Mapped[str] = mapped_column(String(48), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_action: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    first_unmet_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "stock_id",
            "kind",
            "priority_policy_version",
            name="uq_research_coverage_user_stock_kind_policy",
        ),
        Index(
            "ix_research_coverage_user_current_rank",
            "user_id",
            "is_current",
            "priority_rank",
        ),
        Index(
            "ix_research_coverage_user_state",
            "user_id",
            "state",
        ),
        CheckConstraint(
            "kind IN ('eod_price', 'value_line_current_report', "
            "'valuation_input', 'identity_review', 'cusip_review')",
            name="ck_research_coverage_kind",
        ),
        CheckConstraint(
            "state IN ('ready', 'missing', 'stale', 'blocked', "
            "'in_progress', 'failed')",
            name="ck_research_coverage_state",
        ),
    )

    @validates("kind")
    def _validate_kind(self, _: str, value: str) -> str:
        if value not in COVERAGE_KINDS:
            raise ValueError(f"unsupported coverage kind: {value}")
        return value

    @validates("state")
    def _validate_state(self, _: str, value: str) -> str:
        if value not in COVERAGE_STATES:
            raise ValueError(f"unsupported coverage state: {value}")
        return value
