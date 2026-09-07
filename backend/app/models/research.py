from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column, validates
from sqlalchemy.sql import func

from app.core.db import Base


RESEARCH_CASE_STATES = {"queued", "researching", "monitoring", "closed", "voided"}
RESEARCH_DECISIONS = {"watch", "own", "pass"}
RESEARCH_ORIGIN_TYPES = {
    "manual",
    "ticker_search",
    "watchlist",
    "screener",
    "oracle_lens",
    "manager_holding",
    "manager_change",
}
RESEARCH_INBOX_ACTION_STATES = {
    "open",
    "snoozed",
    "dismissed",
    "completed",
    "superseded",
}
RESEARCH_INBOX_ACTION_FAMILIES = {
    "review_due",
    "continue_research",
    "start_research",
    "coverage_gap",
    "candidate_discovery",
    "manager_activity",
}


def _validate_choice(field: str, value: str, choices: set[str]) -> str:
    if value not in choices:
        raise ValueError(f"unsupported {field}: {value}")
    return value


class ResearchCase(Base):
    """User-owned current projection for one auditable research cycle."""

    __tablename__ = "research_cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), nullable=False)
    state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="queued", server_default="queued"
    )
    decision: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    next_review_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    void_reason_content_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    head_revision_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'researching', 'monitoring', 'closed', 'voided')",
            name="ck_research_cases_state",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN ('watch', 'own', 'pass')",
            name="ck_research_cases_decision",
        ),
        CheckConstraint(
            "((state IN ('queued', 'researching') AND decision IS NULL "
            "AND next_review_on IS NULL AND void_reason IS NULL) OR "
            "(state = 'monitoring' AND decision IN ('watch', 'own') "
            "AND next_review_on IS NOT NULL AND void_reason IS NULL) OR "
            "(state = 'closed' AND decision = 'pass' "
            "AND next_review_on IS NULL AND void_reason IS NULL) OR "
            "(state = 'voided' AND decision IS NULL AND next_review_on IS NULL "
            "AND length(btrim(void_reason)) > 0))",
            name="ck_research_cases_state_shape",
        ),
        Index(
            "uq_research_cases_active_user_stock",
            "user_id",
            "stock_id",
            unique=True,
            postgresql_where=text("state IN ('queued', 'researching', 'monitoring')"),
        ),
        Index("ix_research_cases_user_state_updated", "user_id", "state", "updated_at"),
    )

    @validates("state")
    def _validate_state(self, _: str, value: str) -> str:
        return _validate_choice("research case state", value, RESEARCH_CASE_STATES)

    @validates("decision")
    def _validate_decision(self, _: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _validate_choice("research decision", value, RESEARCH_DECISIONS)


class ResearchCaseOrigin(Base):
    """Append-only discovery context; never overwrites the initial origin."""

    __tablename__ = "research_case_origins"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("research_cases.id"), nullable=False)
    origin_type: Mapped[str] = mapped_column(String(32), nullable=False)
    origin_key: Mapped[str] = mapped_column(String(240), nullable=False)
    source_version: Mapped[str] = mapped_column(String(120), nullable=False)
    source_ref_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "case_id", "origin_type", "origin_key", "source_version",
            name="uq_research_case_origins_source",
        ),
        CheckConstraint(
            "origin_type IN ('manual', 'ticker_search', 'watchlist', 'screener', "
            "'oracle_lens', 'manager_holding', 'manager_change')",
            name="ck_research_case_origins_type",
        ),
        Index("ix_research_case_origins_case_created", "case_id", "created_at"),
    )

    @validates("origin_type")
    def _validate_origin_type(self, _: str, value: str) -> str:
        return _validate_choice("research origin type", value, RESEARCH_ORIGIN_TYPES)


