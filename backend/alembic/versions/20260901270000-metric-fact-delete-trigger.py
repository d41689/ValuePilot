"""Allow non-SEC metric-fact deletion without weakening SEC append-only facts.

Revision ID: 20260901270000
Revises: 20260901260000
"""

from alembic import op


revision = "20260901270000"
down_revision = "20260901260000"
branch_labels = None
depends_on = None


_GUARD_BODY = """
CREATE OR REPLACE FUNCTION guard_sec_metric_fact_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  IF OLD.source_type='sec' AND NOT (TG_OP='UPDATE' AND OLD.is_current=true
    AND NEW.is_current=false
    AND ROW(OLD.id,OLD.user_id,OLD.stock_id,OLD.metric_key,OLD.value_json,
      OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,
      OLD.period_type,OLD.period_end_date,OLD.as_of_date,OLD.source_document_id,
      OLD.source_type,OLD.source_ref_id,OLD.created_at)
    IS NOT DISTINCT FROM ROW(NEW.id,NEW.user_id,NEW.stock_id,NEW.metric_key,
      NEW.value_json,NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,
      NEW.period,NEW.period_type,NEW.period_end_date,NEW.as_of_date,
      NEW.source_document_id,NEW.source_type,NEW.source_ref_id,NEW.created_at))
  THEN
    RAISE EXCEPTION 'SEC metric fact is append-only except current demotion';
  END IF;
  IF TG_OP='DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END $$;
"""


_LEGACY_GUARD_BODY = _GUARD_BODY.replace(
    "  IF TG_OP='DELETE' THEN\n    RETURN OLD;\n  END IF;\n  RETURN NEW;",
    "  RETURN NEW;",
)


def upgrade() -> None:
    op.execute(_GUARD_BODY)


def downgrade() -> None:
    op.execute(_LEGACY_GUARD_BODY)
