from datetime import date, datetime
from typing import Optional, List
from sqlalchemy import (
    String, Text, Boolean, ForeignKey, BigInteger, Date,
    DateTime, Integer, Float, Index, UniqueConstraint, event, text, Numeric,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, validates
from sqlalchemy.sql import func
from app.core.db import Base


MANAGER_STATUSES = {"candidate", "active", "inactive", "ignored", "needs_review"}
MANAGER_TYPES = {"fundamental_long", "activist", "quant", "multi_strategy", "index_like", "unknown"}
VALUE_UNIT_OVERRIDES = {"infer", "thousands", "dollars"}
EDGAR_SYNC_STATUSES = {"pending", "running", "success", "failed", "no_data", "partial_success"}
NO_INDEX_REASONS = {"weekend", "federal_holiday", "edgar_special_closure", "other"}
NO_INDEX_SOURCES = {"auto_generated", "admin_manual"}
JOB_RUN_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "partial_success",
    "failed",
    "cancel_requested",
    "canceled",
    "skipped",
}
FILING_PARSE_STATUSES = {"pending", "succeeded", "failed", "partial_success", "needs_review"}
PARSE_RUN_STATUSES = {"running", "succeeded", "failed", "abandoned"}
HOLDING_CUSIP_MAPPING_STATUSES = {"linked", "invalid_cusip", "unresolved", "pending_mapping", "needs_review"}
CUSIP_MAPPING_STATUSES = {"confirmed", "superseded", "needs_review", "deleted"}
OWNERSHIP_CHANGE_STATUSES = {
    "new_position",
    "exited_position",
    "increased",
    "reduced",
    "unchanged",
    "no_prior_data",
    "unresolvable",
    "cusip_changed",
}
OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS = {"high_confidence", "medium_confidence", "low_confidence", "unavailable"}
OWNERSHIP_POSITION_TYPES = {"common", "put_option", "call_option"}
QUALITY_FINDING_STATUSES = {"open", "resolved", "ignored"}
QUALITY_FINDING_SEVERITIES = {"error", "warning", "info"}


def _validate_choice(field: str, value: str, choices: set[str]) -> str:
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{field} must be one of: {allowed}")
    return value


def _status_from_legacy_match_status(match_status: str | None) -> str:
    if match_status == "confirmed":
        return "active"
    if match_status == "revoked":
        return "needs_review"
    if match_status == "rejected":
        return "ignored"
    return "candidate"


class InstitutionManager(Base):
    __tablename__ = "institution_managers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    cik: Mapped[Optional[str]] = mapped_column(String(10), unique=True, nullable=True)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    edgar_legal_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    name_normalized: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_manager_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("institution_managers.id"), nullable=True,
    )
    dataroma_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    match_status: Mapped[str] = mapped_column(String(20), nullable=False, default="seeded")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate", server_default="candidate")
    manager_type: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown", server_default="unknown")
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    value_unit_override: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="infer",
        server_default="infer",
    )
    confirmed_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_superinvestor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    candidate_cik: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    candidate_legal_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    candidate_similarity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    candidate_source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    candidate_evidence_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    candidate_found_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prior_rejected_candidates: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    dataroma_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    filings: Mapped[List["Filing13F"]] = relationship(back_populates="manager")
    cik_review_events: Mapped[List["InstitutionManagerCikReviewEvent"]] = relationship(
        order_by="InstitutionManagerCikReviewEvent.created_at.desc()"
    )

    __table_args__ = (
        Index("idx_institution_managers_parent_manager_id", "parent_manager_id"),
        Index("ix_institution_managers_status", "status"),
        Index("ix_institution_managers_cik_status", "cik", "status"),
    )

    @validates("status")
    def _validate_status(self, _: str, value: str) -> str:
        return _validate_choice("status", value, MANAGER_STATUSES)

    @validates("manager_type")
    def _validate_manager_type(self, _: str, value: str) -> str:
        return _validate_choice("manager_type", value, MANAGER_TYPES)

    @validates("value_unit_override")
    def _validate_value_unit_override(self, _: str, value: str) -> str:
        return _validate_choice("value_unit_override", value, VALUE_UNIT_OVERRIDES)


@event.listens_for(InstitutionManager, "before_insert")
@event.listens_for(InstitutionManager, "before_update")
def _populate_manager_prd_fields(_, __, manager: InstitutionManager) -> None:
    if not manager.canonical_name:
        manager.canonical_name = manager.legal_name
    if not manager.edgar_legal_name and manager.cik:
        manager.edgar_legal_name = manager.legal_name
    if manager.match_status in {"confirmed", "revoked", "rejected"} and manager.status in {None, "candidate"}:
        manager.status = _status_from_legacy_match_status(manager.match_status)


