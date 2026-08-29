"""Make user formula facts unique, traceable, and fail closed.

Revision ID: 20260828310000
Revises: 20260828300000
Create Date: 2026-08-29 07:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260828310000"
down_revision = "20260828300000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "calculated_runs",
        sa.Column("period_type", sa.String(), nullable=True),
    )
    op.add_column(
        "calculated_runs",
        sa.Column("period_end_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "calculated_runs",
        sa.Column(
            "input_fact_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_calculated_runs_input_fact_ids_array",
        "calculated_runs",
        "jsonb_typeof(input_fact_ids_json) = 'array'",
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_metric_facts_current_formula_period_slot
        ON metric_facts (
            user_id,
            stock_id,
            metric_key,
            coalesce(period_type, ''),
            coalesce(period_end_date, DATE '-infinity')
        )
        WHERE source_type = 'calculated'
          AND is_current = true
          AND value_json->>'formula_lineage_version' = 'formula-v2'
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_formula_run_lineage_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'formula calculation runs are retained lineage';
            END IF;
            IF to_jsonb(NEW) - 'is_dirty' - 'updated_at'
               IS DISTINCT FROM
               to_jsonb(OLD) - 'is_dirty' - 'updated_at' THEN
                RAISE EXCEPTION 'formula calculation run lineage is immutable';
            END IF;
            IF OLD.is_dirty = true AND NEW.is_dirty = false THEN
                RAISE EXCEPTION 'dirty formula calculation runs cannot be restored';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_calculated_runs_lineage_immutable
        BEFORE UPDATE OR DELETE ON calculated_runs
        FOR EACH ROW EXECUTE FUNCTION enforce_formula_run_lineage_immutability();

        CREATE FUNCTION demote_formula_fact_when_run_dirty()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.is_dirty = false AND NEW.is_dirty = true THEN
                UPDATE metric_facts
                   SET is_current = false
                 WHERE source_type = 'calculated'
                   AND source_ref_id = NEW.id
                   AND value_json->>'formula_lineage_version' = 'formula-v2'
                   AND is_current = true;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_calculated_runs_dirty_demotes_fact
        AFTER UPDATE OF is_dirty ON calculated_runs
        FOR EACH ROW EXECUTE FUNCTION demote_formula_fact_when_run_dirty();

        CREATE FUNCTION dirty_formula_runs_for_input_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            changed_input_id bigint;
        BEGIN
            changed_input_id := OLD.id;
            IF TG_OP = 'DELETE' OR (
                OLD.is_current = true AND (
                    NEW.is_current = false OR
                    NEW.value_numeric IS DISTINCT FROM OLD.value_numeric OR
                    NEW.value_json IS DISTINCT FROM OLD.value_json OR
                    NEW.value_text IS DISTINCT FROM OLD.value_text OR
                    NEW.unit IS DISTINCT FROM OLD.unit OR
                    NEW.currency IS DISTINCT FROM OLD.currency OR
                    NEW.period IS DISTINCT FROM OLD.period OR
                    NEW.period_type IS DISTINCT FROM OLD.period_type OR
                    NEW.period_end_date IS DISTINCT FROM OLD.period_end_date OR
                    NEW.as_of_date IS DISTINCT FROM OLD.as_of_date
                )
            ) THEN
                UPDATE calculated_runs
                   SET is_dirty = true
                 WHERE is_dirty = false
                   AND input_fact_ids_json @> jsonb_build_array(changed_input_id);
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;

        CREATE TRIGGER trg_metric_facts_dirty_formula_runs_update
        AFTER UPDATE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION dirty_formula_runs_for_input_change();

        CREATE TRIGGER trg_metric_facts_dirty_formula_runs_delete
        AFTER DELETE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION dirty_formula_runs_for_input_change();

        CREATE FUNCTION enforce_formula_metric_fact_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.source_type = 'calculated'
               AND OLD.value_json->>'formula_lineage_version' = 'formula-v2' THEN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'formula metric facts are retained lineage';
                END IF;
                IF to_jsonb(NEW) - 'is_current' - 'updated_at'
                   IS DISTINCT FROM
                   to_jsonb(OLD) - 'is_current' - 'updated_at' THEN
                    RAISE EXCEPTION 'formula metric fact lineage and value are immutable';
                END IF;
                IF OLD.is_current = false AND NEW.is_current = true THEN
                    RAISE EXCEPTION 'retired formula metric facts cannot be restored';
                END IF;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;

        CREATE TRIGGER trg_metric_facts_formula_immutable
        BEFORE UPDATE OR DELETE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION enforce_formula_metric_fact_immutability();

        CREATE FUNCTION validate_formula_metric_fact_lineage()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type = 'calculated'
               AND NEW.value_json->>'formula_lineage_version' = 'formula-v2'
               AND NOT EXISTS (
                    SELECT 1
                    FROM calculated_runs run
                    JOIN formulas formula ON formula.id = run.formula_id
                    WHERE run.id = NEW.source_ref_id
                      AND run.user_id = NEW.user_id
                      AND run.stock_id = NEW.stock_id
                      AND formula.user_id = NEW.user_id
                      AND NEW.metric_key = lower(replace(formula.name, ' ', '_'))
                      AND NEW.source_document_id IS NULL
                      AND NEW.value_text IS NULL
                      AND NEW.value_json->>'formula_id' = formula.id::text
                      AND NEW.value_json->>'calculated_run_id' = run.id::text
                      AND NEW.value_json->'input_fact_ids' = run.input_fact_ids_json
                      AND (
                          SELECT count(*) FROM jsonb_object_keys(NEW.value_json)
                      ) = 5
                      AND NEW.value_json ?& ARRAY[
                          'value', 'formula_id', 'calculated_run_id',
                          'input_fact_ids', 'formula_lineage_version'
                      ]
                      AND NEW.value_numeric IS NOT DISTINCT FROM
                          (run.result_value_json->>'value')::double precision
                      AND NEW.period IS NOT DISTINCT FROM run.period
                      AND NEW.period_type IS NOT DISTINCT FROM run.period_type
                      AND NEW.period_end_date IS NOT DISTINCT FROM run.period_end_date
                      AND NEW.as_of_date IS NOT DISTINCT FROM run.as_of_date
                      AND jsonb_array_length(run.input_fact_ids_json) > 0
                      AND NOT EXISTS (
                          SELECT 1
                          FROM jsonb_array_elements_text(run.input_fact_ids_json)
                               AS input_id(value)
                          LEFT JOIN metric_facts input_fact
                            ON input_fact.id = input_id.value::bigint
                          WHERE input_fact.id IS NULL
                             OR input_fact.user_id IS DISTINCT FROM NEW.user_id
                             OR input_fact.stock_id <> NEW.stock_id
                             OR (NEW.is_current AND input_fact.is_current = false)
                      )
                      AND (NOT NEW.is_current OR run.is_dirty = false)
               ) THEN
                RAISE EXCEPTION
                    'formula metric fact lacks exact current input lineage';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_formula_lineage
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_formula_metric_fact_lineage();
        """
    )
def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM calculated_runs
                WHERE jsonb_array_length(input_fact_ids_json) > 0
            ) OR EXISTS (
                SELECT 1 FROM metric_facts
                WHERE source_type = 'calculated'
                  AND value_json->>'formula_lineage_version' = 'formula-v2'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade formula fact lineage while versioned history exists';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_formula_lineage ON metric_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_formula_metric_fact_lineage()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_formula_immutable ON metric_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_formula_metric_fact_immutability()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_dirty_formula_runs_delete ON metric_facts"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_dirty_formula_runs_update ON metric_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS dirty_formula_runs_for_input_change()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_calculated_runs_dirty_demotes_fact ON calculated_runs"
    )
    op.execute("DROP FUNCTION IF EXISTS demote_formula_fact_when_run_dirty()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_calculated_runs_lineage_immutable ON calculated_runs"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_formula_run_lineage_immutability()")
    op.execute("DROP INDEX IF EXISTS uq_metric_facts_current_formula_period_slot")
    op.drop_constraint(
        "ck_calculated_runs_input_fact_ids_array",
        "calculated_runs",
        type_="check",
    )
    op.drop_column("calculated_runs", "input_fact_ids_json")
    op.drop_column("calculated_runs", "period_end_date")
    op.drop_column("calculated_runs", "period_type")
