from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class CompanyAnalysisClassification(Base):
    __tablename__ = "company_analysis_classifications"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('ordinary_operating', 'bank', 'insurer', "
            "'reit', 'high_sbc_acquisitive', 'cyclical_commodity')",
            name="ck_company_analysis_classifications_value",
        ),
        CheckConstraint(
            "status IN ('reviewed', 'retired')",
            name="ck_company_analysis_classifications_status",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_company_analysis_classifications_interval",
        ),
        CheckConstraint(
            "length(btrim(review_reason)) > 0",
            name="ck_company_analysis_classifications_reason",
        ),
        UniqueConstraint(
            "supersedes_classification_id",
            name="uq_company_analysis_classification_supersession",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    classification: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    method_policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    reviewer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    supersedes_classification_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("company_analysis_classifications.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
