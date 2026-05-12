"""Oracle's Lens scoring tables (MVP4-01).

The product plan (`docs/plans/13f_oracles_lens_dashboard_product_plan.md`)
ranks stocks for the user-facing 13F research surface. Scoring is a
**derived** view on top of MVP1B holdings; per the MVP4 decision gate's
pre-start condition #3 these tables never feed back into ingestion
audit (no mutation of `holdings_13f` / `ownership_changes`).

Two tables:

- ``oracles_lens_signals`` — one row per
  ``(stock_id, report_quarter, score_version)``. Carries the primary
  ranking score plus secondary explainers and per-row caution-flag
  codes (per D3 caveat-propagation rules a–e and the canonical
  readiness vocabulary).
- ``oracles_lens_score_components`` — per-score component breakdown
  (manager / position / streak / action adjustments). Mirrors the
  ``quality_findings_13f`` pattern from MVP3-02 so component-level
  queries are first-class (TL D5 revision: separate table, not a
  JSONB blob).

Concurrency / write-path:
- Score recompute is idempotent per
  ``(stock_id, report_quarter, score_version)`` — write path uses
  ORM upsert
  (``INSERT ... ON CONFLICT (stock_id, report_quarter, score_version)
  DO UPDATE``) per the MVP4-01 pre-start condition #4.
- One ``JobRun(job_type='oracles_lens_score_backfill',
  lock_key='oracles_lens_score:{period}:{score_version}')`` row per
  recompute run; ``source_job_id`` on each score row points at the
  producing job.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.sql import func

from app.core.db import Base
from app.models.institutions import (
    OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS,
    _validate_choice,
)


class OraclesLensSignal(Base):
    __tablename__ = "oracles_lens_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), nullable=False)
    report_quarter: Mapped[str] = mapped_column(String(10), nullable=False)
    quarter_end_date: Mapped["datetime.date"] = mapped_column(Date, nullable=False)
    score_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # Plan §7.1
    raw_consensus_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Plan §7.2 — primary ranking. Null when score_confidence='unavailable'.
    signal_weighted_consensus_score: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)

    # Plan §7.9
    conviction_score: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)

    # Plan §7.11 — advanced sort, visible-but-off-by-default per PO clarification.
    distinctive_consensus_score: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)

    # Plan §7.4 (aggregated across contributing managers).
    add_intensity: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)

    # Plan §7.10 — shared primitive consumed by §7.2 (MVP4-03) and §7.9 (MVP4-04).
    holding_streak_quarters: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Plan §7.12. Same vocabulary as OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS for
    # consistency with MVP2 ownership_changes. SME D3 caveat propagation
    # rules a–e drive demotions.
    score_confidence: Mapped[str] = mapped_column(String(20), nullable=False)

    # Plan §7.13 + D3 caveat propagation. JSON array of canonical readiness
    # codes (CONFIDENTIAL_TREATMENT, PARTIAL_COVERAGE, AMENDMENTS_PENDING,
    # AMENDMENT_FAILED, NT_DETECTION_UNSUPPORTED,
    # OWNERSHIP_CHANGES_NEEDS_RECOMPUTE, HISTORICAL_BACKFILL_NEEDS_VALIDATION,
    # PRE_2023_PRE_HISTORY_UNAVAILABLE) plus score-service-emitted row-level
    # codes (NT_QUARTER_STREAK_BREAK, stale_until_recompute).
    caution_flag_codes: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Composite summary surfaced in the ranking table (plan §9.1
    # score_explanation sketch). The full per-manager component breakdown
    # lives in OraclesLensScoreComponent (separate table, queryable).
    score_explanation: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("job_runs.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    components: Mapped[list["OraclesLensScoreComponent"]] = relationship(
        back_populates="score",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "stock_id",
            "report_quarter",
            "score_version",
            name="uq_oracles_lens_signals_stock_quarter_version",
        ),
        Index(
            "idx_oracles_lens_signals_quarter_version",
            "report_quarter",
            "score_version",
        ),
        Index(
            "idx_oracles_lens_signals_ranking",
            "score_version",
            "signal_weighted_consensus_score",
        ),
    )

    @validates("score_confidence")
    def _validate_score_confidence(self, _: str, value: str) -> str:
        return _validate_choice("score_confidence", value, OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS)


class OraclesLensScoreComponent(Base):
    __tablename__ = "oracles_lens_score_components"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    score_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("oracles_lens_signals.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_name: Mapped[str] = mapped_column(String(80), nullable=False)
    manager_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("institution_managers.id"), nullable=True
    )
    numeric_value: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)
    string_value: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Evidence is intentionally loose: per-component metadata such as which
    # caveat caused a demotion, which manager_type bucket fed the weight, etc.
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    score: Mapped[OraclesLensSignal] = relationship(back_populates="components")

    __table_args__ = (
        # Per-aggregate (manager_id IS NULL) and per-manager rows share the
        # unique surface. Postgres treats NULLs as distinct in UNIQUE so
        # multiple aggregate rows for the same (score_id, component_name)
        # could slip through — the implementing service is responsible for
        # writing exactly one aggregate row per (score_id, component_name).
        # If duplicate-aggregate becomes a real concern, replace this with a
        # partial unique index pair.
        UniqueConstraint(
            "score_id",
            "component_name",
            "manager_id",
            name="uq_oracles_lens_score_components_per_score_component_manager",
        ),
        Index(
            "idx_oracles_lens_score_components_score_component",
            "score_id",
            "component_name",
        ),
    )
