from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class SecIssuerIdentity(Base):
    __tablename__ = "sec_issuer_identities"
    __table_args__ = (
        CheckConstraint(
            "status IN ('reviewed', 'needs_review', 'retired')",
            name="ck_sec_issuer_identities_status",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_sec_issuer_identities_interval",
        ),
        CheckConstraint(
            "status = 'needs_review' OR length(btrim(review_reason)) > 0",
            name="ck_sec_issuer_identities_review_reason",
        ),
        UniqueConstraint(
            "stock_id",
            "cik",
            "effective_from",
            "known_at",
            name="uq_sec_issuer_identity_decision",
        ),
        UniqueConstraint(
            "supersedes_identity_id",
            name="uq_sec_issuer_identity_single_supersession",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False
    )
    cik: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewer_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    supersedes_identity_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_issuer_identities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SecFinancialFiling(Base):
    __tablename__ = "sec_financial_filings"
    __table_args__ = (
        CheckConstraint(
            "form_type IN ('10-K', '10-K/A', '10-Q', '10-Q/A', '20-F', '20-F/A', '6-K')",
            name="ck_sec_financial_filings_form",
        ),
        CheckConstraint(
            "is_amendment = (right(form_type, 2) = '/A')",
            name="ck_sec_financial_filings_amendment_flag",
        ),
        UniqueConstraint("accession_no", name="uq_sec_financial_filings_accession"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issuer_identity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_issuer_identities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    accession_no: Mapped[str] = mapped_column(String(20), nullable=False)
    form_type: Mapped[str] = mapped_column(String(12), nullable=False)
    is_amendment: Mapped[bool] = mapped_column(Boolean, nullable=False)
    filed_on: Mapped[date] = mapped_column(Date, nullable=False)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    primary_document: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_doc_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    submissions_source_url: Mapped[str] = mapped_column(Text, nullable=False)
    discovery_payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    amends_filing_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_filings.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SecFilingArtifact(Base):
    __tablename__ = "sec_filing_artifacts"
    __table_args__ = (
        CheckConstraint(
            "state IN ('manifest_only', 'retained', 'unavailable', 'rejected')",
            name="ck_sec_filing_artifacts_state",
        ),
        CheckConstraint(
            "(state = 'retained' AND sha256 IS NOT NULL AND byte_size IS NOT NULL "
            "AND storage_key IS NOT NULL AND fetched_at IS NOT NULL) OR "
            "(state <> 'retained' AND storage_key IS NULL)",
            name="ck_sec_filing_artifacts_retained_shape",
        ),
        UniqueConstraint(
            "filing_id",
            "filename",
            "manifest_hash",
            "state",
            name="uq_sec_filing_artifact_observation",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_filings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sec_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    declared_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    content_mime: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    http_etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SecFinancialParseRun(Base):
    __tablename__ = "sec_financial_parse_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_sec_financial_parse_runs_status",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND error_code IS NULL) OR "
            "(status = 'failed' AND error_code IS NOT NULL)",
            name="ck_sec_financial_parse_runs_result",
        ),
        UniqueConstraint(
            "filing_id",
            "parser_version",
            "input_manifest_hash",
            name="uq_sec_financial_parse_run_input",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_filings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    input_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SecFinancialParseRunArtifact(Base):
    __tablename__ = "sec_financial_parse_run_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "parse_run_id", "artifact_id", name="uq_sec_financial_parse_run_artifact"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parse_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_parse_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    artifact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_filing_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SecRawXbrlFact(Base):
    __tablename__ = "sec_raw_xbrl_facts"
    __table_args__ = (
        UniqueConstraint(
            "parse_run_id", "ordinal", name="uq_sec_raw_xbrl_fact_ordinal"
        ),
        ForeignKeyConstraint(
            ["parse_run_id", "artifact_id"],
            [
                "sec_financial_parse_run_artifacts.parse_run_id",
                "sec_financial_parse_run_artifacts.artifact_id",
            ],
            name="fk_sec_raw_xbrl_fact_exact_input",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parse_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_parse_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    artifact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_filing_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    concept: Mapped[str] = mapped_column(Text, nullable=False)
    concept_namespace_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_measure: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    transformation_format: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(80), nullable=True)
    continued_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    decimals: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scale: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sign: Mapped[str | None] = mapped_column(String(4), nullable=True)
    is_nil: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    period_instant: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    entity_identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimensions_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    locator_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