class InstitutionManagerCikReviewEvent(Base):
    __tablename__ = "institution_manager_cik_review_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("institution_managers.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    old_cik: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    new_cik: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    old_match_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    new_match_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    affected_filings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    affected_quarters: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    requires_downstream_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_manager_cik_review_events_manager_id", "manager_id"),
        Index("ix_manager_cik_review_events_created_at", "created_at"),
    )


class RawSourceDocument(Base):
    __tablename__ = "raw_source_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_system: Mapped[str] = mapped_column(String(20), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    cik: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    accession_no: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    etag: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    body_path: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("uq_raw_source_documents_system_url", "source_system", "source_url", unique=True),
    )


class EdgarSyncStatus(Base):
    __tablename__ = "edgar_sync_status"
    __table_args__ = (
        Index("idx_sync_status", "status", "sync_date"),
    )

    sync_date: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", server_default="pending")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    form_idx_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_document_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_source_documents.id"), nullable=True
    )
    filings_seen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tracked_13f_hr_found_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tracked_13f_nt_found_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @validates("status")
    def _validate_status(self, _: str, value: str) -> str:
        return _validate_choice("status", value, EDGAR_SYNC_STATUSES)


class NoIndexExpectedDate(Base):
    __tablename__ = "no_index_expected_dates"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    holiday_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @validates("reason")
    def _validate_reason(self, _: str, value: str) -> str:
        return _validate_choice("reason", value, NO_INDEX_REASONS)

    @validates("source")
    def _validate_source(self, _: str, value: str) -> str:
        return _validate_choice("source", value, NO_INDEX_SOURCES)

    @classmethod
    def active_for_date(cls, session: Session, expected_date: date) -> Optional["NoIndexExpectedDate"]:
        return session.query(cls).filter(cls.date == expected_date, cls.active.is_(True)).one_or_none()


class Filing13F(Base):
    __tablename__ = "filings_13f"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("institution_managers.id"), nullable=False)
    accession_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    accession_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    cik: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    period_of_report: Mapped[date] = mapped_column(Date, nullable=False)
    filed_at: Mapped[date] = mapped_column(Date, nullable=False)
    form_type: Mapped[str] = mapped_column(String(10), nullable=False)
    report_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    coverage_completeness: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown", server_default="unknown")
    coverage_type: Mapped[str] = mapped_column(String(40), nullable=False, default="normal", server_default="normal")
    other_managers_included: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    other_managers_reporting: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    amends_accession_no: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    amends_accession_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    version_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_latest_for_period: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    has_confidential_treatment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidential_treatment_status: Mapped[str] = mapped_column(String(40), nullable=False, default="none", server_default="none")
    filing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    report_quarter: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    quarter_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    official_filing_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_amendment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    amendment_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    amendment_type_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active_for_manager_period: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    raw_filing_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_infotable_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", server_default="pending")
    parse_warning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parse_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parser_version: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    form_spec_version: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    xml_schema_version: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    total_13f_reported_value_usd: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_13f_common_value_usd: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    holdings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    common_holdings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    amendment_status: Mapped[str] = mapped_column(String(40), nullable=False, default="no_amendments_seen", server_default="no_amendments_seen")
    amendment_sort_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    reported_total_value_thousands: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    computed_total_value_thousands: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    raw_primary_doc_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_source_documents.id"), nullable=True
    )
    raw_infotable_doc_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("raw_source_documents.id"), nullable=True
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    manager: Mapped["InstitutionManager"] = relationship(back_populates="filings")
    holdings: Mapped[List["Holding13F"]] = relationship(back_populates="filing")
    parse_runs: Mapped[List["ParseRun13F"]] = relationship(
        primaryjoin="foreign(ParseRun13F.accession_number) == Filing13F.accession_number",
        viewonly=True,
    )
    raw_primary_doc: Mapped[Optional["RawSourceDocument"]] = relationship(
        foreign_keys=[raw_primary_doc_id]
    )
    raw_infotable_doc: Mapped[Optional["RawSourceDocument"]] = relationship(
        foreign_keys=[raw_infotable_doc_id]
    )

    __table_args__ = (
        Index(
            "uq_active_filing_per_manager_period",
            "manager_id",
            "quarter_end_date",
            unique=True,
            postgresql_where=text("is_active_for_manager_period = true"),
        ),
        Index("idx_filings_manager_qend", "manager_id", "quarter_end_date"),
        Index("idx_filings_manager_quarter", "manager_id", "report_quarter"),
        Index("idx_filings_active", "is_active_for_manager_period"),
        Index("idx_filings_parser_version", "parser_version"),
        Index("uq_filings_13f_accession_number", "accession_number", unique=True),
    )

    @validates("parse_status")
    def _validate_parse_status(self, _: str, value: str) -> str:
        return _validate_choice("parse_status", value, FILING_PARSE_STATUSES)


