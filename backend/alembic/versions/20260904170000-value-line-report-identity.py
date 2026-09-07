"""Version Value Line document report identity for point-in-time reads.

Revision ID: 20260904170000
Revises: 20260904160000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904170000"
down_revision = "20260904160000"
branch_labels = None
depends_on = None


TABLE = "value_line_document_report_identity_revisions"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column(
            "known_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "created_txid",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["pdf_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_value_line_report_identity_document_known",
        TABLE,
        ["document_id", sa.text("known_at DESC"), sa.text("id DESC")],
    )
    # Establish current authority for retained documents before the insert
    # guard is installed.  Its clock-stamped knowledge time deliberately does
    # not make this identity available to pre-migration historical cutoffs.
    op.execute(
        "INSERT INTO value_line_document_report_identity_revisions "
        "(document_id,user_id,stock_id,report_date) "
        "SELECT id,user_id,stock_id,report_date FROM pdf_documents ORDER BY id"
    )
    op.execute(
        """
        CREATE FUNCTION guard_value_line_report_identity_revision()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          document_user_id integer;
          document_stock_id integer;
          document_report_date date;
        BEGIN
          -- The migration-owned pdf_documents capture path reaches this guard
          -- at depth two. A top-level DML caller cannot manufacture a revision
          -- or its database-owned timestamps, and deeper recursive chains are
          -- rejected rather than accepted accidentally.
          IF TG_OP='INSERT' AND pg_trigger_depth() <> 2 THEN
            RAISE EXCEPTION 'Value Line report identity is document-generated';
          END IF;
          IF TG_OP='UPDATE' THEN
            RAISE EXCEPTION 'Value Line report identity revisions are append-only';
          END IF;
          IF TG_OP='DELETE' THEN
            IF pg_trigger_depth() <= 1 OR EXISTS (
              SELECT 1 FROM pdf_documents WHERE id=OLD.document_id
            ) THEN
              RAISE EXCEPTION 'Value Line report identity revisions are append-only';
            END IF;
            RETURN OLD;
          END IF;

          SELECT user_id,stock_id,report_date
            INTO document_user_id,document_stock_id,document_report_date
            FROM pdf_documents
            WHERE id=NEW.document_id
            FOR SHARE;
          IF NOT FOUND OR ROW(NEW.user_id,NEW.stock_id,NEW.report_date)
             IS DISTINCT FROM
             ROW(document_user_id,document_stock_id,document_report_date)
          THEN
            RAISE EXCEPTION 'Value Line report identity must match its document';
          END IF;
          NEW.known_at := clock_timestamp();
          NEW.created_txid := txid_current();
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_value_line_report_identity_revision
        BEFORE INSERT OR UPDATE OR DELETE
        ON value_line_document_report_identity_revisions
        FOR EACH ROW EXECUTE FUNCTION guard_value_line_report_identity_revision();

        CREATE FUNCTION capture_value_line_document_report_identity()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='INSERT' OR ROW(OLD.user_id,OLD.stock_id,OLD.report_date)
             IS DISTINCT FROM ROW(NEW.user_id,NEW.stock_id,NEW.report_date)
          THEN
            INSERT INTO value_line_document_report_identity_revisions
              (document_id,user_id,stock_id,report_date)
            VALUES (NEW.id,NEW.user_id,NEW.stock_id,NEW.report_date);
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_value_line_document_report_identity
        AFTER INSERT OR UPDATE OF user_id,stock_id,report_date ON pdf_documents
        FOR EACH ROW EXECUTE FUNCTION capture_value_line_document_report_identity();
        """
    )
    op.add_column(
        "metric_facts",
        sa.Column(
            "value_line_report_identity_revision_id",
            sa.BigInteger(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_metric_facts_value_line_report_identity_revision",
        "metric_facts",
        TABLE,
        ["value_line_report_identity_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_metric_facts_value_line_report_identity_revision",
        "metric_facts",
        ["value_line_report_identity_revision_id"],
    )
    # Bind only facts whose retained document identity agrees. A NULL document
    # stock is the established multi-company-container contract; each fact's
    # already-immutable stock remains authoritative in that case. Any explicit
    # stock or tenant mismatch remains null and is quarantined by readers.
    op.execute(
        "UPDATE metric_facts AS fact "
        "SET value_line_report_identity_revision_id=identity.id "
        "FROM value_line_document_report_identity_revisions AS identity "
        "WHERE fact.source_type='parsed' "
        "AND fact.source_document_id=identity.document_id "
        "AND fact.user_id IS NOT DISTINCT FROM identity.user_id "
        "AND (identity.stock_id IS NULL "
        "OR fact.stock_id IS NOT DISTINCT FROM identity.stock_id)"
    )
    op.execute(
        """
        CREATE FUNCTION bind_value_line_fact_report_identity()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          identity_row value_line_document_report_identity_revisions%ROWTYPE;
          document_user_id integer;
          document_stock_id integer;
          document_report_date date;
        BEGIN
          IF TG_OP='UPDATE' THEN
            IF (OLD.source_type='parsed' OR NEW.source_type='parsed')
               AND ROW(
                    OLD.user_id,OLD.stock_id,OLD.source_type,
                    OLD.source_document_id,
                    OLD.value_line_report_identity_revision_id
                   ) IS DISTINCT FROM ROW(
                    NEW.user_id,NEW.stock_id,NEW.source_type,
                    NEW.source_document_id,
                    NEW.value_line_report_identity_revision_id
                   )
            THEN
              RAISE EXCEPTION 'Value Line fact report identity binding is immutable';
            END IF;
            RETURN NEW;
          END IF;

          IF NEW.source_type<>'parsed' OR NEW.source_document_id IS NULL THEN
            NEW.value_line_report_identity_revision_id := NULL;
            RETURN NEW;
          END IF;

          -- Serialize fact publication with mutable document identity.  Without
          -- this row lock a concurrent document reassignment could commit after
          -- the fact selected the prior revision, leaving a newly published fact
          -- bound to authority that was no longer current at commit ordering.
          SELECT user_id,stock_id,report_date
            INTO document_user_id,document_stock_id,document_report_date
            FROM pdf_documents
            WHERE id=NEW.source_document_id
            FOR SHARE;
          IF NOT FOUND
             OR document_user_id IS DISTINCT FROM NEW.user_id
             OR (document_stock_id IS NOT NULL
                 AND document_stock_id IS DISTINCT FROM NEW.stock_id)
          THEN
            RAISE EXCEPTION 'Value Line fact requires current report identity authority';
          END IF;
          SELECT * INTO identity_row
            FROM value_line_document_report_identity_revisions
            WHERE document_id=NEW.source_document_id
            ORDER BY known_at DESC,id DESC
            LIMIT 1;
          IF NOT FOUND
             OR identity_row.user_id IS DISTINCT FROM NEW.user_id
             OR (identity_row.stock_id IS NOT NULL
                 AND identity_row.stock_id IS DISTINCT FROM NEW.stock_id)
             OR identity_row.report_date IS DISTINCT FROM document_report_date
          THEN
            RAISE EXCEPTION 'Value Line fact requires current report identity authority';
          END IF;
          NEW.value_line_report_identity_revision_id := identity_row.id;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_value_line_z_fact_report_identity
        BEFORE INSERT OR UPDATE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION bind_value_line_fact_report_identity();
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    op.execute(
        "LOCK TABLE value_line_document_report_identity_revisions IN SHARE MODE"
    )
    retained = connection.execute(
        sa.text(
            "SELECT count(*) FROM value_line_document_report_identity_revisions"
        )
    ).scalar_one()
    if retained:
        raise RuntimeError(
            "downgrade refused: cannot downgrade retained Value Line report "
            "identity authority"
        )

    op.execute(
        "DROP TRIGGER trg_value_line_z_fact_report_identity ON metric_facts; "
        "DROP FUNCTION bind_value_line_fact_report_identity()"
    )
    op.drop_index(
        "ix_metric_facts_value_line_report_identity_revision",
        table_name="metric_facts",
    )
    op.drop_constraint(
        "fk_metric_facts_value_line_report_identity_revision",
        "metric_facts",
        type_="foreignkey",
    )
    op.drop_column("metric_facts", "value_line_report_identity_revision_id")
    op.execute(
        "DROP TRIGGER trg_value_line_document_report_identity ON pdf_documents; "
        "DROP FUNCTION capture_value_line_document_report_identity(); "
        "DROP TRIGGER trg_value_line_report_identity_revision "
        "ON value_line_document_report_identity_revisions; "
        "DROP FUNCTION guard_value_line_report_identity_revision()"
    )
    op.drop_index("ix_value_line_report_identity_document_known", table_name=TABLE)
    op.drop_table(TABLE)
