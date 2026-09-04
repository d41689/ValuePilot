"""Preserve immutable Value Line parse revisions and their exact run identity.

Revision ID: 20260904120000
Revises: 20260901280000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904120000"
down_revision = "20260901280000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "value_line_parse_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(), nullable=False),
        sa.Column("source_mapping_version", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')",
            name="ck_value_line_parse_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["pdf_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "metric_extractions",
        sa.Column("value_line_parse_run_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "metric_facts",
        sa.Column("value_line_parse_run_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_metric_extractions_value_line_parse_run_id",
        "metric_extractions",
        "value_line_parse_runs",
        ["value_line_parse_run_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_metric_facts_value_line_parse_run_id",
        "metric_facts",
        "value_line_parse_runs",
        ["value_line_parse_run_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_metric_facts_value_line_parse_run_source",
        "metric_facts",
        "value_line_parse_run_id IS NULL OR source_type='parsed'",
    )
    op.create_index(
        "ix_metric_extractions_value_line_parse_run_id",
        "metric_extractions",
        ["value_line_parse_run_id"],
    )
    op.create_index(
        "ix_metric_facts_value_line_parse_run_id",
        "metric_facts",
        ["value_line_parse_run_id"],
    )

    # The old constraint collapsed all history for one document/slot.  Keep
    # uniqueness only for the current parsed revision so reparse can append.
    op.drop_constraint("uq_metric_facts_dedupe", "metric_facts", type_="unique")
    op.create_index(
        "uq_metric_facts_current_parsed_document_period",
        "metric_facts",
        [
            "stock_id",
            "metric_key",
            "period_type",
            "period_end_date",
            "source_document_id",
        ],
        unique=True,
        postgresql_where=sa.text("source_type='parsed' AND is_current=true"),
    )
    # Preserve the legacy uniqueness contract for every non-Value-Line row;
    # only parsed Value Line revisions gain append-only history here.
    op.create_index(
        "uq_metric_facts_nonparsed_document_period",
        "metric_facts",
        [
            "stock_id",
            "metric_key",
            "period_type",
            "period_end_date",
            "source_document_id",
        ],
        unique=True,
        postgresql_where=sa.text("source_type<>'parsed'"),
    )

    op.execute(
        """
        CREATE FUNCTION guard_value_line_parse_run_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP='INSERT' THEN
            NEW.status := 'running';
            NEW.created_txid := txid_current();
            NEW.started_at := clock_timestamp();
            NEW.completed_at := NULL;
            RETURN NEW;
          END IF;
          IF TG_OP='DELETE' THEN
            IF EXISTS (
              SELECT 1 FROM pdf_documents WHERE id=OLD.document_id
            ) THEN
              RAISE EXCEPTION 'Value Line parse runs are append-only';
            END IF;
            -- An explicitly deleted source document owns the complete run,
            -- extraction, and fact retention boundary.  Its FK cascade may
            -- therefore remove the run after the parent is no longer visible.
            RETURN OLD;
          END IF;
          IF OLD.created_txid<>txid_current() OR OLD.status<>'running'
             OR NEW.status NOT IN ('succeeded','failed')
             OR ROW(OLD.id,OLD.user_id,OLD.document_id,OLD.parser_version,
                    OLD.source_mapping_version,OLD.created_txid,OLD.started_at)
                IS DISTINCT FROM
                ROW(NEW.id,NEW.user_id,NEW.document_id,NEW.parser_version,
                    NEW.source_mapping_version,NEW.created_txid,NEW.started_at)
          THEN
            RAISE EXCEPTION 'Value Line parse run may finalize only in its creating transaction';
          END IF;
          NEW.completed_at := clock_timestamp();
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_value_line_parse_run_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON value_line_parse_runs
        FOR EACH ROW EXECUTE FUNCTION guard_value_line_parse_run_mutation();

        CREATE FUNCTION guard_value_line_extraction_run_binding() RETURNS trigger
        LANGUAGE plpgsql AS $$ DECLARE run_row value_line_parse_runs%ROWTYPE; BEGIN
          IF TG_OP='UPDATE' THEN
            IF NEW.value_line_parse_run_id IS DISTINCT FROM OLD.value_line_parse_run_id THEN
              RAISE EXCEPTION 'Value Line extraction run binding is immutable';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.value_line_parse_run_id IS NULL THEN RETURN NEW; END IF;
          SELECT * INTO run_row FROM value_line_parse_runs
            WHERE id=NEW.value_line_parse_run_id;
          IF NOT FOUND OR run_row.status<>'running'
             OR run_row.created_txid<>txid_current()
             OR run_row.user_id<>NEW.user_id
             OR run_row.document_id<>NEW.document_id
          THEN
            RAISE EXCEPTION 'Value Line extraction must bind its creating parse run';
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_value_line_extraction_run_binding
        BEFORE INSERT OR UPDATE OF value_line_parse_run_id ON metric_extractions
        FOR EACH ROW EXECUTE FUNCTION guard_value_line_extraction_run_binding();

        CREATE FUNCTION guard_value_line_fact_run_binding() RETURNS trigger
        LANGUAGE plpgsql AS $$ DECLARE run_row value_line_parse_runs%ROWTYPE; BEGIN
          IF TG_OP='UPDATE' THEN
            IF NEW.value_line_parse_run_id IS DISTINCT FROM OLD.value_line_parse_run_id THEN
              RAISE EXCEPTION 'Value Line fact run binding is immutable';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.value_line_parse_run_id IS NULL THEN RETURN NEW; END IF;
          SELECT * INTO run_row FROM value_line_parse_runs
            WHERE id=NEW.value_line_parse_run_id;
          IF NOT FOUND OR run_row.status<>'running'
             OR run_row.created_txid<>txid_current()
             OR NEW.source_type<>'parsed'
             OR run_row.user_id<>NEW.user_id
             OR run_row.document_id IS DISTINCT FROM NEW.source_document_id
          THEN
            RAISE EXCEPTION 'Value Line fact must bind its creating parse run';
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_value_line_fact_run_binding
        BEFORE INSERT OR UPDATE OF value_line_parse_run_id ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION guard_value_line_fact_run_binding();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_value_line_fact_run_binding ON metric_facts;
        DROP FUNCTION IF EXISTS guard_value_line_fact_run_binding();
        DROP TRIGGER IF EXISTS trg_value_line_extraction_run_binding
          ON metric_extractions;
        DROP FUNCTION IF EXISTS guard_value_line_extraction_run_binding();
        DROP TRIGGER IF EXISTS trg_value_line_parse_run_mutation
          ON value_line_parse_runs;
        DROP FUNCTION IF EXISTS guard_value_line_parse_run_mutation();
        """
    )
    op.drop_index(
        "uq_metric_facts_current_parsed_document_period",
        table_name="metric_facts",
    )
    op.drop_index(
        "uq_metric_facts_nonparsed_document_period",
        table_name="metric_facts",
    )
    # The legacy schema cannot represent revision history.  Keep the newest
    # row per former uniqueness tuple solely to make an explicit downgrade
    # reversible; forward migration never deletes audit history.
    op.execute(
        """
        DELETE FROM metric_facts older
        USING metric_facts newer
        WHERE older.source_type='parsed' AND newer.source_type='parsed'
          AND older.id<newer.id
          AND ROW(older.stock_id,older.metric_key,older.period_type,
                  older.period_end_date,older.source_document_id)
              IS NOT DISTINCT FROM
              ROW(newer.stock_id,newer.metric_key,newer.period_type,
                  newer.period_end_date,newer.source_document_id)
        """
    )
    op.create_unique_constraint(
        "uq_metric_facts_dedupe",
        "metric_facts",
        [
            "stock_id",
            "metric_key",
            "period_type",
            "period_end_date",
            "source_document_id",
        ],
    )
    op.drop_constraint(
        "ck_metric_facts_value_line_parse_run_source",
        "metric_facts",
        type_="check",
    )
    op.drop_index("ix_metric_facts_value_line_parse_run_id", table_name="metric_facts")
    op.drop_index(
        "ix_metric_extractions_value_line_parse_run_id",
        table_name="metric_extractions",
    )
    op.drop_constraint(
        "fk_metric_facts_value_line_parse_run_id",
        "metric_facts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_metric_extractions_value_line_parse_run_id",
        "metric_extractions",
        type_="foreignkey",
    )
    op.drop_column("metric_facts", "value_line_parse_run_id")
    op.drop_column("metric_extractions", "value_line_parse_run_id")
    op.drop_table("value_line_parse_runs")
