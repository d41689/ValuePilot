"""Allow only parent-cascade removal of currentness history.

Revision ID: 20260904210000
Revises: 20260904200000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904210000"
down_revision = "20260904200000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "metric_fact_currentness_revisions_fact_id_fkey",
        "metric_fact_currentness_revisions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_metric_fact_currentness_fact",
        "metric_fact_currentness_revisions",
        "metric_facts",
        ["fact_id"],
        ["id"],
        ondelete="CASCADE",
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
          IF TG_OP='DELETE' AND pg_trigger_depth()>1 AND NOT EXISTS (
            SELECT 1 FROM metric_facts WHERE id=OLD.fact_id
          ) THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'metric fact currentness revisions are append-only';
        END $$;
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT count(*) FROM metric_fact_currentness_revisions")
    ).scalar_one():
        raise RuntimeError(
            "downgrade refused: cannot alter retained metric fact currentness authority"
        )
    op.drop_constraint(
        "fk_metric_fact_currentness_fact",
        "metric_fact_currentness_revisions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "metric_fact_currentness_revisions_fact_id_fkey",
        "metric_fact_currentness_revisions",
        "metric_facts",
        ["fact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
