"""Keep canonical slot identity immutable without blocking manual provenance moves.

Revision ID: 20260904250000
Revises: 20260904240000
"""

from alembic import op


revision = "20260904250000"
down_revision = "20260904240000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP TRIGGER trg_metric_fact_slot_identity_immutable ON metric_facts;
        DROP FUNCTION guard_metric_fact_slot_identity();

        CREATE FUNCTION guard_metric_fact_slot_identity()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF ROW(
               OLD.user_id,OLD.stock_id,OLD.metric_key,OLD.source_type,
               OLD.source_ref_id,OLD.period_type,OLD.period_end_date,OLD.as_of_date
             ) IS DISTINCT FROM ROW(
               NEW.user_id,NEW.stock_id,NEW.metric_key,NEW.source_type,
               NEW.source_ref_id,NEW.period_type,NEW.period_end_date,NEW.as_of_date
             ) OR (
               OLD.source_type='parsed'
               AND OLD.source_document_id IS DISTINCT FROM NEW.source_document_id
             )
          THEN
            RAISE EXCEPTION 'metric fact canonical slot identity is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_zz_metric_fact_slot_identity_immutable
        BEFORE UPDATE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION guard_metric_fact_slot_identity();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER trg_zz_metric_fact_slot_identity_immutable ON metric_facts;
        DROP FUNCTION guard_metric_fact_slot_identity();

        CREATE FUNCTION guard_metric_fact_slot_identity()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF ROW(
               OLD.user_id,OLD.stock_id,OLD.metric_key,OLD.source_type,
               OLD.source_document_id,OLD.source_ref_id,OLD.period_type,
               OLD.period_end_date,OLD.as_of_date
             ) IS DISTINCT FROM ROW(
               NEW.user_id,NEW.stock_id,NEW.metric_key,NEW.source_type,
               NEW.source_document_id,NEW.source_ref_id,NEW.period_type,
               NEW.period_end_date,NEW.as_of_date
             )
          THEN
            RAISE EXCEPTION 'metric fact canonical slot identity is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_metric_fact_slot_identity_immutable
        BEFORE UPDATE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION guard_metric_fact_slot_identity();
        """
    )
