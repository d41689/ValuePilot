"""Complete the immutable currentness slot with as-of date.

Revision ID: 20260904230000
Revises: 20260904220000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904230000"
down_revision = "20260904220000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "metric_fact_currentness_revisions",
        sa.Column("as_of_date", sa.Date(), nullable=True),
    )
    # This is a one-time completion from the now database-immutable fact slot;
    # no knowledge timestamp or currentness state is rewritten.
    op.execute(
        "ALTER TABLE metric_fact_currentness_revisions DISABLE TRIGGER "
        "trg_metric_fact_currentness_revision_immutable"
    )
    op.execute(
        "UPDATE metric_fact_currentness_revisions r SET as_of_date=f.as_of_date "
        "FROM metric_facts f WHERE f.id=r.fact_id"
    )
    op.execute(
        "ALTER TABLE metric_fact_currentness_revisions ENABLE TRIGGER "
        "trg_metric_fact_currentness_revision_immutable"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_metric_fact_currentness_revision()
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
                 NEW.period_end_date,NEW.as_of_date,NEW.is_current
               ) IS DISTINCT FROM ROW(
                 fact_row.user_id,fact_row.stock_id,fact_row.metric_key,
                 fact_row.source_type,fact_row.source_document_id,
                 fact_row.source_ref_id,fact_row.period_type,
                 fact_row.period_end_date,fact_row.as_of_date,fact_row.is_current
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
          IF TG_OP='DELETE' AND pg_trigger_depth()>1 AND NOT EXISTS (
            SELECT 1 FROM metric_facts WHERE id=OLD.fact_id
          ) THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'metric fact currentness revisions are append-only';
        END $$;

        CREATE OR REPLACE FUNCTION capture_metric_fact_currentness_revision()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='INSERT' OR OLD.is_current IS DISTINCT FROM NEW.is_current THEN
            INSERT INTO metric_fact_currentness_revisions
              (fact_id,user_id,stock_id,metric_key,source_type,source_document_id,
               source_ref_id,period_type,period_end_date,as_of_date,is_current,
               known_at,created_txid,is_backfill)
            VALUES
              (NEW.id,NEW.user_id,NEW.stock_id,NEW.metric_key,NEW.source_type,
               NEW.source_document_id,NEW.source_ref_id,NEW.period_type,
               NEW.period_end_date,NEW.as_of_date,NEW.is_current,
               clock_timestamp(),txid_current(),false);
          END IF;
          RETURN NEW;
        END $$;
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT count(*) FROM metric_fact_currentness_revisions")
    ).scalar_one():
        raise RuntimeError(
            "downgrade refused: cannot truncate retained currentness slot identity"
        )
    op.drop_column("metric_fact_currentness_revisions", "as_of_date")
