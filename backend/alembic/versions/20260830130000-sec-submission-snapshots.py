"""Separate issuer submissions snapshots from filing parse inputs.

Revision ID: 20260830130000
Revises: 20260830120000
Create Date: 2026-08-30 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260830130000"
down_revision = "20260830120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    invalid_cik_count = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM sec_issuer_identities "
            "WHERE cik !~ '^[0-9]{10}$' OR octet_length(cik) <> 10"
        )
    ).scalar_one()
    if invalid_cik_count:
        raise RuntimeError(
            "existing SEC issuer identity CIK is not exactly 10 ASCII digits"
        )
    op.create_check_constraint(
        "ck_sec_issuer_identities_cik",
        "sec_issuer_identities",
        "cik ~ '^[0-9]{10}$' AND octet_length(cik) = 10",
    )
    op.create_table(
        "sec_financial_ingestion_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("issuer_identity_id", sa.BigInteger(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_txid",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_sec_financial_ingestion_operations_id",
        ),
        sa.ForeignKeyConstraint(
            ["issuer_identity_id"],
            ["sec_issuer_identities.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sec_financial_lineage_availabilities",
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "finalized_txid",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["sec_financial_ingestion_operations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_table(
        "sec_submission_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("issuer_identity_id", sa.BigInteger(), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "byte_size >= 0",
            name="ck_sec_submission_snapshots_byte_size",
        ),
        sa.CheckConstraint(
            "fetched_at <= known_at",
            name="ck_sec_submission_snapshots_knowledge_order",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_sec_submission_snapshots_sha256",
        ),
        sa.CheckConstraint(
            "storage_key = 'financial/' || left(sha256, 2) || '/' || sha256",
            name="ck_sec_submission_snapshots_storage_key",
        ),
        sa.ForeignKeyConstraint(
            ["issuer_identity_id"],
            ["sec_issuer_identities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["sec_financial_ingestion_operations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "issuer_identity_id",
            "source_url",
            "sha256",
            name="uq_sec_submission_snapshot_content",
        ),
    )
    op.create_index(
        "ix_sec_submission_snapshots_identity_known",
        "sec_submission_snapshots",
        ["issuer_identity_id", "known_at"],
    )
    op.create_table(
        "sec_financial_operation_snapshots",
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_txid",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["sec_financial_ingestion_operations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["sec_submission_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("operation_id", "snapshot_id"),
    )
    op.create_table(
        "sec_financial_resource_anchors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("resource_role", sa.String(length=48), nullable=False),
        sa.Column("resource_key", sa.String(length=2048), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_txid",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "resource_role = 'main_submissions'",
            name="ck_sec_financial_resource_anchors_role",
        ),
        sa.CheckConstraint(
            "char_length(resource_key) BETWEEN 1 AND 2048",
            name="ck_sec_financial_resource_anchors_resource_key",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["sec_financial_ingestion_operations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id",
            name="uq_sec_financial_resource_anchors_operation",
        ),
    )
    op.add_column(
        "sec_financial_parse_runs",
        sa.Column("operation_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_sec_financial_parse_runs_operation",
        "sec_financial_parse_runs",
        "sec_financial_ingestion_operations",
        ["operation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_sec_financial_parse_runs_operation",
        "sec_financial_parse_runs",
        ["operation_id"],
    )
    op.create_table(
        "sec_financial_legacy_parse_runs",
        sa.Column("parse_run_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "marked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parse_run_id"],
            ["sec_financial_parse_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("parse_run_id"),
    )
    op.execute(
        "INSERT INTO sec_financial_legacy_parse_runs (parse_run_id) "
        "SELECT id FROM sec_financial_parse_runs WHERE operation_id IS NULL"
    )
    unmarked_legacy_count = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM sec_financial_parse_runs run "
            "WHERE run.operation_id IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM sec_financial_legacy_parse_runs legacy "
            "WHERE legacy.parse_run_id = run.id)"
        )
    ).scalar_one()
    if unmarked_legacy_count:
        raise RuntimeError("preexisting NULL-operation parse run was not allowlisted")
    op.execute(
        "CREATE TRIGGER trg_sec_financial_legacy_parse_runs_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON sec_financial_legacy_parse_runs "
        "FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation()"
    )
    op.create_table(
        "sec_financial_acquisition_failures",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("submission_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("resource_anchor_id", sa.BigInteger(), nullable=True),
        sa.Column("stage", sa.String(length=48), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=False),
        sa.Column("accession_no", sa.String(length=20), nullable=True),
        sa.Column("resource_role", sa.String(length=48), nullable=False),
        sa.Column("resource_key", sa.String(length=2048), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "error_code ~ '^[a-z0-9_]{1,80}$'",
            name="ck_sec_financial_acquisition_failures_error_code",
        ),
        sa.CheckConstraint(
            "stage IN ('submissions_fetch', 'submissions_parse', 'submissions_identity', "
            "'historical_submissions_fetch', 'historical_submissions_parse', "
            "'accession_index_fetch', 'filing_artifact_acquisition')",
            name="ck_sec_financial_acquisition_failures_stage",
        ),
        sa.CheckConstraint(
            "accession_no IS NULL OR accession_no ~ "
            "'^[0-9]{10}-[0-9]{2}-[0-9]{6}$'",
            name="ck_sec_financial_acquisition_failures_accession",
        ),
        sa.CheckConstraint(
            "resource_role IN ('main_submissions', 'historical_submissions', "
            "'accession_index', 'filing_artifact')",
            name="ck_sec_financial_acquisition_failures_resource_role",
        ),
        sa.CheckConstraint(
            "char_length(resource_key) BETWEEN 1 AND 2048",
            name="ck_sec_financial_acquisition_failures_resource_key",
        ),
        sa.CheckConstraint(
            "(submission_snapshot_id IS NOT NULL) <> (resource_anchor_id IS NOT NULL)",
            name="ck_sec_financial_acquisition_failures_source",
        ),
        sa.CheckConstraint(
            "(stage = 'submissions_fetch') = (resource_anchor_id IS NOT NULL)",
            name="ck_sec_financial_acquisition_failures_source_stage",
        ),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["sec_financial_ingestion_operations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submission_snapshot_id"],
            ["sec_submission_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_anchor_id"],
            ["sec_financial_resource_anchors.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id",
            "resource_role",
            "resource_key",
            "stage",
            "error_code",
            "accession_no",
            name="uq_sec_financial_acquisition_failure",
        ),
    )
    op.create_table(
        "sec_financial_accession_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("filing_id", sa.BigInteger(), nullable=False),
        sa.Column("accession_no", sa.String(length=20), nullable=False),
        sa.Column("index_resource_key", sa.String(length=2048), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("index_sha256", sa.String(length=64), nullable=True),
        sa.Column("input_manifest_hash", sa.String(length=64), nullable=True),
        sa.Column("parse_run_id", sa.BigInteger(), nullable=True),
        sa.Column("acquisition_failure_id", sa.BigInteger(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), server_default=sa.text("txid_current()"), nullable=False),
        sa.CheckConstraint(
            "accession_no ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'",
            name="ck_sec_financial_accession_attempts_accession",
        ),
        sa.CheckConstraint(
            "index_sha256 IS NULL OR index_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_sec_financial_accession_attempts_index_sha256",
        ),
        sa.CheckConstraint(
            "input_manifest_hash IS NULL OR input_manifest_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sec_financial_accession_attempts_manifest_hash",
        ),
        sa.CheckConstraint(
            "(outcome = 'acquisition_failed' AND acquisition_failure_id IS NOT NULL "
            "AND parse_run_id IS NULL AND index_sha256 IS NULL AND "
            "input_manifest_hash IS NULL) OR "
            "(outcome IN ('parse_succeeded', 'parse_failed', "
            "'parse_reused_succeeded', 'parse_reused_failed') AND "
            "acquisition_failure_id IS NULL AND parse_run_id IS NOT NULL AND "
            "index_sha256 IS NOT NULL AND input_manifest_hash IS NOT NULL)",
            name="ck_sec_financial_accession_attempts_shape",
        ),
        sa.ForeignKeyConstraint(["operation_id"], ["sec_financial_ingestion_operations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["filing_id"], ["sec_financial_filings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parse_run_id"], ["sec_financial_parse_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["acquisition_failure_id"], ["sec_financial_acquisition_failures.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", "filing_id", name="uq_sec_financial_accession_attempt"),
    )
    op.create_table(
        "sec_financial_accession_attempt_artifacts",
        sa.Column("attempt_id", sa.BigInteger(), nullable=False),
        sa.Column("artifact_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), server_default=sa.text("txid_current()"), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["sec_financial_accession_attempts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["artifact_id"], ["sec_filing_artifacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("attempt_id", "artifact_id"),
    )
    op.create_table(
        "sec_financial_acquisition_resolutions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("resource_role", sa.String(length=48), nullable=False),
        sa.Column("resource_key", sa.String(length=2048), nullable=False),
        sa.Column("resolution_kind", sa.String(length=32), nullable=False),
        sa.Column("submission_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("parse_run_id", sa.BigInteger(), nullable=True),
        sa.Column("accession_attempt_id", sa.BigInteger(), nullable=True),
        sa.Column("accession_no", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "resource_role IN ('main_submissions', 'historical_submissions', "
            "'accession_terminal')",
            name="ck_sec_financial_acquisition_resolutions_resource_role",
        ),
        sa.CheckConstraint(
            "char_length(resource_key) BETWEEN 1 AND 2048",
            name="ck_sec_financial_acquisition_resolutions_resource_key",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "accession_no IS NULL OR accession_no ~ "
            "'^[0-9]{10}-[0-9]{2}-[0-9]{6}$'",
            name="ck_sec_financial_acquisition_resolutions_accession",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["sec_financial_ingestion_operations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submission_snapshot_id"],
            ["sec_submission_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parse_run_id"],
            ["sec_financial_parse_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["accession_attempt_id"],
            ["sec_financial_accession_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id",
            "resource_role",
            "resource_key",
            name="uq_sec_financial_acquisition_resolution",
        ),
    )
    op.create_table(
        "sec_financial_operation_results",
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("result_kind", sa.String(length=40), nullable=False),
        sa.Column("parse_run_id", sa.BigInteger(), nullable=True),
        sa.Column("acquisition_failure_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_txid",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(result_kind = 'parse_run' AND parse_run_id IS NOT NULL "
            "AND acquisition_failure_id IS NULL) OR "
            "(result_kind = 'acquisition_failure' AND parse_run_id IS NULL "
            "AND acquisition_failure_id IS NOT NULL) OR "
            "(result_kind = 'no_eligible_filings' AND parse_run_id IS NULL "
            "AND acquisition_failure_id IS NULL)",
            name="ck_sec_financial_operation_results_shape",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["sec_financial_ingestion_operations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parse_run_id"],
            ["sec_financial_parse_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_failure_id"],
            ["sec_financial_acquisition_failures.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    invalid_operation_ownership_count = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM ("
            "SELECT snapshot.id FROM sec_submission_snapshots snapshot "
            "JOIN sec_financial_ingestion_operations operation "
            "ON operation.id = snapshot.operation_id "
            "WHERE snapshot.issuer_identity_id <> operation.issuer_identity_id "
            "UNION ALL "
            "SELECT run.id FROM sec_financial_parse_runs run "
            "JOIN sec_financial_filings filing ON filing.id = run.filing_id "
            "JOIN sec_financial_ingestion_operations operation "
            "ON operation.id = run.operation_id "
            "WHERE run.operation_id IS NOT NULL "
            "AND filing.issuer_identity_id <> operation.issuer_identity_id "
            "UNION ALL "
            "SELECT failure.id FROM sec_financial_acquisition_failures failure "
            "JOIN sec_submission_snapshots snapshot "
            "ON snapshot.id = failure.submission_snapshot_id "
            "JOIN sec_financial_ingestion_operations operation "
            "ON operation.id = failure.operation_id "
            "WHERE operation.issuer_identity_id <> snapshot.issuer_identity_id "
            "OR NOT EXISTS (SELECT 1 FROM sec_financial_operation_snapshots link "
            "WHERE link.operation_id = failure.operation_id "
            "AND link.snapshot_id = failure.submission_snapshot_id)"
            ") invalid_ownership"
        )
    ).scalar_one()
    if invalid_operation_ownership_count:
        raise RuntimeError("existing SEC operation lineage ownership is invalid")
    invalid_artifact_url_count = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM sec_filing_artifacts artifact "
            "JOIN sec_financial_filings filing ON filing.id = artifact.filing_id "
            "JOIN sec_issuer_identities identity ON identity.id = filing.issuer_identity_id "
            "WHERE artifact.source_url IS NOT NULL AND NOT ("
            "artifact.filename = '__submissions__.json' AND EXISTS ("
            "SELECT 1 FROM sec_financial_parse_run_artifacts link "
            "JOIN sec_financial_legacy_parse_runs legacy "
            "ON legacy.parse_run_id = link.parse_run_id "
            "WHERE link.artifact_id = artifact.id)) AND ("
            "(artifact.filename <> '__accession_index__.json' AND ("
            "artifact.filename !~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$' "
            "OR strpos(artifact.filename, '..') > 0)) OR "
            "artifact.source_url <> ('https://www.sec.gov/Archives/edgar/data/' || "
            "identity.cik::bigint::text || '/' || replace(filing.accession_no, '-', '') || '/' || "
            "CASE WHEN artifact.filename = '__accession_index__.json' "
            "THEN 'index.json' ELSE artifact.filename END))"
        )
    ).scalar_one()
    if invalid_artifact_url_count:
        raise RuntimeError("existing SEC filing artifact URL is not canonical")
    op.execute(
        """
        CREATE FUNCTION guard_sec_filing_artifact_source_url_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            expected_url text;
            filing_accession text;
            identity_cik text;
        BEGIN
            SELECT filing.accession_no, identity.cik
            INTO filing_accession, identity_cik
            FROM sec_financial_filings filing
            JOIN sec_issuer_identities identity
              ON identity.id = filing.issuer_identity_id
            WHERE filing.id = NEW.filing_id;
            IF filing_accession IS NULL THEN
                RAISE EXCEPTION 'artifact requires known filing identity';
            END IF;
            IF NEW.source_url IS NOT NULL THEN
                IF NEW.filename <> '__accession_index__.json' AND (
                    NEW.filename !~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$'
                    OR strpos(NEW.filename, '..') > 0
                ) THEN
                    RAISE EXCEPTION 'artifact source URL requires strict safe filename';
                END IF;
                expected_url := 'https://www.sec.gov/Archives/edgar/data/' ||
                    identity_cik::bigint::text || '/' ||
                    replace(filing_accession, '-', '') || '/' ||
                    CASE WHEN NEW.filename = '__accession_index__.json'
                         THEN 'index.json' ELSE NEW.filename END;
                IF NEW.source_url <> expected_url THEN
                    RAISE EXCEPTION 'artifact source URL is not canonical SEC Archives URL';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_sec_filing_artifacts_source_url_insert_guard "
        "BEFORE INSERT ON sec_filing_artifacts FOR EACH ROW "
        "EXECUTE FUNCTION guard_sec_filing_artifact_source_url_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_financial_operation_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            operation_identity sec_issuer_identities%ROWTYPE;
        BEGIN
            NEW.created_at := clock_timestamp();
            NEW.created_txid := txid_current();
            SELECT * INTO operation_identity
            FROM sec_issuer_identities
            WHERE id = NEW.issuer_identity_id;
            IF operation_identity.id IS NULL THEN
                RAISE EXCEPTION 'operation requires reviewed SEC issuer identity';
            END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended('sec-issuer-cik:' || operation_identity.cik, 0)
            );
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    'sec-issuer-stock:' || operation_identity.stock_id::text, 0
                )
            );
            SELECT * INTO operation_identity
            FROM sec_issuer_identities
            WHERE id = NEW.issuer_identity_id
            FOR SHARE;
            IF operation_identity.status <> 'reviewed'
               OR operation_identity.known_at > NEW.attempted_at
               OR EXISTS (
                   SELECT 1 FROM sec_issuer_identities child
                   WHERE child.supersedes_identity_id = operation_identity.id
                     AND child.known_at <= NEW.attempted_at
               ) THEN
                RAISE EXCEPTION 'operation requires current reviewed SEC issuer identity';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_financial_ingestion_operations_insert_guard
        BEFORE INSERT ON sec_financial_ingestion_operations
        FOR EACH ROW EXECUTE FUNCTION guard_sec_financial_operation_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_financial_operation_snapshot_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            operation_identity_id bigint;
            snapshot_identity_id bigint;
        BEGIN
            NEW.created_txid := txid_current();
            SELECT issuer_identity_id
            INTO operation_identity_id
            FROM sec_financial_ingestion_operations
            WHERE id = NEW.operation_id
            FOR UPDATE;
            SELECT issuer_identity_id INTO snapshot_identity_id
            FROM sec_submission_snapshots
            WHERE id = NEW.snapshot_id;
            IF operation_identity_id IS NULL
               OR snapshot_identity_id IS NULL
               OR operation_identity_id <> snapshot_identity_id
               OR EXISTS (
                   SELECT 1 FROM sec_financial_lineage_availabilities
                   WHERE operation_id = NEW.operation_id
               ) THEN
                RAISE EXCEPTION 'invalid or sealed SEC operation snapshot link';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_financial_operation_snapshots_insert_guard
        BEFORE INSERT ON sec_financial_operation_snapshots
        FOR EACH ROW EXECUTE FUNCTION guard_sec_financial_operation_snapshot_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_financial_resource_anchor_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            operation_cik text;
        BEGIN
            NEW.created_at := clock_timestamp();
            NEW.created_txid := txid_current();
            SELECT identity.cik INTO operation_cik
            FROM sec_financial_ingestion_operations operation
            JOIN sec_issuer_identities identity
              ON identity.id = operation.issuer_identity_id
            WHERE operation.id = NEW.operation_id
            FOR UPDATE OF operation;
            IF operation_cik IS NULL
               OR NEW.resource_role <> 'main_submissions'
               OR NEW.resource_key <> (
                   'https://data.sec.gov/submissions/CIK' || operation_cik || '.json'
               )
               OR EXISTS (
                   SELECT 1 FROM sec_financial_lineage_availabilities
                   WHERE operation_id = NEW.operation_id
               ) THEN
                RAISE EXCEPTION 'resource anchor requires exact main resource and unsealed operation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_financial_resource_anchors_insert_guard
        BEFORE INSERT ON sec_financial_resource_anchors
        FOR EACH ROW EXECUTE FUNCTION guard_sec_financial_resource_anchor_insert()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION stamp_sec_financial_parse_run_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            operation_identity_id bigint;
            filing_identity_id bigint;
        BEGIN
            NEW.created_at := clock_timestamp();
            NEW.created_txid := txid_current();
            IF NEW.operation_id IS NULL THEN
                RAISE EXCEPTION 'new parse run requires explicit ingestion operation';
            END IF;
            SELECT issuer_identity_id
            INTO operation_identity_id
            FROM sec_financial_ingestion_operations
            WHERE id = NEW.operation_id
            FOR UPDATE;
            SELECT issuer_identity_id INTO filing_identity_id
            FROM sec_financial_filings
            WHERE id = NEW.filing_id;
            IF operation_identity_id IS NULL
               OR filing_identity_id IS NULL
               OR operation_identity_id <> filing_identity_id
               OR EXISTS (
                   SELECT 1 FROM sec_financial_lineage_availabilities
                   WHERE operation_id = NEW.operation_id
               ) THEN
                RAISE EXCEPTION 'parse run requires matching unsealed SEC operation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_financial_acquisition_failure_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            operation_identity_id bigint;
            operation_cik text;
            snapshot_identity_id bigint;
            anchor_operation_id text;
            anchor_resource_role text;
            anchor_resource_key text;
        BEGIN
            SELECT operation.issuer_identity_id, identity.cik
            INTO operation_identity_id, operation_cik
            FROM sec_financial_ingestion_operations operation
            JOIN sec_issuer_identities identity
              ON identity.id = operation.issuer_identity_id
            WHERE operation.id = NEW.operation_id
            FOR UPDATE;
            SELECT issuer_identity_id
            INTO snapshot_identity_id
            FROM sec_submission_snapshots
            WHERE id = NEW.submission_snapshot_id;
            IF operation_identity_id IS NULL
               OR EXISTS (
                   SELECT 1 FROM sec_financial_lineage_availabilities
                   WHERE operation_id = NEW.operation_id
               ) THEN
                RAISE EXCEPTION 'acquisition failure requires an unsealed operation';
            END IF;
            IF NEW.submission_snapshot_id IS NOT NULL THEN
                IF snapshot_identity_id IS NULL
                   OR operation_identity_id <> snapshot_identity_id
                   OR NOT EXISTS (
                       SELECT 1 FROM sec_financial_operation_snapshots link
                       WHERE link.operation_id = NEW.operation_id
                         AND link.snapshot_id = NEW.submission_snapshot_id
                   ) THEN
                    RAISE EXCEPTION 'acquisition failure requires an operation-linked snapshot';
                END IF;
            ELSE
                SELECT operation_id, resource_role, resource_key
                INTO anchor_operation_id, anchor_resource_role, anchor_resource_key
                FROM sec_financial_resource_anchors
                WHERE id = NEW.resource_anchor_id;
                IF anchor_operation_id IS DISTINCT FROM NEW.operation_id
                   OR anchor_resource_role IS DISTINCT FROM NEW.resource_role
                   OR anchor_resource_key IS DISTINCT FROM NEW.resource_key
                   OR NEW.stage <> 'submissions_fetch' THEN
                    RAISE EXCEPTION 'acquisition failure requires its exact no-bytes resource anchor';
                END IF;
            END IF;
            IF (NEW.resource_role = 'main_submissions' AND
                    NEW.resource_key <> (
                        'https://data.sec.gov/submissions/CIK' ||
                        operation_cik || '.json'))
               OR (NEW.resource_role = 'historical_submissions' AND
                    NEW.resource_key !~ ('^https://data[.]sec[.]gov/submissions/CIK' ||
                        operation_cik || '-submissions-[0-9]+[.]json$'))
               OR (NEW.resource_role = 'accession_index' AND NOT EXISTS (
                    SELECT 1 FROM sec_financial_filings filing
                    WHERE filing.issuer_identity_id = operation_identity_id
                      AND filing.accession_no = NEW.accession_no
                      AND filing.index_url = NEW.resource_key
               ))
               OR (NEW.resource_role = 'filing_artifact' AND NOT (
                    EXISTS (
                        SELECT 1
                        FROM sec_filing_artifacts artifact
                        JOIN sec_financial_filings filing
                          ON filing.id = artifact.filing_id
                        WHERE filing.issuer_identity_id = operation_identity_id
                          AND filing.accession_no = NEW.accession_no
                          AND artifact.source_url = NEW.resource_key
                          AND artifact.state IN ('unavailable', 'rejected')
                          AND artifact.reason_code = NEW.error_code
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM sec_filing_artifacts artifact
                        JOIN sec_financial_filings filing
                          ON filing.id = artifact.filing_id
                        WHERE filing.issuer_identity_id = operation_identity_id
                          AND filing.accession_no = NEW.accession_no
                          AND artifact.source_url IS NULL
                          AND artifact.state IN ('unavailable', 'rejected')
                          AND artifact.reason_code = NEW.error_code
                          AND NEW.resource_key = (
                              'urn:valuepilot:sec-filing-artifact:' ||
                              NEW.accession_no || ':sha256:' ||
                              encode(sha256(convert_to(artifact.filename, 'UTF8')), 'hex')
                          )
                    )
               )) THEN
                RAISE EXCEPTION 'acquisition failure requires exact failed artifact observation';
            END IF;
            NEW.created_at := clock_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_financial_acquisition_failures_insert_guard
        BEFORE INSERT ON sec_financial_acquisition_failures
        FOR EACH ROW EXECUTE FUNCTION guard_sec_financial_acquisition_failure_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_financial_accession_attempt_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            operation_identity_id bigint;
            filing_identity_id bigint;
            filing_accession text;
            filing_index_url text;
            run_operation_id text;
            run_status text;
            run_filing_id bigint;
            failure_operation_id text;
            failure_accession text;
            failure_resource_role text;
            failure_resource_key text;
        BEGIN
            SELECT issuer_identity_id INTO operation_identity_id
            FROM sec_financial_ingestion_operations
            WHERE id = NEW.operation_id FOR UPDATE;
            SELECT issuer_identity_id, accession_no, index_url
            INTO filing_identity_id, filing_accession, filing_index_url
            FROM sec_financial_filings WHERE id = NEW.filing_id;
            IF operation_identity_id IS NULL
               OR filing_identity_id IS DISTINCT FROM operation_identity_id
               OR filing_accession IS DISTINCT FROM NEW.accession_no
               OR filing_index_url IS DISTINCT FROM NEW.index_resource_key
               OR EXISTS (
                   SELECT 1 FROM sec_financial_lineage_availabilities
                   WHERE operation_id = NEW.operation_id
               ) THEN
                RAISE EXCEPTION 'accession attempt requires matching unsealed operation and filing';
            END IF;
            IF NEW.outcome = 'acquisition_failed' THEN
                SELECT operation_id, accession_no, resource_role, resource_key
                INTO failure_operation_id, failure_accession,
                     failure_resource_role, failure_resource_key
                FROM sec_financial_acquisition_failures
                WHERE id = NEW.acquisition_failure_id;
                IF failure_operation_id IS DISTINCT FROM NEW.operation_id
                   OR failure_accession IS DISTINCT FROM NEW.accession_no
                   OR failure_resource_role <> 'accession_index'
                   OR failure_resource_key IS DISTINCT FROM NEW.index_resource_key THEN
                    RAISE EXCEPTION 'failed accession attempt requires its exact index failure';
                END IF;
            ELSE
                SELECT operation_id, status, filing_id
                INTO run_operation_id, run_status, run_filing_id
                FROM sec_financial_parse_runs WHERE id = NEW.parse_run_id;
                IF run_filing_id IS DISTINCT FROM NEW.filing_id
                   OR run_status IS DISTINCT FROM (CASE
                       WHEN NEW.outcome IN ('parse_succeeded', 'parse_reused_succeeded')
                           THEN 'succeeded'
                       ELSE 'failed'
                   END)
                   OR (
                       NEW.outcome IN ('parse_succeeded', 'parse_failed')
                       AND run_operation_id IS DISTINCT FROM NEW.operation_id
                   )
                   OR (
                       NEW.outcome IN ('parse_reused_succeeded', 'parse_reused_failed')
                       AND run_operation_id IS NOT DISTINCT FROM NEW.operation_id
                   )
                   OR (
                       NEW.outcome IN ('parse_reused_succeeded', 'parse_reused_failed')
                       AND run_operation_id IS NOT NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM sec_financial_lineage_availabilities
                           WHERE operation_id = run_operation_id
                       )
                   )
                   OR (
                       NEW.outcome IN ('parse_reused_succeeded', 'parse_reused_failed')
                       AND run_operation_id IS NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM sec_financial_legacy_parse_runs
                           WHERE parse_run_id = NEW.parse_run_id
                       )
                   ) THEN
                    RAISE EXCEPTION 'parse accession attempt requires owned or replayable exact run';
                END IF;
            END IF;
            NEW.attempted_at := clock_timestamp();
            NEW.created_at := NEW.attempted_at;
            NEW.created_txid := txid_current();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_sec_financial_accession_attempts_insert_guard "
        "BEFORE INSERT ON sec_financial_accession_attempts FOR EACH ROW "
        "EXECUTE FUNCTION guard_sec_financial_accession_attempt_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_financial_accession_attempt_artifact_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            attempt_operation_id text;
            attempt_filing_id bigint;
            attempt_txid bigint;
            artifact_filing_id bigint;
            artifact_state text;
        BEGIN
            SELECT attempt.operation_id, attempt.filing_id, attempt.created_txid
            INTO attempt_operation_id, attempt_filing_id, attempt_txid
            FROM sec_financial_accession_attempts attempt
            JOIN sec_financial_ingestion_operations operation
              ON operation.id = attempt.operation_id
            WHERE attempt.id = NEW.attempt_id
            FOR UPDATE OF operation;
            SELECT filing_id, state
            INTO artifact_filing_id, artifact_state
            FROM sec_filing_artifacts WHERE id = NEW.artifact_id;
            IF attempt_operation_id IS NULL
               OR attempt_filing_id IS DISTINCT FROM artifact_filing_id
               OR artifact_state <> 'retained'
               OR attempt_txid <> txid_current()
               OR EXISTS (
                   SELECT 1 FROM sec_financial_lineage_availabilities
                   WHERE operation_id = attempt_operation_id
               ) THEN
                RAISE EXCEPTION 'attempt artifact requires same-transaction retained filing input';
            END IF;
            NEW.created_at := clock_timestamp();
            NEW.created_txid := txid_current();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_sec_financial_accession_attempt_artifacts_insert_guard "
        "BEFORE INSERT ON sec_financial_accession_attempt_artifacts FOR EACH ROW "
        "EXECUTE FUNCTION guard_sec_financial_accession_attempt_artifact_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_financial_acquisition_resolution_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            operation_identity_id bigint;
            referenced_identity_id bigint;
            referenced_source_url text;
            referenced_accession text;
            referenced_status text;
            attempt_operation_id text;
            attempt_parse_run_id bigint;
            attempt_accession text;
            attempt_outcome text;
            attempt_manifest_hash text;
            run_manifest_hash text;
        BEGIN
            SELECT issuer_identity_id
            INTO operation_identity_id
            FROM sec_financial_ingestion_operations
            WHERE id = NEW.operation_id
            FOR UPDATE;
            IF operation_identity_id IS NULL OR EXISTS (
                SELECT 1 FROM sec_financial_lineage_availabilities
                WHERE operation_id = NEW.operation_id
            ) THEN
                RAISE EXCEPTION 'acquisition resolution requires an unsealed operation';
            END IF;
            IF NEW.resolution_kind = 'resource_validated' THEN
                SELECT snapshot.issuer_identity_id, snapshot.source_url
                INTO referenced_identity_id, referenced_source_url
                FROM sec_submission_snapshots snapshot
                JOIN sec_financial_operation_snapshots link
                  ON link.snapshot_id = snapshot.id
                 AND link.operation_id = NEW.operation_id
                WHERE snapshot.id = NEW.submission_snapshot_id;
                IF referenced_identity_id IS NULL
                   OR referenced_identity_id <> operation_identity_id
                   OR referenced_source_url <> NEW.resource_key THEN
                    RAISE EXCEPTION 'resource resolution requires its exact operation-linked snapshot';
                END IF;
            ELSE
                SELECT filing.issuer_identity_id, filing.accession_no, run.status,
                       attempt.operation_id, attempt.parse_run_id,
                       attempt.accession_no, attempt.outcome,
                       attempt.input_manifest_hash, run.input_manifest_hash
                INTO referenced_identity_id, referenced_accession, referenced_status,
                     attempt_operation_id, attempt_parse_run_id,
                     attempt_accession, attempt_outcome,
                     attempt_manifest_hash, run_manifest_hash
                FROM sec_financial_parse_runs run
                JOIN sec_financial_filings filing ON filing.id = run.filing_id
                JOIN sec_financial_accession_attempts attempt
                  ON attempt.id = NEW.accession_attempt_id
                WHERE run.id = NEW.parse_run_id;
                IF referenced_identity_id IS NULL
                   OR referenced_identity_id <> operation_identity_id
                   OR referenced_accession <> NEW.accession_no
                   OR NEW.resource_key <> NEW.accession_no
                   OR attempt_operation_id IS DISTINCT FROM NEW.operation_id
                   OR attempt_parse_run_id IS DISTINCT FROM NEW.parse_run_id
                   OR attempt_accession IS DISTINCT FROM NEW.accession_no
                   OR referenced_status <> (CASE NEW.resolution_kind
                       WHEN 'parse_succeeded' THEN 'succeeded'
                       WHEN 'parse_failed' THEN 'failed'
                       ELSE NULL
                   END)
                   OR attempt_outcome NOT IN (
                       CASE NEW.resolution_kind
                           WHEN 'parse_succeeded' THEN 'parse_succeeded'
                           ELSE 'parse_failed'
                       END,
                       CASE NEW.resolution_kind
                           WHEN 'parse_succeeded' THEN 'parse_reused_succeeded'
                           ELSE 'parse_reused_failed'
                       END
                   )
                   OR NOT EXISTS (
                       SELECT 1 FROM sec_financial_accession_attempt_artifacts
                       WHERE attempt_id = NEW.accession_attempt_id
                   )
                   OR EXISTS (
                       SELECT 1
                       FROM sec_financial_accession_attempt_artifacts attempted
                       WHERE attempted.attempt_id = NEW.accession_attempt_id
                         AND NOT EXISTS (
                             SELECT 1 FROM sec_financial_parse_run_artifacts linked
                             WHERE linked.parse_run_id = NEW.parse_run_id
                               AND linked.artifact_id = attempted.artifact_id
                         )
                   )
                   OR (
                       run_manifest_hash = attempt_manifest_hash
                       AND EXISTS (
                           SELECT 1 FROM sec_financial_parse_run_artifacts linked
                           WHERE linked.parse_run_id = NEW.parse_run_id
                             AND NOT EXISTS (
                                 SELECT 1
                                 FROM sec_financial_accession_attempt_artifacts attempted
                                 WHERE attempted.attempt_id = NEW.accession_attempt_id
                                   AND attempted.artifact_id = linked.artifact_id
                             )
                       )
                   )
                   OR (
                       run_manifest_hash <> attempt_manifest_hash
                       AND (
                           (SELECT count(*)
                            FROM sec_financial_parse_run_artifacts linked
                            JOIN sec_filing_artifacts artifact
                              ON artifact.id = linked.artifact_id
                            WHERE linked.parse_run_id = NEW.parse_run_id
                              AND artifact.filename = '__submissions__.json') <> 1
                           OR EXISTS (
                               SELECT 1
                               FROM sec_financial_parse_run_artifacts linked
                               JOIN sec_filing_artifacts artifact
                                 ON artifact.id = linked.artifact_id
                               WHERE linked.parse_run_id = NEW.parse_run_id
                                 AND artifact.filename <> '__submissions__.json'
                                 AND NOT EXISTS (
                                     SELECT 1
                                     FROM sec_financial_accession_attempt_artifacts attempted
                                     WHERE attempted.attempt_id = NEW.accession_attempt_id
                                       AND attempted.artifact_id = linked.artifact_id
                                 )
                           )
                       )
                   ) THEN
                    RAISE EXCEPTION 'accession resolution requires current operation accession attempt';
                END IF;
            END IF;
            NEW.created_at := clock_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_financial_acquisition_resolutions_insert_guard
        BEFORE INSERT ON sec_financial_acquisition_resolutions
        FOR EACH ROW EXECUTE FUNCTION guard_sec_financial_acquisition_resolution_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_financial_operation_result_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            operation_identity_id bigint;
            referenced_identity_id bigint;
            referenced_operation_id text;
        BEGIN
            NEW.created_at := clock_timestamp();
            NEW.created_txid := txid_current();
            SELECT issuer_identity_id
            INTO operation_identity_id
            FROM sec_financial_ingestion_operations
            WHERE id = NEW.operation_id
            FOR UPDATE;
            IF operation_identity_id IS NULL
               OR EXISTS (
                   SELECT 1 FROM sec_financial_lineage_availabilities
                   WHERE operation_id = NEW.operation_id
               ) THEN
                RAISE EXCEPTION 'operation result requires matching unsealed operation';
            END IF;
            IF NEW.result_kind = 'parse_run' THEN
                SELECT filing.issuer_identity_id, run.operation_id
                INTO referenced_identity_id, referenced_operation_id
                FROM sec_financial_parse_runs run
                JOIN sec_financial_filings filing ON filing.id = run.filing_id
                WHERE run.id = NEW.parse_run_id;
                IF referenced_identity_id IS DISTINCT FROM operation_identity_id
                   OR (
                       referenced_operation_id IS NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM sec_financial_legacy_parse_runs
                           WHERE parse_run_id = NEW.parse_run_id
                       )
                   )
                   OR (
                       referenced_operation_id IS NOT NULL
                       AND referenced_operation_id IS DISTINCT FROM NEW.operation_id
                       AND NOT EXISTS (
                           SELECT 1 FROM sec_financial_lineage_availabilities
                           WHERE operation_id = referenced_operation_id
                       )
                   ) THEN
                    RAISE EXCEPTION 'operation result references unavailable parse lineage';
                END IF;
            ELSIF NEW.result_kind = 'acquisition_failure' THEN
                SELECT operation_id INTO referenced_operation_id
                FROM sec_financial_acquisition_failures
                WHERE id = NEW.acquisition_failure_id;
                IF referenced_operation_id IS DISTINCT FROM NEW.operation_id THEN
                    RAISE EXCEPTION 'operation result references foreign acquisition failure';
                END IF;
            ELSIF NEW.result_kind = 'no_eligible_filings' AND EXISTS (
                SELECT 1 FROM sec_financial_resource_anchors
                WHERE operation_id = NEW.operation_id
            ) THEN
                RAISE EXCEPTION 'no-filings result cannot use no-bytes resource anchor';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_financial_operation_results_insert_guard
        BEFORE INSERT ON sec_financial_operation_results
        FOR EACH ROW EXECUTE FUNCTION guard_sec_financial_operation_result_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION stamp_sec_financial_lineage_availability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            sealed_operation sec_financial_ingestion_operations%ROWTYPE;
            terminal sec_financial_operation_results%ROWTYPE;
        BEGIN
            SELECT * INTO sealed_operation
            FROM sec_financial_ingestion_operations
            WHERE id = NEW.operation_id
            FOR UPDATE;
            IF sealed_operation.id IS NULL
               OR sealed_operation.created_txid = txid_current() THEN
                RAISE EXCEPTION 'availability requires a committed ingestion operation';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM sec_financial_operation_snapshots
                WHERE operation_id = NEW.operation_id
            ) AND NOT EXISTS (
                SELECT 1 FROM sec_financial_resource_anchors
                WHERE operation_id = NEW.operation_id
            ) THEN
                RAISE EXCEPTION 'availability requires retained submissions snapshot or no-bytes resource anchor';
            END IF;
            SELECT * INTO terminal
            FROM sec_financial_operation_results
            WHERE operation_id = NEW.operation_id;
            IF terminal.operation_id IS NULL THEN
                RAISE EXCEPTION 'availability requires terminal operation result';
            END IF;
            IF terminal.result_kind = 'parse_run' AND NOT EXISTS (
                SELECT 1
                FROM sec_financial_parse_runs run
                JOIN sec_financial_filings filing ON filing.id = run.filing_id
                WHERE run.id = terminal.parse_run_id
                  AND filing.issuer_identity_id = sealed_operation.issuer_identity_id
                  AND (
                      run.operation_id = NEW.operation_id
                      OR (
                          run.operation_id IS NULL
                          AND EXISTS (
                              SELECT 1 FROM sec_financial_legacy_parse_runs legacy
                              WHERE legacy.parse_run_id = run.id
                          )
                      )
                      OR EXISTS (
                          SELECT 1 FROM sec_financial_lineage_availabilities prior
                          WHERE prior.operation_id = run.operation_id
                      )
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM sec_financial_acquisition_resolutions resolution
                      JOIN sec_financial_accession_attempts attempt
                        ON attempt.id = resolution.accession_attempt_id
                      WHERE resolution.operation_id = NEW.operation_id
                        AND resolution.resource_role = 'accession_terminal'
                        AND resolution.parse_run_id = terminal.parse_run_id
                        AND attempt.operation_id = NEW.operation_id
                        AND attempt.parse_run_id = terminal.parse_run_id
                  )
            ) THEN
                RAISE EXCEPTION 'availability parse terminal is invalid';
            ELSIF terminal.result_kind = 'acquisition_failure' AND NOT EXISTS (
                SELECT 1
                FROM sec_financial_acquisition_failures failure
                LEFT JOIN sec_submission_snapshots snapshot
                  ON snapshot.id = failure.submission_snapshot_id
                LEFT JOIN sec_financial_operation_snapshots link
                  ON link.operation_id = failure.operation_id
                 AND link.snapshot_id = failure.submission_snapshot_id
                LEFT JOIN sec_financial_resource_anchors anchor
                  ON anchor.id = failure.resource_anchor_id
                WHERE failure.id = terminal.acquisition_failure_id
                  AND failure.operation_id = NEW.operation_id
                  AND (
                      (
                          failure.submission_snapshot_id IS NOT NULL
                          AND snapshot.issuer_identity_id = sealed_operation.issuer_identity_id
                          AND link.snapshot_id IS NOT NULL
                      )
                      OR (
                          failure.resource_anchor_id IS NOT NULL
                          AND anchor.operation_id = NEW.operation_id
                          AND anchor.resource_role = failure.resource_role
                          AND anchor.resource_key = failure.resource_key
                          AND failure.resource_role = 'main_submissions'
                          AND failure.stage = 'submissions_fetch'
                      )
                  )
                  AND (
                      failure.accession_no IS NULL
                      OR EXISTS (
                          SELECT 1 FROM sec_financial_accession_attempts attempt
                          WHERE attempt.operation_id = NEW.operation_id
                            AND attempt.accession_no = failure.accession_no
                      )
                  )
            ) THEN
                RAISE EXCEPTION 'availability acquisition terminal is invalid';
            ELSIF terminal.result_kind = 'no_eligible_filings' AND (
                EXISTS (
                    SELECT 1 FROM sec_financial_parse_runs
                    WHERE operation_id = NEW.operation_id
                )
                OR EXISTS (
                    SELECT 1 FROM sec_financial_acquisition_failures
                    WHERE operation_id = NEW.operation_id
                )
                OR EXISTS (
                    SELECT 1 FROM sec_financial_resource_anchors
                    WHERE operation_id = NEW.operation_id
                )
                OR EXISTS (
                    SELECT 1 FROM sec_financial_accession_attempts
                    WHERE operation_id = NEW.operation_id
                )
                OR EXISTS (
                    SELECT 1 FROM sec_financial_acquisition_resolutions
                    WHERE operation_id = NEW.operation_id
                      AND resource_role = 'accession_terminal'
                )
            ) THEN
                RAISE EXCEPTION 'availability no-filings terminal is invalid';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM sec_financial_acquisition_resolutions resolution
                LEFT JOIN sec_submission_snapshots snapshot
                  ON snapshot.id = resolution.submission_snapshot_id
                LEFT JOIN sec_financial_operation_snapshots link
                  ON link.operation_id = resolution.operation_id
                 AND link.snapshot_id = resolution.submission_snapshot_id
                LEFT JOIN sec_financial_parse_runs run
                  ON run.id = resolution.parse_run_id
                LEFT JOIN sec_financial_filings filing
                  ON filing.id = run.filing_id
                WHERE resolution.operation_id = NEW.operation_id
                  AND (
                      (resolution.resolution_kind = 'resource_validated' AND (
                          snapshot.issuer_identity_id IS DISTINCT FROM
                              sealed_operation.issuer_identity_id
                          OR link.snapshot_id IS NULL
                          OR snapshot.source_url IS DISTINCT FROM resolution.resource_key
                      ))
                      OR
                      (resolution.resolution_kind IN ('parse_succeeded', 'parse_failed') AND (
                          filing.issuer_identity_id IS DISTINCT FROM
                              sealed_operation.issuer_identity_id
                          OR filing.accession_no IS DISTINCT FROM resolution.accession_no
                          OR resolution.resource_key IS DISTINCT FROM
                              resolution.accession_no
                          OR run.status IS DISTINCT FROM (CASE resolution.resolution_kind
                              WHEN 'parse_succeeded' THEN 'succeeded'
                              ELSE 'failed'
                          END)
                      ))
                  )
            ) THEN
                RAISE EXCEPTION 'availability acquisition resolution is invalid';
            END IF;
            NEW.available_at := clock_timestamp();
            NEW.finalized_txid := txid_current();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_financial_lineage_availabilities_stamp
        BEFORE INSERT ON sec_financial_lineage_availabilities
        FOR EACH ROW EXECUTE FUNCTION stamp_sec_financial_lineage_availability()
        """
    )
    for table_name in (
        "sec_financial_ingestion_operations",
        "sec_financial_lineage_availabilities",
        "sec_financial_resource_anchors",
        "sec_financial_acquisition_failures",
        "sec_financial_accession_attempts",
        "sec_financial_accession_attempt_artifacts",
        "sec_financial_acquisition_resolutions",
        "sec_financial_operation_snapshots",
        "sec_financial_operation_results",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation()"
        )
    op.execute(
        """
        CREATE FUNCTION guard_sec_submission_snapshot_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            snapshot_identity sec_issuer_identities%ROWTYPE;
            operation_identity_id bigint;
        BEGIN
            SELECT issuer_identity_id
            INTO operation_identity_id
            FROM sec_financial_ingestion_operations
            WHERE id = NEW.operation_id
            FOR UPDATE;
            IF operation_identity_id IS NULL
               OR operation_identity_id <> NEW.issuer_identity_id
               OR EXISTS (
                   SELECT 1 FROM sec_financial_lineage_availabilities
                   WHERE operation_id = NEW.operation_id
               ) THEN
                RAISE EXCEPTION 'snapshot requires matching unsealed SEC operation';
            END IF;
            SELECT * INTO snapshot_identity
            FROM sec_issuer_identities
            WHERE id = NEW.issuer_identity_id;
            IF snapshot_identity.id IS NOT NULL THEN
                PERFORM pg_advisory_xact_lock(
                    hashtextextended('sec-issuer-cik:' || snapshot_identity.cik, 0)
                );
                PERFORM pg_advisory_xact_lock(
                    hashtextextended(
                        'sec-issuer-stock:' || snapshot_identity.stock_id::text, 0
                    )
                );
                SELECT * INTO snapshot_identity
                FROM sec_issuer_identities
                WHERE id = NEW.issuer_identity_id
                FOR SHARE;
            END IF;
            IF snapshot_identity.id IS NULL
               OR snapshot_identity.status <> 'reviewed'
               OR snapshot_identity.known_at > NEW.known_at
               OR EXISTS (
                   SELECT 1 FROM sec_issuer_identities child
                   WHERE child.supersedes_identity_id = snapshot_identity.id
                     AND child.known_at <= NEW.known_at
               ) THEN
                RAISE EXCEPTION
                    'snapshot requires current reviewed SEC issuer identity';
            END IF;
            IF NEW.source_url <> (
                   'https://data.sec.gov/submissions/CIK'
                   || snapshot_identity.cik || '.json'
               )
               AND NEW.source_url !~ (
                   '^https://data[.]sec[.]gov/submissions/CIK'
                   || snapshot_identity.cik
                   || '-submissions-[0-9]+[.]json$'
               ) THEN
                RAISE EXCEPTION
                    'snapshot requires canonical SEC submissions source URL';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_submission_snapshots_insert_guard
        BEFORE INSERT ON sec_submission_snapshots
        FOR EACH ROW EXECUTE FUNCTION guard_sec_submission_snapshot_insert()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_submission_snapshots_append_only
        BEFORE UPDATE OR DELETE ON sec_submission_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sec_issuer_identity_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            superseded sec_issuer_identities%ROWTYPE;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended('sec-issuer-cik:' || NEW.cik, 0)
            );
            PERFORM pg_advisory_xact_lock(
                hashtextextended('sec-issuer-stock:' || NEW.stock_id::text, 0)
            );
            IF NEW.status = 'retired' AND NEW.supersedes_identity_id IS NULL THEN
                RAISE EXCEPTION
                    'retired SEC issuer identity must supersede a current decision';
            END IF;
            IF NEW.supersedes_identity_id IS NOT NULL THEN
                SELECT * INTO superseded
                FROM sec_issuer_identities
                WHERE id = NEW.supersedes_identity_id
                FOR UPDATE;
                IF NOT FOUND
                   OR superseded.stock_id <> NEW.stock_id
                   OR NEW.known_at <= superseded.known_at
                   OR EXISTS (
                       SELECT 1 FROM sec_issuer_identities child
                       WHERE child.supersedes_identity_id = superseded.id
                   ) THEN
                    RAISE EXCEPTION
                        'invalid or stale SEC issuer identity supersession';
                END IF;
                IF EXISTS (
                       SELECT 1 FROM sec_submission_snapshots snapshot
                       WHERE snapshot.issuer_identity_id = superseded.id
                         AND snapshot.known_at >= NEW.known_at
                   )
                   OR EXISTS (
                       SELECT 1 FROM sec_financial_filings filing
                       WHERE filing.issuer_identity_id = superseded.id
                         AND filing.known_at >= NEW.known_at
                   ) THEN
                    RAISE EXCEPTION
                        'identity transition predates persisted SEC lineage';
                END IF;
            END IF;

            IF NEW.status = 'reviewed' AND EXISTS (
                SELECT 1
                FROM sec_issuer_identities existing
                WHERE existing.status IN ('reviewed', 'retired')
                  AND existing.id IS DISTINCT FROM NEW.supersedes_identity_id
                  AND NOT EXISTS (
                      SELECT 1 FROM sec_issuer_identities child
                      WHERE child.supersedes_identity_id = existing.id
                  )
                  AND (
                      existing.effective_to IS NULL
                      OR NEW.effective_from <= existing.effective_to
                  )
                  AND (
                      NEW.effective_to IS NULL
                      OR existing.effective_from <= NEW.effective_to
                  )
                  AND (existing.stock_id = NEW.stock_id OR existing.cik = NEW.cik)
            ) THEN
                RAISE EXCEPTION 'overlapping reviewed SEC issuer identity';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sec_financial_filing_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            amended sec_financial_filings%ROWTYPE;
            new_identity sec_issuer_identities%ROWTYPE;
            amended_identity sec_issuer_identities%ROWTYPE;
        BEGIN
            SELECT * INTO new_identity FROM sec_issuer_identities
            WHERE id = NEW.issuer_identity_id;
            IF new_identity.id IS NOT NULL THEN
                PERFORM pg_advisory_xact_lock(
                    hashtextextended('sec-issuer-cik:' || new_identity.cik, 0)
                );
                PERFORM pg_advisory_xact_lock(
                    hashtextextended(
                        'sec-issuer-stock:' || new_identity.stock_id::text, 0
                    )
                );
                SELECT * INTO new_identity FROM sec_issuer_identities
                WHERE id = NEW.issuer_identity_id
                FOR SHARE;
            END IF;
            IF new_identity.id IS NULL
               OR new_identity.status <> 'reviewed'
               OR new_identity.known_at > NEW.known_at
               OR new_identity.effective_from > COALESCE(NEW.report_date, NEW.filed_on)
               OR (
                   new_identity.effective_to IS NOT NULL
                   AND new_identity.effective_to < COALESCE(NEW.report_date, NEW.filed_on)
               )
               OR EXISTS (
                   SELECT 1 FROM sec_issuer_identities child
                   WHERE child.supersedes_identity_id = new_identity.id
                     AND child.known_at <= NEW.known_at
               ) THEN
                RAISE EXCEPTION 'filing requires current reviewed SEC issuer identity';
            END IF;
            IF NEW.amends_filing_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT * INTO amended FROM sec_financial_filings
            WHERE id = NEW.amends_filing_id;
            SELECT identity.* INTO amended_identity
            FROM sec_issuer_identities identity
            WHERE identity.id = amended.issuer_identity_id;
            IF amended.id IS NULL
               OR new_identity.id IS NULL
               OR amended_identity.id IS NULL
               OR NOT NEW.is_amendment
               OR amended.form_type <> left(NEW.form_type, length(NEW.form_type) - 2)
               OR amended.report_date IS DISTINCT FROM NEW.report_date
               OR amended.accepted_at >= NEW.accepted_at
               OR amended_identity.stock_id <> new_identity.stock_id
               OR amended_identity.cik <> new_identity.cik THEN
                RAISE EXCEPTION 'invalid SEC financial amendment link';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_financial_ingestion_operations "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    op.execute(
        "LOCK TABLE sec_submission_snapshots IN SHARE ROW EXCLUSIVE MODE"
    )
    op.execute(
        "LOCK TABLE sec_financial_acquisition_failures, "
        "sec_financial_resource_anchors, "
        "sec_financial_accession_attempt_artifacts, "
        "sec_financial_accession_attempts, "
        "sec_financial_acquisition_resolutions, "
        "sec_financial_lineage_availabilities, "
        "sec_financial_legacy_parse_runs, "
        "sec_financial_operation_snapshots, "
        "sec_financial_operation_results IN SHARE ROW EXCLUSIVE MODE"
    )
    retained_snapshot_count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM sec_submission_snapshots")
    ).scalar_one()
    if retained_snapshot_count:
        raise RuntimeError(
            "cannot downgrade with retained SEC submissions snapshots"
        )
    retained_operation_count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM sec_financial_ingestion_operations")
    ).scalar_one()
    if retained_operation_count:
        raise RuntimeError(
            "cannot downgrade with retained SEC financial ingestion operations"
        )
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_operation_results_append_only ON sec_financial_operation_results")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_operation_results_insert_guard ON sec_financial_operation_results")
    op.drop_table("sec_financial_operation_results")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_financial_operation_result_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_acquisition_resolutions_append_only ON sec_financial_acquisition_resolutions")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_acquisition_resolutions_insert_guard ON sec_financial_acquisition_resolutions")
    op.drop_table("sec_financial_acquisition_resolutions")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_financial_acquisition_resolution_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_accession_attempt_artifacts_append_only ON sec_financial_accession_attempt_artifacts")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_accession_attempt_artifacts_insert_guard ON sec_financial_accession_attempt_artifacts")
    op.drop_table("sec_financial_accession_attempt_artifacts")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_financial_accession_attempt_artifact_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_accession_attempts_append_only ON sec_financial_accession_attempts")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_accession_attempts_insert_guard ON sec_financial_accession_attempts")
    op.drop_table("sec_financial_accession_attempts")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_financial_accession_attempt_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_acquisition_failures_append_only ON sec_financial_acquisition_failures")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_acquisition_failures_insert_guard ON sec_financial_acquisition_failures")
    op.drop_table("sec_financial_acquisition_failures")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_financial_acquisition_failure_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_resource_anchors_append_only ON sec_financial_resource_anchors")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_resource_anchors_insert_guard ON sec_financial_resource_anchors")
    op.drop_table("sec_financial_resource_anchors")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_financial_resource_anchor_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_filing_artifacts_source_url_insert_guard ON sec_filing_artifacts")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_filing_artifact_source_url_insert()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_financial_legacy_parse_runs_immutable "
        "ON sec_financial_legacy_parse_runs"
    )
    op.drop_table("sec_financial_legacy_parse_runs")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION stamp_sec_financial_parse_run_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.created_at := clock_timestamp();
            NEW.created_txid := txid_current();
            RETURN NEW;
        END;
        $$
        """
    )
    op.drop_index(
        "ix_sec_financial_parse_runs_operation",
        table_name="sec_financial_parse_runs",
    )
    op.drop_constraint(
        "fk_sec_financial_parse_runs_operation",
        "sec_financial_parse_runs",
        type_="foreignkey",
    )
    op.drop_column("sec_financial_parse_runs", "operation_id")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sec_financial_filing_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            amended sec_financial_filings%ROWTYPE;
            new_identity sec_issuer_identities%ROWTYPE;
            amended_identity sec_issuer_identities%ROWTYPE;
        BEGIN
            SELECT * INTO new_identity FROM sec_issuer_identities
            WHERE id = NEW.issuer_identity_id;
            IF new_identity.id IS NULL
               OR new_identity.status <> 'reviewed'
               OR new_identity.known_at > NEW.known_at
               OR new_identity.effective_from > COALESCE(NEW.report_date, NEW.filed_on)
               OR (
                   new_identity.effective_to IS NOT NULL
                   AND new_identity.effective_to < COALESCE(NEW.report_date, NEW.filed_on)
               )
               OR EXISTS (
                   SELECT 1 FROM sec_issuer_identities child
                   WHERE child.supersedes_identity_id = new_identity.id
                     AND child.known_at <= NEW.known_at
               ) THEN
                RAISE EXCEPTION 'filing requires current reviewed SEC issuer identity';
            END IF;
            IF NEW.amends_filing_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT * INTO amended FROM sec_financial_filings
            WHERE id = NEW.amends_filing_id;
            SELECT identity.* INTO amended_identity
            FROM sec_issuer_identities identity
            WHERE identity.id = amended.issuer_identity_id;
            IF amended.id IS NULL
               OR new_identity.id IS NULL
               OR amended_identity.id IS NULL
               OR NOT NEW.is_amendment
               OR amended.form_type <> left(NEW.form_type, length(NEW.form_type) - 2)
               OR amended.report_date IS DISTINCT FROM NEW.report_date
               OR amended.accepted_at >= NEW.accepted_at
               OR amended_identity.stock_id <> new_identity.stock_id
               OR amended_identity.cik <> new_identity.cik THEN
                RAISE EXCEPTION 'invalid SEC financial amendment link';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sec_issuer_identity_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            superseded sec_issuer_identities%ROWTYPE;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended('sec-issuer-cik:' || NEW.cik, 0)
            );
            PERFORM pg_advisory_xact_lock(
                hashtextextended('sec-issuer-stock:' || NEW.stock_id::text, 0)
            );
            IF NEW.status = 'retired' AND NEW.supersedes_identity_id IS NULL THEN
                RAISE EXCEPTION 'retired SEC issuer identity must supersede a current decision';
            END IF;
            IF NEW.supersedes_identity_id IS NOT NULL THEN
                SELECT * INTO superseded
                FROM sec_issuer_identities
                WHERE id = NEW.supersedes_identity_id;
                IF NOT FOUND
                   OR superseded.stock_id <> NEW.stock_id
                   OR NEW.known_at <= superseded.known_at
                   OR EXISTS (
                       SELECT 1 FROM sec_issuer_identities child
                       WHERE child.supersedes_identity_id = superseded.id
                   ) THEN
                    RAISE EXCEPTION 'invalid or stale SEC issuer identity supersession';
                END IF;
            END IF;

            IF NEW.status = 'reviewed' AND EXISTS (
                SELECT 1
                FROM sec_issuer_identities existing
                WHERE existing.status IN ('reviewed', 'retired')
                  AND existing.id IS DISTINCT FROM NEW.supersedes_identity_id
                  AND NOT EXISTS (
                      SELECT 1 FROM sec_issuer_identities child
                      WHERE child.supersedes_identity_id = existing.id
                  )
                  AND (
                      existing.effective_to IS NULL
                      OR NEW.effective_from <= existing.effective_to
                  )
                  AND (
                      NEW.effective_to IS NULL
                      OR existing.effective_from <= NEW.effective_to
                  )
                  AND (existing.stock_id = NEW.stock_id OR existing.cik = NEW.cik)
            ) THEN
                RAISE EXCEPTION 'overlapping reviewed SEC issuer identity';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_submission_snapshots_insert_guard "
        "ON sec_submission_snapshots"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_submission_snapshots_append_only "
        "ON sec_submission_snapshots"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_operation_snapshots_append_only ON sec_financial_operation_snapshots")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_operation_snapshots_insert_guard ON sec_financial_operation_snapshots")
    op.drop_table("sec_financial_operation_snapshots")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_financial_operation_snapshot_insert()")
    op.drop_index(
        "ix_sec_submission_snapshots_identity_known",
        table_name="sec_submission_snapshots",
    )
    op.drop_table("sec_submission_snapshots")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_submission_snapshot_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_lineage_availabilities_append_only ON sec_financial_lineage_availabilities")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_lineage_availabilities_stamp ON sec_financial_lineage_availabilities")
    op.drop_table("sec_financial_lineage_availabilities")
    op.execute("DROP FUNCTION IF EXISTS stamp_sec_financial_lineage_availability()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_ingestion_operations_append_only ON sec_financial_ingestion_operations")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_ingestion_operations_insert_guard ON sec_financial_ingestion_operations")
    op.drop_table("sec_financial_ingestion_operations")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_financial_operation_insert()")
    op.drop_constraint(
        "ck_sec_issuer_identities_cik",
        "sec_issuer_identities",
        type_="check",
    )