@event.listens_for(Filing13F, "before_insert")
@event.listens_for(Filing13F, "before_update")
def _populate_filing_prd_fields(_, __, filing: Filing13F) -> None:
    if not filing.accession_number and filing.accession_no:
        filing.accession_number = filing.accession_no
    if not filing.accession_no and filing.accession_number:
        filing.accession_no = filing.accession_number
    if not filing.amends_accession_number and filing.amends_accession_no:
        filing.amends_accession_number = filing.amends_accession_no
    if not filing.filing_date and filing.filed_at:
        filing.filing_date = filing.filed_at


class ParseRun13F(Base):
    __tablename__ = "parse_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(20), nullable=False)
    job_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("job_runs.id"), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    fingerprint_version: Mapped[str] = mapped_column(String(40), nullable=False, default="v1", server_default="v1")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running", server_default="running")
    holdings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    holdings: Mapped[List["Holding13F"]] = relationship(back_populates="parse_run")

    __table_args__ = (
        Index("idx_parse_runs_accession", "accession_number"),
        Index(
            "uq_parse_runs_current_accession",
            "accession_number",
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
    )

    @validates("status")
    def _validate_status(self, _: str, value: str) -> str:
        return _validate_choice("status", value, PARSE_RUN_STATUSES)


class Holding13F(Base):
    __tablename__ = "holdings_13f"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filing_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("filings_13f.id"), nullable=False)
    parse_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("parse_runs.id"), nullable=True)
    manager_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("institution_managers.id"), nullable=True)
    accession_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    report_quarter: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    quarter_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    row_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    holding_row_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    cusip: Mapped[str] = mapped_column(String(9), nullable=False)
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False)
    name_of_issuer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title_of_class: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_thousands: Mapped[int] = mapped_column(BigInteger, nullable=False)
    value_raw: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    value_unit_raw: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    value_parse_rule: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    value_usd: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    shares: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ssh_prnamt: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    share_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    ssh_prnamt_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    put_call: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    investment_discretion: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    other_managers_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    holding_attribution_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    voting_sole: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    voting_shared: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    voting_none: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    stock_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("stocks.id"), nullable=True
    )
    cusip_mapping_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending_mapping", server_default="pending_mapping")
    portfolio_weight_pct: Mapped[Optional[float]] = mapped_column(Numeric(12, 6), nullable=True)
    fingerprint_version: Mapped[str] = mapped_column(String(40), nullable=False, default="v1", server_default="v1")
    source_row_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    filing: Mapped["Filing13F"] = relationship(back_populates="holdings")
    parse_run: Mapped[Optional["ParseRun13F"]] = relationship(back_populates="holdings")

    __table_args__ = (
        UniqueConstraint("filing_id", "row_fingerprint", name="uq_holdings_13f_filing_fingerprint"),
        UniqueConstraint("parse_run_id", "holding_row_fingerprint", name="uq_holdings_fingerprint"),
        Index("idx_holdings_parse_run", "parse_run_id"),
        Index("idx_holdings_manager_qend", "manager_id", "quarter_end_date"),
        Index("idx_holdings_manager_quarter", "manager_id", "report_quarter"),
        Index("idx_holdings_cusip", "cusip"),
        Index("idx_holdings_stock_id", "stock_id"),
        Index("idx_holdings_put_call", "put_call"),
        Index("idx_holdings_attribution", "holding_attribution_status"),
    )

    @validates("cusip_mapping_status")
    def _validate_cusip_mapping_status(self, _: str, value: str) -> str:
        return _validate_choice("cusip_mapping_status", value, HOLDING_CUSIP_MAPPING_STATUSES)


