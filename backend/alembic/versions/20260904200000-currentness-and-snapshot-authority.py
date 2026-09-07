"""Version fact currentness and bound document snapshots.

Revision ID: 20260904200000
Revises: 20260904190000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904200000"
down_revision = "20260904190000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metric_fact_currentness_authority",
        sa.Column("singleton", sa.Boolean(), nullable=False),
        sa.Column("authority_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("singleton", name="ck_metric_fact_currentness_singleton"),
        sa.PrimaryKeyConstraint("singleton"),
    )
    op.execute(
        "INSERT INTO metric_fact_currentness_authority "
        "(singleton,authority_started_at) VALUES (true,clock_timestamp())"
    )
    op.create_table(
        "metric_fact_currentness_revisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("fact_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("stock_id", sa.BigInteger(), nullable=False),
        sa.Column("metric_key", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("period_type", sa.String(), nullable=True),
        sa.Column("period_end_date", sa.Date(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), nullable=True),
        sa.Column("is_backfill", sa.Boolean(), nullable=False),
        sa.Column("prior_revision_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["fact_id"], ["metric_facts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["prior_revision_id"],
            ["metric_fact_currentness_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_metric_fact_currentness_fact_known",
        "metric_fact_currentness_revisions",
        ["fact_id", sa.text("known_at DESC"), sa.text("id DESC")],
    )
    # Retained projection state is learned only at the migration boundary.  It
    # must never be presented as proof of any earlier state.
    op.execute(
        "INSERT INTO metric_fact_currentness_revisions "
        "(fact_id,user_id,stock_id,metric_key,source_type,source_document_id,"
        "source_ref_id,period_type,period_end_date,is_current,known_at,"
        "created_txid,is_backfill) "
        "SELECT f.id,f.user_id,f.stock_id,f.metric_key,f.source_type,"
        "f.source_document_id,f.source_ref_id,f.period_type,f.period_end_date,"
        "f.is_current,a.authority_started_at,NULL,true "
        "FROM metric_facts f CROSS JOIN metric_fact_currentness_authority a "
        "WHERE a.singleton=true ORDER BY f.id"
    )
    op.execute(
        """
        CREATE FUNCTION guard_metric_fact_currentness_revision()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          fact_row metric_facts%ROWTYPE;
        BEGIN
          IF TG_OP='INSERT' THEN
            IF pg_trigger_depth() <> 2 THEN
              RAISE EXCEPTION 'metric fact currentness revisions are database-owned';
            END IF;
            SELECT * INTO fact_row FROM metric_facts WHERE id=NEW.fact_id FOR SHARE;
            IF NOT FOUND OR ROW(
                 NEW.user_id,NEW.stock_id,NEW.metric_key,NEW.source_type,
                 NEW.source_document_id,NEW.source_ref_id,NEW.period_type,
                 NEW.period_end_date,NEW.is_current
               ) IS DISTINCT FROM ROW(
                 fact_row.user_id,fact_row.stock_id,fact_row.metric_key,
                 fact_row.source_type,fact_row.source_document_id,
                 fact_row.source_ref_id,fact_row.period_type,
                 fact_row.period_end_date,fact_row.is_current
               )
            THEN
              RAISE EXCEPTION 'metric fact currentness revision must match its fact';
            END IF;
            SELECT id INTO NEW.prior_revision_id
              FROM metric_fact_currentness_revisions
              WHERE fact_id=NEW.fact_id ORDER BY id DESC LIMIT 1;
            NEW.known_at := clock_timestamp();
            NEW.created_txid := txid_current();
            NEW.is_backfill := false;
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'metric fact currentness revisions are append-only';
        END $$;

        CREATE TRIGGER trg_metric_fact_currentness_revision_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON metric_fact_currentness_revisions
        FOR EACH ROW EXECUTE FUNCTION guard_metric_fact_currentness_revision();

        CREATE FUNCTION capture_metric_fact_currentness_revision()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='INSERT' OR OLD.is_current IS DISTINCT FROM NEW.is_current THEN
            INSERT INTO metric_fact_currentness_revisions
              (fact_id,user_id,stock_id,metric_key,source_type,source_document_id,
               source_ref_id,period_type,period_end_date,is_current,known_at,
               created_txid,is_backfill)
            VALUES
              (NEW.id,NEW.user_id,NEW.stock_id,NEW.metric_key,NEW.source_type,
               NEW.source_document_id,NEW.source_ref_id,NEW.period_type,
               NEW.period_end_date,NEW.is_current,clock_timestamp(),
               txid_current(),false);
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_metric_fact_currentness_capture
        AFTER INSERT OR UPDATE OF is_current ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION capture_metric_fact_currentness_revision();
        """
    )

    op.add_column(
        "document_list_snapshots",
        sa.Column("membership_fingerprint", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "document_list_snapshot_members",
        sa.Column("report_date", sa.Date(), nullable=True),
    )
    op.execute(
        "UPDATE document_list_snapshots s SET membership_fingerprint="
        "COALESCE((SELECT md5(string_agg("
        "m.document_id::text || ':' || COALESCE(m.upload_time::text,'NULL') || ':' || "
        "m.source,',' ORDER BY m.ordinal)) FROM document_list_snapshot_members m "
        "WHERE m.snapshot_id=s.id),md5(''))"
    )
    op.alter_column(
        "document_list_snapshots", "membership_fingerprint", nullable=False
    )
    op.create_index(
        "ix_document_list_snapshots_user_active",
        "document_list_snapshots",
        ["user_id", sa.text("expires_at DESC"), sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_pdf_documents_user_upload_id",
        "pdf_documents",
        ["user_id", sa.text("upload_time DESC NULLS LAST"), sa.text("id DESC")],
    )
    # Replace the 190 trigger so all four temporal/transaction fields are
    # stamped from one database clock value and the TTL cannot be shortened,
    # extended or backdated by DML.
    op.execute(
        """
        DROP TRIGGER trg_document_list_snapshots_immutable ON document_list_snapshots;
        DROP FUNCTION guard_document_list_snapshot_immutability();

        CREATE FUNCTION guard_document_list_snapshot_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          snapshot_clock timestamptz;
        BEGIN
          IF TG_OP='INSERT' THEN
            snapshot_clock := clock_timestamp();
            NEW.snapshot_cutoff := snapshot_clock;
            NEW.created_at := snapshot_clock;
            NEW.expires_at := snapshot_clock + interval '15 minutes';
            NEW.created_txid := txid_current();
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'document list snapshots are immutable';
        END $$;

        CREATE TRIGGER trg_document_list_snapshots_immutable
        BEFORE INSERT OR UPDATE ON document_list_snapshots
        FOR EACH ROW EXECUTE FUNCTION guard_document_list_snapshot_immutability();
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    retained = connection.execute(
        sa.text("SELECT count(*) FROM metric_fact_currentness_revisions")
    ).scalar_one()
    if retained:
        raise RuntimeError(
            "downgrade refused: cannot discard retained metric fact currentness authority"
        )
    op.execute(
        "DROP TRIGGER trg_metric_fact_currentness_capture ON metric_facts; "
        "DROP FUNCTION capture_metric_fact_currentness_revision(); "
        "DROP TRIGGER trg_metric_fact_currentness_revision_immutable "
        "ON metric_fact_currentness_revisions; "
        "DROP FUNCTION guard_metric_fact_currentness_revision()"
    )
    op.execute(
        "DROP TRIGGER trg_document_list_snapshots_immutable "
        "ON document_list_snapshots; "
        "DROP FUNCTION guard_document_list_snapshot_immutability(); "
        "CREATE FUNCTION guard_document_list_snapshot_immutability() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "IF TG_OP='INSERT' THEN NEW.created_at:=clock_timestamp(); "
        "NEW.created_txid:=txid_current(); RETURN NEW; END IF; "
        "RAISE EXCEPTION 'document list snapshots are immutable'; END $$; "
        "CREATE TRIGGER trg_document_list_snapshots_immutable "
        "BEFORE INSERT OR UPDATE ON document_list_snapshots "
        "FOR EACH ROW EXECUTE FUNCTION guard_document_list_snapshot_immutability()"
    )
    op.drop_index("ix_pdf_documents_user_upload_id", table_name="pdf_documents")
    op.drop_index(
        "ix_document_list_snapshots_user_active",
        table_name="document_list_snapshots",
    )
    op.drop_column("document_list_snapshot_members", "report_date")
    op.drop_column("document_list_snapshots", "membership_fingerprint")
    op.drop_index(
        "ix_metric_fact_currentness_fact_known",
        table_name="metric_fact_currentness_revisions",
    )
    op.drop_table("metric_fact_currentness_revisions")
    op.drop_table("metric_fact_currentness_authority")