class ResearchCaseRevision(Base):
    """Immutable full decision snapshot, except for audited content redaction."""

    __tablename__ = "research_case_revisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("research_cases.id"), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    thesis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    variant_view: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assumptions_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    risks_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    evidence_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    case_state: Mapped[str] = mapped_column(String(24), nullable=False)
    is_qualified_decision: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    valuation_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 6), nullable=True)
    valuation_base: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 6), nullable=True)
    valuation_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 6), nullable=True)
    valuation_currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    valuation_unavailable_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    valuation_as_of_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    next_review_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    snapshot_stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"), nullable=False)
    stock_ticker: Mapped[str] = mapped_column(String(40), nullable=False)
    stock_company_name: Mapped[str] = mapped_column(Text, nullable=False)
    stock_exchange: Mapped[str] = mapped_column(String(40), nullable=False)
    stock_listing_exchange: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    is_redacted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    redaction_content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    redaction_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    redaction_reason_content_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    redacted_by_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    redacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("case_id", "revision_number", name="uq_research_case_revision_number"),
        CheckConstraint(
            "decision IS NULL OR decision IN ('watch', 'own', 'pass')",
            name="ck_research_case_revisions_decision",
        ),
        CheckConstraint(
            "case_state IN ('queued', 'researching', 'monitoring', 'closed', 'voided')",
            name="ck_research_case_revisions_state",
        ),
        CheckConstraint(
            "((valuation_low IS NULL AND valuation_base IS NULL "
            "AND valuation_high IS NULL AND valuation_currency IS NULL) OR "
            "(valuation_low IS NOT NULL AND valuation_base IS NOT NULL "
            "AND valuation_high IS NOT NULL AND valuation_currency = 'USD' "
            "AND valuation_unavailable_reason IS NULL "
            "AND valuation_low <= valuation_base "
            "AND valuation_base <= valuation_high))",
            name="ck_research_case_revisions_valuation_shape",
        ),
        Index("ix_research_case_revisions_case_created", "case_id", "created_at"),
    )

    @validates("decision")
    def _validate_revision_decision(self, _: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _validate_choice("research decision", value, RESEARCH_DECISIONS)


class ResearchCaseEvent(Base):
    """Append-only audit event for research-case state and content operations."""

    __tablename__ = "research_case_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("research_cases.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "case_id", "event_type", "correlation_id",
            name="uq_research_case_event_correlation",
        ),
        Index("ix_research_case_events_case_created", "case_id", "created_at"),
    )


class ResearchInboxAction(Base):
    """User-owned current action projection keyed to an immutable source version."""

    __tablename__ = "research_inbox_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    logical_key: Mapped[str] = mapped_column(String(240), nullable=False)
    action_family: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(24), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(160), nullable=False)
    source_version: Mapped[str] = mapped_column(String(200), nullable=False)
    supersedes_action_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("research_inbox_actions.id"), nullable=True
    )
    priority_policy_version: Mapped[str] = mapped_column(String(48), nullable=False)
    matched_rule: Mapped[str] = mapped_column(String(80), nullable=False)
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    rank_components: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="open", server_default="open")
    snoozed_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    target_case_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("research_cases.id"), nullable=True
    )
    stock_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("stocks.id"), nullable=True
    )
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "logical_key", "source_version",
            name="uq_research_inbox_action_source",
        ),
        CheckConstraint(
            "state IN ('open', 'snoozed', 'dismissed', 'completed', 'superseded')",
            name="ck_research_inbox_actions_state",
        ),
        CheckConstraint(
            "action_family IN ('review_due', 'continue_research', 'start_research', "
            "'coverage_gap', 'candidate_discovery', 'manager_activity')",
            name="ck_research_inbox_actions_family",
        ),
        CheckConstraint(
            "((state = 'snoozed' AND snoozed_until IS NOT NULL) OR "
            "(state <> 'snoozed' AND snoozed_until IS NULL))",
            name="ck_research_inbox_actions_snooze_shape",
        ),
        Index(
            "ix_research_inbox_user_state_rank",
            "user_id", "state", "priority_rank", "id",
        ),
        Index("ix_research_inbox_user_logical", "user_id", "logical_key"),
    )

    @validates("state")
    def _validate_inbox_state(self, _: str, value: str) -> str:
        return _validate_choice("research inbox state", value, RESEARCH_INBOX_ACTION_STATES)

    @validates("action_family")
    def _validate_inbox_family(self, _: str, value: str) -> str:
        return _validate_choice("research inbox family", value, RESEARCH_INBOX_ACTION_FAMILIES)


class ResearchInboxActionEvent(Base):
    """Append-only audit history for Inbox projection changes."""

    __tablename__ = "research_inbox_action_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    action_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("research_inbox_actions.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    payload_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_research_inbox_events_action_created", "action_id", "created_at"),
        Index("ix_research_inbox_events_user_created", "user_id", "created_at"),
    )