class OwnershipChange13F(Base):
    __tablename__ = "ownership_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manager_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("institution_managers.id"), nullable=False)
    stock_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("stocks.id"), nullable=True)
    report_quarter: Mapped[str] = mapped_column(String(10), nullable=False)
    quarter_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    previous_report_quarter: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    previous_quarter_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    current_filing_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("filings_13f.id"), nullable=True)
    previous_filing_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("filings_13f.id"), nullable=True)
    current_holding_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("holdings_13f.id"), nullable=True)
    previous_holding_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("holdings_13f.id"), nullable=True)
    current_parse_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("parse_runs.id"), nullable=True)
    previous_parse_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("parse_runs.id"), nullable=True)
    security_key: Mapped[str] = mapped_column(String(120), nullable=False)
    current_cusip: Mapped[Optional[str]] = mapped_column(String(9), nullable=True)
    previous_cusip: Mapped[Optional[str]] = mapped_column(String(9), nullable=True)
    ssh_prnamt_type: Mapped[str] = mapped_column(String(10), nullable=False, default="SH", server_default="SH")
    put_call: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    position_type: Mapped[str] = mapped_column(String(20), nullable=False, default="common", server_default="common")
    change_status: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(40), nullable=False)
    is_primary_signal_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    caveat_codes: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    unavailable_reason: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    current_value_usd: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    previous_value_usd: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    value_delta_usd: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    value_delta_pct: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)
    current_shares: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    previous_shares: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    share_delta: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    share_change_pct: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)
    current_portfolio_weight_pct: Mapped[Optional[float]] = mapped_column(Numeric(12, 6), nullable=True)
    previous_portfolio_weight_pct: Mapped[Optional[float]] = mapped_column(Numeric(12, 6), nullable=True)
    mapping_confidence: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    attribution_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    has_confidential_treatment_caveat: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    has_combination_report_caveat: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    has_pending_amendment_caveat: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "uq_ownership_changes_manager_quarter_security_position",
            "manager_id",
            "report_quarter",
            "security_key",
            "ssh_prnamt_type",
            "position_type",
            unique=True,
        ),
        Index("idx_ownership_changes_stock_quarter", "stock_id", "report_quarter"),
        Index("idx_ownership_changes_manager_quarter", "manager_id", "report_quarter"),
        Index("idx_ownership_changes_change_status", "change_status"),
        Index("idx_ownership_changes_confidence", "confidence_level"),
        Index(
            "idx_ownership_changes_primary_signal",
            "stock_id",
            "report_quarter",
            postgresql_where=text("is_primary_signal_eligible = true"),
        ),
    )

    @validates("change_status")
    def _validate_change_status(self, _: str, value: str) -> str:
        return _validate_choice("change_status", value, OWNERSHIP_CHANGE_STATUSES)

    @validates("confidence_level")
    def _validate_confidence_level(self, _: str, value: str) -> str:
        return _validate_choice("confidence_level", value, OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS)

    @validates("position_type")
    def _validate_position_type(self, _: str, value: str) -> str:
        return _validate_choice("position_type", value, OWNERSHIP_POSITION_TYPES)


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        Index(
            "uq_job_runs_active_lock_key",
            "lock_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'cancel_requested')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    trigger_source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    sync_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    lock_key: Mapped[str] = mapped_column(String(200), nullable=False)
    quarter: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    lease_token: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    input_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    summary_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @validates("status")
    def _validate_status(self, _: str, value: str) -> str:
        return _validate_choice("status", value, JOB_RUN_STATUSES)


class JobWorkerHeartbeat(Base):
    __tablename__ = "job_worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    worker_type: Mapped[str] = mapped_column(String(60), nullable=False, default="13f_admin")
    hostname: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    process_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="idle")
    current_job_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("job_runs.id"), nullable=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QualityReport13F(Base):
    __tablename__ = "quality_reports_13f"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    quarter: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    info_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unavailable_reasons: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    issues_json: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_job_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("job_runs.id"), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QualityFinding13F(Base):
    __tablename__ = "quality_findings_13f"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    validation_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quality_reports_13f.id", ondelete="CASCADE"), nullable=False
    )
    rule_code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    quarter: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    manager_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("institution_managers.id"), nullable=True)
    accession_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @validates("severity")
    def _validate_severity(self, _: str, value: str) -> str:
        return _validate_choice("severity", value, QUALITY_FINDING_SEVERITIES)

    @validates("status")
    def _validate_finding_status(self, _: str, value: str) -> str:
        return _validate_choice("status", value, QUALITY_FINDING_STATUSES)


class CusipTickerMap(Base):
    __tablename__ = "cusip_ticker_map"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cusip: Mapped[str] = mapped_column(String(9), nullable=False)
    ticker: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    issuer_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    security_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    exchange: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    stock_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("stocks.id"), nullable=True)
    is_13f_reportable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    candidate_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mapping_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    effective_from_quarter: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    effective_to_quarter: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    evidence_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    mapping_status: Mapped[str] = mapped_column(String(30), nullable=False, default="needs_review", server_default="needs_review")
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("cusip", "valid_from", name="uq_cusip_ticker_map_cusip_valid_from"),
        UniqueConstraint("cusip", "source", "ticker", "exchange", "effective_from_quarter", name="uq_cusip_mapping"),
        Index(
            "idx_cusip_map_temporal",
            "cusip",
            "effective_from_quarter",
            "effective_to_quarter",
            postgresql_where=text("mapping_status IN ('confirmed', 'superseded')"),
        ),
    )

    @validates("mapping_status")
    def _validate_mapping_status(self, _: str, value: str) -> str:
        return _validate_choice("mapping_status", value, CUSIP_MAPPING_STATUSES)
