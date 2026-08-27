"""SEC financial-filing lineage foundation.

Revision ID: 20260827120000
Revises: 20260826130000
Create Date: 2026-08-27 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260827120000"
down_revision = "20260826130000"
branch_labels = None
depends_on = None


_TABLES = (
    "sec_issuer_identities",
    "sec_financial_filings",
    "sec_filing_artifacts",
    "sec_financial_parse_runs",
    "sec_financial_parse_run_artifacts",
    "sec_raw_xbrl_facts",
)


def upgrade() -> None:
    op.create_table(
        "sec_issuer_identities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stock_id", sa.BigInteger(), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer_user_id", sa.BigInteger(), nullable=True),
        sa.Column("supersedes_identity_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('reviewed', 'needs_review', 'retired')",
            name="ck_sec_issuer_identities_status",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_sec_issuer_identities_interval",
        ),
        sa.CheckConstraint(
            "status = 'needs_review' OR length(btrim(review_reason)) > 0",
            name="ck_sec_issuer_identities_review_reason",
        ),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["supersedes_identity_id"], ["sec_issuer_identities.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_id", "cik", "effective_from", "known_at",
            name="uq_sec_issuer_identity_decision",
        ),
        sa.UniqueConstraint(
            "supersedes_identity_id",
            name="uq_sec_issuer_identity_single_supersession",
        ),
    )
    op.create_index("ix_sec_issuer_identities_cik", "sec_issuer_identities", ["cik"])
    op.create_index(
        "ix_sec_issuer_identities_stock_known",
        "sec_issuer_identities",
        ["stock_id", "known_at"],
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_issuer_identity_insert()
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
        """
        CREATE TRIGGER trg_sec_issuer_identities_insert_guard
        BEFORE INSERT ON sec_issuer_identities
        FOR EACH ROW EXECUTE FUNCTION guard_sec_issuer_identity_insert()
        """
    )

    op.create_table(
        "sec_financial_filings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("issuer_identity_id", sa.BigInteger(), nullable=False),
        sa.Column("accession_no", sa.String(length=20), nullable=False),
        sa.Column("form_type", sa.String(length=12), nullable=False),
        sa.Column("is_amendment", sa.Boolean(), nullable=False),
        sa.Column("filed_on", sa.Date(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("primary_document", sa.String(length=255), nullable=False),
        sa.Column("primary_doc_description", sa.Text(), nullable=True),
        sa.Column("index_url", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("submissions_source_url", sa.Text(), nullable=False),
        sa.Column("discovery_payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("amends_filing_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "form_type IN ('10-K', '10-K/A', '10-Q', '10-Q/A', '20-F', '20-F/A', '6-K')",
            name="ck_sec_financial_filings_form",
        ),
        sa.CheckConstraint(
            "is_amendment = (right(form_type, 2) = '/A')",
            name="ck_sec_financial_filings_amendment_flag",
        ),
        sa.ForeignKeyConstraint(
            ["amends_filing_id"], ["sec_financial_filings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["issuer_identity_id"], ["sec_issuer_identities.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accession_no", name="uq_sec_financial_filings_accession"),
    )
    op.create_index(
        "ix_sec_financial_filings_identity_accepted",
        "sec_financial_filings",
        ["issuer_identity_id", "accepted_at"],
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_financial_filing_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            amended sec_financial_filings%ROWTYPE;
            new_identity sec_issuer_identities%ROWTYPE;
            amended_identity sec_issuer_identities%ROWTYPE;
        BEGIN
            IF NEW.amends_filing_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT * INTO amended FROM sec_financial_filings
            WHERE id = NEW.amends_filing_id;
            SELECT * INTO new_identity FROM sec_issuer_identities
            WHERE id = NEW.issuer_identity_id;
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
        CREATE TRIGGER trg_sec_financial_filings_insert_guard
        BEFORE INSERT ON sec_financial_filings
        FOR EACH ROW EXECUTE FUNCTION guard_sec_financial_filing_insert()
        """
    )

    op.create_table(
        "sec_filing_artifacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sec_type", sa.String(length=80), nullable=True),
        sa.Column("declared_size", sa.BigInteger(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("content_mime", sa.String(length=160), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_etag", sa.Text(), nullable=True),
        sa.Column("http_last_modified", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "state IN ('manifest_only', 'retained', 'unavailable', 'rejected')",
            name="ck_sec_filing_artifacts_state",
        ),
        sa.CheckConstraint(
            "(state = 'retained' AND sha256 IS NOT NULL AND byte_size IS NOT NULL "
            "AND storage_key IS NOT NULL AND fetched_at IS NOT NULL) OR "
            "(state <> 'retained' AND storage_key IS NULL)",
            name="ck_sec_filing_artifacts_retained_shape",
        ),
        sa.ForeignKeyConstraint(["filing_id"], ["sec_financial_filings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "filing_id", "filename", "manifest_hash", "state",
            name="uq_sec_filing_artifact_observation",
        ),
    )
    op.create_index(
        "ix_sec_filing_artifacts_filing_known",
        "sec_filing_artifacts",
        ["filing_id", "known_at"],
    )

    op.create_table(
        "sec_financial_parse_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_name", sa.String(length=80), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("input_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fact_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_sec_financial_parse_runs_status",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND error_code IS NULL) OR "
            "(status = 'failed' AND error_code IS NOT NULL)",
            name="ck_sec_financial_parse_runs_result",
        ),
        sa.ForeignKeyConstraint(["filing_id"], ["sec_financial_filings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "filing_id", "parser_version", "input_manifest_hash",
            name="uq_sec_financial_parse_run_input",
        ),
    )
    op.create_index(
        "ix_sec_financial_parse_runs_filing_known",
        "sec_financial_parse_runs",
        ["filing_id", "known_at"],
    )

    op.create_table(
        "sec_financial_parse_run_artifacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("parse_run_id", sa.BigInteger(), nullable=False),
        sa.Column("artifact_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["sec_filing_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parse_run_id"], ["sec_financial_parse_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parse_run_id", "artifact_id", name="uq_sec_financial_parse_run_artifact"
        ),
    )
    op.create_index(
        "ix_sec_financial_parse_run_artifacts_run",
        "sec_financial_parse_run_artifacts",
        ["parse_run_id"],
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_parse_run_artifact_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            run_filing_id bigint;
            run_known_at timestamptz;
            artifact_filing_id bigint;
            artifact_state text;
            artifact_known_at timestamptz;
        BEGIN
            SELECT filing_id, known_at INTO run_filing_id, run_known_at
            FROM sec_financial_parse_runs WHERE id = NEW.parse_run_id;
            SELECT filing_id, state, known_at
            INTO artifact_filing_id, artifact_state, artifact_known_at
            FROM sec_filing_artifacts WHERE id = NEW.artifact_id;
            IF run_filing_id IS NULL
               OR artifact_filing_id IS NULL
               OR run_filing_id <> artifact_filing_id
               OR artifact_state <> 'retained'
               OR artifact_known_at > run_known_at THEN
                RAISE EXCEPTION 'invalid SEC parse-run artifact link';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_financial_parse_run_artifacts_insert_guard
        BEFORE INSERT ON sec_financial_parse_run_artifacts
        FOR EACH ROW EXECUTE FUNCTION guard_sec_parse_run_artifact_insert()
        """
    )

    op.create_table(
        "sec_raw_xbrl_facts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("parse_run_id", sa.BigInteger(), nullable=False),
        sa.Column("artifact_id", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("concept", sa.Text(), nullable=False),
        sa.Column("concept_namespace_uri", sa.Text(), nullable=True),
        sa.Column("context_id", sa.Text(), nullable=True),
        sa.Column("unit_id", sa.Text(), nullable=True),
        sa.Column("unit_measure", sa.Text(), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("transformation_format", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=80), nullable=True),
        sa.Column("continued_at", sa.Text(), nullable=True),
        sa.Column("decimals", sa.String(length=40), nullable=True),
        sa.Column("scale", sa.Integer(), nullable=True),
        sa.Column("sign", sa.String(length=4), nullable=True),
        sa.Column("is_nil", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("period_instant", sa.Date(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("entity_identifier", sa.Text(), nullable=True),
        sa.Column("dimensions_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("locator_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["sec_filing_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parse_run_id"], ["sec_financial_parse_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["parse_run_id", "artifact_id"],
            [
                "sec_financial_parse_run_artifacts.parse_run_id",
                "sec_financial_parse_run_artifacts.artifact_id",
            ],
            name="fk_sec_raw_xbrl_fact_exact_input",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parse_run_id", "ordinal", name="uq_sec_raw_xbrl_fact_ordinal"),
    )
    op.create_index("ix_sec_raw_xbrl_facts_parse_run_id", "sec_raw_xbrl_facts", ["parse_run_id"])
    op.execute(
        """
        CREATE FUNCTION guard_sec_raw_xbrl_fact_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            run_status text;
            artifact_state text;
        BEGIN
            SELECT status INTO run_status
            FROM sec_financial_parse_runs WHERE id = NEW.parse_run_id;
            SELECT state INTO artifact_state
            FROM sec_filing_artifacts WHERE id = NEW.artifact_id;
            IF run_status <> 'succeeded' OR artifact_state <> 'retained' THEN
                RAISE EXCEPTION 'raw SEC XBRL fact requires succeeded run and retained input';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_raw_xbrl_facts_insert_guard
        BEFORE INSERT ON sec_raw_xbrl_facts
        FOR EACH ROW EXECUTE FUNCTION guard_sec_raw_xbrl_fact_insert()
        """
    )

    op.execute(
        """
        CREATE FUNCTION reject_sec_financial_lineage_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only; % is forbidden', TG_TABLE_NAME, TG_OP;
        END;
        $$
        """
    )
    for table_name in _TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation()
            """
        )


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS reject_sec_financial_lineage_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_raw_xbrl_facts_insert_guard "
        "ON sec_raw_xbrl_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_sec_raw_xbrl_fact_insert()")
    op.drop_index("ix_sec_raw_xbrl_facts_parse_run_id", table_name="sec_raw_xbrl_facts")
    op.drop_table("sec_raw_xbrl_facts")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_financial_parse_run_artifacts_insert_guard "
        "ON sec_financial_parse_run_artifacts"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_sec_parse_run_artifact_insert()")
    # A reload-enabled development API may have materialized the newly imported
    # model table before Alembic reaches this revision. Its metadata-created
    # index has a different generated name, so tolerate the planned index being
    # absent while still dropping the exact table below.
    op.execute("DROP INDEX IF EXISTS ix_sec_financial_parse_run_artifacts_run")
    op.execute("DROP TABLE IF EXISTS sec_financial_parse_run_artifacts")
    op.drop_index("ix_sec_financial_parse_runs_filing_known", table_name="sec_financial_parse_runs")
    op.drop_table("sec_financial_parse_runs")
    op.drop_index("ix_sec_filing_artifacts_filing_known", table_name="sec_filing_artifacts")
    op.drop_table("sec_filing_artifacts")
    op.drop_index("ix_sec_financial_filings_identity_accepted", table_name="sec_financial_filings")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_financial_filings_insert_guard "
        "ON sec_financial_filings"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_sec_financial_filing_insert()")
    op.drop_table("sec_financial_filings")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_issuer_identities_insert_guard "
        "ON sec_issuer_identities"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_sec_issuer_identity_insert()")
    op.drop_index("ix_sec_issuer_identities_stock_known", table_name="sec_issuer_identities")
    op.drop_index("ix_sec_issuer_identities_cik", table_name="sec_issuer_identities")
    op.drop_table("sec_issuer_identities")
