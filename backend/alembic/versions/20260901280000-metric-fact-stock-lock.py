"""Serialize stock-scoped metric-fact reads and writes.

Revision ID: 20260901280000
Revises: 20260901270000
"""

from alembic import op


revision = "20260901280000"
down_revision = "20260901270000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION lock_metric_fact_stock_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          old_stock_id bigint;
          new_stock_id bigint;
          first_stock_id bigint;
          second_stock_id bigint;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            new_stock_id := NEW.stock_id;
          ELSIF TG_OP = 'DELETE' THEN
            old_stock_id := OLD.stock_id;
          ELSE
            old_stock_id := OLD.stock_id;
            new_stock_id := NEW.stock_id;
          END IF;

          IF old_stock_id IS NOT NULL AND new_stock_id IS NOT NULL THEN
            first_stock_id := LEAST(old_stock_id, new_stock_id);
            second_stock_id := GREATEST(old_stock_id, new_stock_id);
          ELSE
            first_stock_id := COALESCE(old_stock_id, new_stock_id);
          END IF;

          PERFORM pg_advisory_xact_lock(
            hashtextextended(
              'valuepilot:metric-facts-stock:' || first_stock_id::text,
              0
            )
          );
          IF second_stock_id IS NOT NULL AND second_stock_id <> first_stock_id THEN
            PERFORM pg_advisory_xact_lock(
              hashtextextended(
                'valuepilot:metric-facts-stock:' || second_stock_id::text,
                0
              )
            );
          END IF;

          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_metric_facts_stock_lock
        BEFORE INSERT OR UPDATE OR DELETE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION lock_metric_fact_stock_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_metric_facts_stock_lock ON metric_facts;
        DROP FUNCTION IF EXISTS lock_metric_fact_stock_mutation();
        """
    )
