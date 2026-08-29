"""Revalidate formula publication identity on already-upgraded databases.

Revision ID: 20260828400000
Revises: 20260828390000
Create Date: 2026-08-29 16:00:00
"""

from alembic import op


revision = "20260828400000"
down_revision = "20260828390000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The conditional add repairs development databases that applied the
    # unshipped 3800 revision before output-key snapshots were added. Fresh
    # databases already have the column from 3800.
    op.execute(
        """
        ALTER TABLE calculated_runs
            ADD COLUMN IF NOT EXISTS output_key_snapshot varchar;

        DO $$
        BEGIN
            IF EXISTS (
                SELECT run.id
                FROM calculated_runs run
                JOIN metric_facts fact
                  ON fact.source_type = 'calculated'
                 AND fact.source_ref_id = run.id
                 AND fact.value_json->>'formula_lineage_version' = 'formula-v2'
                WHERE run.output_key_snapshot IS NULL
                GROUP BY run.id
                HAVING count(DISTINCT fact.metric_key) > 1
            ) THEN
                RAISE EXCEPTION
                    'formula run has ambiguous historical output identity';
            END IF;
        END;
        $$;

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
               OR (
                    NEW.output_key_snapshot IS DISTINCT FROM OLD.output_key_snapshot
                    AND NOT (
                        OLD.output_key_snapshot IS NULL
                        AND NEW.output_key_snapshot IS NOT NULL
                        AND current_setting(
                            'valuepilot.formula_output_key_migration', true
                        ) = 'on'
                    )
               ) THEN
                RAISE EXCEPTION 'formula calculation run lineage is immutable';
            END IF;
            IF OLD.is_dirty = true AND NEW.is_dirty = false THEN
                RAISE EXCEPTION 'dirty formula calculation runs cannot be restored';
            END IF;
            RETURN NEW;
        END;
        $$;

        SELECT set_config(
            'valuepilot.formula_output_key_migration', 'on', true
        );

        UPDATE calculated_runs run
           SET output_key_snapshot = COALESCE(
               (
                   SELECT fact.metric_key
                   FROM metric_facts fact
                   WHERE fact.source_type = 'calculated'
                     AND fact.source_ref_id = run.id
                     AND fact.value_json->>'formula_lineage_version' = 'formula-v2'
                   ORDER BY fact.id
                   LIMIT 1
               ),
               formula.output_key
           )
          FROM formulas formula
         WHERE formula.id = run.formula_id
           AND run.output_key_snapshot IS NULL;

        SELECT set_config(
            'valuepilot.formula_output_key_migration', 'off', true
        );

        ALTER TABLE calculated_runs
            ALTER COLUMN output_key_snapshot SET NOT NULL;

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
                  AND fact.is_current = true
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

        CREATE OR REPLACE FUNCTION guard_published_formula_definition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND EXISTS (
                SELECT 1 FROM calculated_runs WHERE formula_id = OLD.id
            ) THEN
                RAISE EXCEPTION
                    'published formula definitions are retained lineage';
            END IF;
            IF TG_OP = 'UPDATE'
               AND (
                    NEW.user_id IS DISTINCT FROM OLD.user_id
                    OR NEW.output_key IS DISTINCT FROM OLD.output_key
                    OR NEW.expression IS DISTINCT FROM OLD.expression
                    OR NEW.dependencies_json IS DISTINCT FROM OLD.dependencies_json
                    OR NEW.compiled_ast_json IS DISTINCT FROM OLD.compiled_ast_json
               )
               AND EXISTS (
                    SELECT 1 FROM calculated_runs WHERE formula_id = OLD.id
               ) THEN
                RAISE EXCEPTION
                    'published formula identity and definition are immutable';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM metric_facts fact
                JOIN calculated_runs run ON run.id = fact.source_ref_id
                JOIN formulas formula ON formula.id = run.formula_id
                WHERE fact.source_type = 'calculated'
                  AND fact.value_json->>'formula_lineage_version' = 'formula-v2'
                  AND fact.is_current = true
                  AND (
                       fact.metric_key IS DISTINCT FROM run.output_key_snapshot
                       OR fact.metric_key IS DISTINCT FROM formula.output_key
                       OR run.is_dirty = true
                  )
            ) THEN
                RAISE EXCEPTION
                    'current formula fact remains detached from publication identity';
            END IF;
        END;
        $$;
        """
    )


def downgrade() -> None:
    # Revision 3800 owns the snapshot column and validators. This remediation
    # only revalidates already-upgraded databases, so downgrade has no schema
    # delta to reverse.
    pass
