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
            "cik ~ '^[0-9]{10}$' AND octet_length(cik) = 10",
            name="ck_sec_issuer_identities_cik",
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


class SecSubmissionSnapshot(Base):
    __tablename__ = "sec_submission_snapshots"
    __table_args__ = (
        CheckConstraint(
            "byte_size >= 0",
            name="ck_sec_submission_snapshots_byte_size",
        ),
        CheckConstraint(
            "fetched_at <= known_at",
            name="ck_sec_submission_snapshots_knowledge_order",
        ),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_sec_submission_snapshots_sha256",
        ),
        CheckConstraint(
            "storage_key = 'financial/' || left(sha256, 2) || '/' || sha256",
            name="ck_sec_submission_snapshots_storage_key",
        ),
        UniqueConstraint(
            "issuer_identity_id",
            "source_url",
            "sha256",
            name="uq_sec_submission_snapshot_content",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issuer_identity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_issuer_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sec_financial_ingestion_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
        CheckConstraint(
            "(report_date IS NULL OR "
            "(report_date <= filed_on AND "
            "report_date <= (accepted_at AT TIME ZONE 'UTC')::date))",
            name="ck_sec_financial_filings_period_order",
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
        CheckConstraint(
            "(status = 'succeeded' AND fact_count > 0) OR "
            "(status = 'failed' AND fact_count = 0)",
            name="ck_sec_financial_parse_runs_fact_count",
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
    operation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("sec_financial_ingestion_operations.id", ondelete="RESTRICT"),
        nullable=True,
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
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )


class SecFinancialLegacyParseRun(Base):
    __tablename__ = "sec_financial_legacy_parse_runs"

    parse_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_parse_runs.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    marked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )


class SecFinancialIngestionOperation(Base):
    __tablename__ = "sec_financial_ingestion_operations"
    __table_args__ = (
        CheckConstraint(
            "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_sec_financial_ingestion_operations_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_identity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_issuer_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SecFinancialResourceAnchor(Base):
    """Canonical SEC resource attempted before any response bytes existed."""

    __tablename__ = "sec_financial_resource_anchors"
    __table_args__ = (
        CheckConstraint(
            "resource_role = 'main_submissions'",
            name="ck_sec_financial_resource_anchors_role",
        ),
        CheckConstraint(
            "char_length(resource_key) BETWEEN 1 AND 2048",
            name="ck_sec_financial_resource_anchors_resource_key",
        ),
        UniqueConstraint(
            "operation_id",
            name="uq_sec_financial_resource_anchors_operation",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sec_financial_ingestion_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    resource_role: Mapped[str] = mapped_column(String(48), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )


class SecFinancialLineageAvailability(Base):
    __tablename__ = "sec_financial_lineage_availabilities"

    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sec_financial_ingestion_operations.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        nullable=False,
    )
    finalized_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )


class SecFinancialOperationSnapshot(Base):
    __tablename__ = "sec_financial_operation_snapshots"

    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sec_financial_ingestion_operations.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_submission_snapshots.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )


class SecFinancialAcquisitionFailure(Base):
    __tablename__ = "sec_financial_acquisition_failures"
    __table_args__ = (
        CheckConstraint(
            "error_code ~ '^[a-z0-9_]{1,80}$'",
            name="ck_sec_financial_acquisition_failures_error_code",
        ),
        CheckConstraint(
            "stage IN ('submissions_fetch', 'submissions_parse', 'submissions_identity', "
            "'historical_submissions_fetch', 'historical_submissions_parse', "
            "'accession_index_fetch', 'filing_artifact_acquisition')",
            name="ck_sec_financial_acquisition_failures_stage",
        ),
        CheckConstraint(
            "accession_no IS NULL OR accession_no ~ "
            "'^[0-9]{10}-[0-9]{2}-[0-9]{6}$'",
            name="ck_sec_financial_acquisition_failures_accession",
        ),
        CheckConstraint(
            "resource_role IN ('main_submissions', 'historical_submissions', "
            "'accession_index', 'filing_artifact')",
            name="ck_sec_financial_acquisition_failures_resource_role",
        ),
        CheckConstraint(
            "char_length(resource_key) BETWEEN 1 AND 2048",
            name="ck_sec_financial_acquisition_failures_resource_key",
        ),
        CheckConstraint(
            "(submission_snapshot_id IS NOT NULL) <> (resource_anchor_id IS NOT NULL)",
            name="ck_sec_financial_acquisition_failures_source",
        ),
        CheckConstraint(
            "(stage = 'submissions_fetch') = (resource_anchor_id IS NOT NULL)",
            name="ck_sec_financial_acquisition_failures_source_stage",
        ),
        CheckConstraint(
            "(resource_role = 'main_submissions' AND accession_no IS NULL AND "
            "stage IN ('submissions_fetch', 'submissions_parse', "
            "'submissions_identity')) OR "
            "(resource_role = 'historical_submissions' AND accession_no IS NULL AND "
            "stage IN ('historical_submissions_fetch', "
            "'historical_submissions_parse')) OR "
            "(resource_role = 'accession_index' AND accession_no IS NOT NULL AND "
            "stage = 'accession_index_fetch') OR "
            "(resource_role = 'filing_artifact' AND accession_no IS NOT NULL AND "
            "stage = 'filing_artifact_acquisition')",
            name="ck_sec_financial_acquisition_failures_scope",
        ),
        UniqueConstraint(
            "operation_id",
            "resource_role",
            "resource_key",
            "stage",
            "error_code",
            "accession_no",
            name="uq_sec_financial_acquisition_failure",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sec_financial_ingestion_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    submission_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_submission_snapshots.id", ondelete="RESTRICT"),
        nullable=True,
    )
    resource_anchor_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_resource_anchors.id", ondelete="RESTRICT"),
        nullable=True,
    )
    stage: Mapped[str] = mapped_column(String(48), nullable=False)
    error_code: Mapped[str] = mapped_column(String(80), nullable=False)
    accession_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resource_role: Mapped[str] = mapped_column(String(48), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SecFinancialAccessionAttempt(Base):
    __tablename__ = "sec_financial_accession_attempts"
    __table_args__ = (
        CheckConstraint(
            "accession_no ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'",
            name="ck_sec_financial_accession_attempts_accession",
        ),
        CheckConstraint(
            "index_sha256 IS NULL OR index_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_sec_financial_accession_attempts_index_sha256",
        ),
        CheckConstraint(
            "input_manifest_hash IS NULL OR "
            "input_manifest_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sec_financial_accession_attempts_manifest_hash",
        ),
        CheckConstraint(
            "(outcome = 'acquisition_failed' AND acquisition_failure_id IS NOT NULL "
            "AND parse_run_id IS NULL AND index_sha256 IS NULL AND "
            "input_manifest_hash IS NULL) OR "
            "(outcome IN ('parse_succeeded', 'parse_failed', "
            "'parse_reused_succeeded', 'parse_reused_failed') AND "
            "acquisition_failure_id IS NULL AND parse_run_id IS NOT NULL AND "
            "index_sha256 IS NOT NULL AND input_manifest_hash IS NOT NULL)",
            name="ck_sec_financial_accession_attempts_shape",
        ),
        UniqueConstraint(
            "operation_id",
            "filing_id",
            name="uq_sec_financial_accession_attempt",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sec_financial_ingestion_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    filing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_filings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    accession_no: Mapped[str] = mapped_column(String(20), nullable=False)
    index_resource_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    index_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parse_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_parse_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    acquisition_failure_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_acquisition_failures.id", ondelete="RESTRICT"),
        nullable=True,
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )


class SecFinancialAccessionAttemptArtifact(Base):
    __tablename__ = "sec_financial_accession_attempt_artifacts"

    attempt_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_accession_attempts.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    artifact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sec_filing_artifacts.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )


class SecFinancialAcquisitionResolution(Base):
    __tablename__ = "sec_financial_acquisition_resolutions"
    __table_args__ = (
        CheckConstraint(
            "resource_role IN ('main_submissions', 'historical_submissions', "
            "'accession_terminal')",
            name="ck_sec_financial_acquisition_resolutions_resource_role",
        ),
        CheckConstraint(
            "char_length(resource_key) BETWEEN 1 AND 2048",
            name="ck_sec_financial_acquisition_resolutions_resource_key",
        ),
        CheckConstraint(
            "(resolution_kind = 'resource_validated' AND "
            "resource_role IN ('main_submissions', 'historical_submissions') AND "
            "submission_snapshot_id IS NOT NULL AND parse_run_id IS NULL AND "
            "accession_attempt_id IS NULL AND "
            "accession_no IS NULL) OR "
            "(resolution_kind IN ('parse_succeeded', 'parse_failed') AND "
            "resource_role = 'accession_terminal' AND "
            "submission_snapshot_id IS NULL AND parse_run_id IS NOT NULL AND "
            "accession_attempt_id IS NOT NULL AND "
            "accession_no IS NOT NULL)",
            name="ck_sec_financial_acquisition_resolutions_shape",
        ),
        CheckConstraint(
            "accession_no IS NULL OR accession_no ~ "
            "'^[0-9]{10}-[0-9]{2}-[0-9]{6}$'",
            name="ck_sec_financial_acquisition_resolutions_accession",
        ),
        UniqueConstraint(
            "operation_id",
            "resource_role",
            "resource_key",
            name="uq_sec_financial_acquisition_resolution",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sec_financial_ingestion_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    resource_role: Mapped[str] = mapped_column(String(48), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    resolution_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    submission_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_submission_snapshots.id", ondelete="RESTRICT"),
        nullable=True,
    )
    parse_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_parse_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    accession_attempt_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_accession_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    accession_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SecFinancialOperationResult(Base):
    __tablename__ = "sec_financial_operation_results"
    __table_args__ = (
        CheckConstraint(
            "(result_kind = 'parse_run' AND parse_run_id IS NOT NULL "
            "AND acquisition_failure_id IS NULL) OR "
            "(result_kind = 'acquisition_failure' AND parse_run_id IS NULL "
            "AND acquisition_failure_id IS NOT NULL) OR "
            "(result_kind = 'no_eligible_filings' AND parse_run_id IS NULL "
            "AND acquisition_failure_id IS NULL)",
            name="ck_sec_financial_operation_results_shape",
        ),
    )

    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sec_financial_ingestion_operations.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    result_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    parse_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_parse_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    acquisition_failure_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sec_financial_acquisition_failures.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )
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
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
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
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )
