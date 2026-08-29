"""Give formulas an explicit canonical output key.

Revision ID: 20260828380000
Revises: 20260828370000
Create Date: 2026-08-29 14:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828380000"
down_revision = "20260828370000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("formulas", sa.Column("output_key", sa.String(), nullable=True))
    op.add_column(
        "calculated_runs",
        sa.Column("output_key_snapshot", sa.String(), nullable=True),
    )
    op.execute(
        """
        UPDATE formulas
           SET output_key = trim(
               both '_' from regexp_replace(
                   lower(btrim(name)), '[^a-z0-9]+', '_', 'g'
               )
           )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_formula_run_lineage_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'formula calculation runs are retained lineage';
            END IF;
            IF to_jsonb(NEW) - 'is_dirty' - 'updated_at' - 'output_key_snapshot'
               IS DISTINCT FROM
               to_jsonb(OLD) - 'is_dirty' - 'updated_at' - 'output_key_snapshot'
               OR NOT (
                    NEW.output_key_snapshot IS NOT NULL
                    AND OLD.output_key_snapshot IS NULL
                    AND current_setting(
                        'valuepilot.formula_output_key_migration', true
                    ) = 'on'
               ) THEN
                RAISE EXCEPTION 'formula calculation run lineage is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;

        SELECT set_config(
            'valuepilot.formula_output_key_migration', 'on', true
        );

        UPDATE calculated_runs run
           SET output_key_snapshot = lower(replace(formula.name, ' ', '_'))
          FROM formulas formula
         WHERE formula.id = run.formula_id;

        SELECT set_config(
            'valuepilot.formula_output_key_migration', 'off', true
        );

        CREATE OR REPLACE FUNCTION enforce_formula_run_lineage_immutability()
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
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM formulas
                 WHERE output_key IS NULL
                    OR output_key !~ '^[a-z][a-z0-9_]*$'
            ) THEN
                RAISE EXCEPTION
                    'legacy formula name cannot be migrated to canonical output key';
            END IF;
            IF EXISTS (
                SELECT user_id, output_key
                  FROM formulas
                 GROUP BY user_id, output_key
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'legacy formulas collide on canonical output key';
            END IF;
        END;
        $$;
        """
    )
    op.alter_column("calculated_runs", "output_key_snapshot", nullable=False)
    # A formula-v2 fact created before this migration used the legacy
    # lower(replace(name, ' ', '_')) identity. Normalizing punctuation can
    # therefore change the key. Keep the old fact as audit lineage, but never
    # leave it queryable under an identity the migrated formula no longer owns.
    op.execute(
        """
        UPDATE calculated_runs run
           SET is_dirty = true
          FROM formulas formula
         WHERE formula.id = run.formula_id
           AND run.is_dirty = false
           AND EXISTS (
                SELECT 1
                  FROM metric_facts fact
                 WHERE fact.source_type = 'calculated'
                   AND fact.source_ref_id = run.id
                   AND fact.value_json->>'formula_lineage_version' = 'formula-v2'
                   AND fact.metric_key IS DISTINCT FROM formula.output_key
           );

        UPDATE metric_facts fact
           SET is_current = false
          FROM calculated_runs run
          JOIN formulas formula ON formula.id = run.formula_id
         WHERE fact.source_type = 'calculated'
           AND fact.source_ref_id = run.id
           AND fact.value_json->>'formula_lineage_version' = 'formula-v2'
           AND fact.is_current = true
           AND fact.metric_key IS DISTINCT FROM formula.output_key;
        """
    )
    op.alter_column("formulas", "output_key", nullable=False)
    op.create_check_constraint(
        "ck_formulas_output_key_canonical",
        "formulas",
        "output_key ~ '^[a-z][a-z0-9_]*$'",
    )
    op.create_unique_constraint(
        "uq_formulas_user_output_key",
        "formulas",
        ["user_id", "output_key"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_formula_metric_fact_lineage()
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
                      AND NEW.metric_key = run.output_key_snapshot
                      AND (NOT NEW.is_current OR NEW.metric_key = formula.output_key)
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
                             OR (
                                  NEW.is_current
                                  AND EXISTS (
                                      SELECT 1
                                      FROM metric_facts manual_override
                                      WHERE manual_override.user_id = input_fact.user_id
                                        AND manual_override.stock_id = input_fact.stock_id
                                        AND manual_override.metric_key = input_fact.metric_key
                                        AND manual_override.period_type IS NOT DISTINCT FROM input_fact.period_type
                                        AND manual_override.period_end_date IS NOT DISTINCT FROM input_fact.period_end_date
                                        AND manual_override.as_of_date IS NOT DISTINCT FROM input_fact.as_of_date
                                        AND manual_override.source_type = 'manual'
                                        AND manual_override.is_current = true
                                        AND manual_override.id <> input_fact.id
                                  )
                             )
                      )
                      AND (NOT NEW.is_current OR run.is_dirty = false)
               ) THEN
                RAISE EXCEPTION
                    'formula metric fact lacks exact current input lineage';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM formulas
                 WHERE output_key IS DISTINCT FROM lower(replace(name, ' ', '_'))
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade explicit formula output keys';
            END IF;
        END;
        $$;

        CREATE OR REPLACE FUNCTION validate_formula_metric_fact_lineage()
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
                             OR (
                                  NEW.is_current
                                  AND EXISTS (
                                      SELECT 1
                                      FROM metric_facts manual_override
                                      WHERE manual_override.user_id = input_fact.user_id
                                        AND manual_override.stock_id = input_fact.stock_id
                                        AND manual_override.metric_key = input_fact.metric_key
                                        AND manual_override.period_type IS NOT DISTINCT FROM input_fact.period_type
                                        AND manual_override.period_end_date IS NOT DISTINCT FROM input_fact.period_end_date
                                        AND manual_override.as_of_date IS NOT DISTINCT FROM input_fact.as_of_date
                                        AND manual_override.source_type = 'manual'
                                        AND manual_override.is_current = true
                                        AND manual_override.id <> input_fact.id
                                  )
                             )
                      )
                      AND (NOT NEW.is_current OR run.is_dirty = false)
               ) THEN
                RAISE EXCEPTION
                    'formula metric fact lacks exact current input lineage';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.drop_constraint("uq_formulas_user_output_key", "formulas", type_="unique")
    op.drop_constraint(
        "ck_formulas_output_key_canonical", "formulas", type_="check"
    )
    op.drop_column("calculated_runs", "output_key_snapshot")
    op.drop_column("formulas", "output_key")
