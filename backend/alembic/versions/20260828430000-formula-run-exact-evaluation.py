"""Validate formula runs from exact inputs and a database-evaluable AST.

Revision ID: 20260828430000
Revises: 20260828420000
Create Date: 2026-08-29 19:00:00
"""

from alembic import op


revision = "20260828430000"
down_revision = "20260828420000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
                    OR NEW.dependencies_json::jsonb IS DISTINCT FROM
                       OLD.dependencies_json::jsonb
                    OR NEW.compiled_ast_json::jsonb IS DISTINCT FROM
                       OLD.compiled_ast_json::jsonb
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

        CREATE FUNCTION formula_ast_variables(node jsonb)
        RETURNS text[]
        LANGUAGE plpgsql
        IMMUTABLE
        AS $$
        DECLARE
            node_type text := node->>'type';
        BEGIN
            IF node_type = 'number' THEN
                RETURN ARRAY[]::text[];
            ELSIF node_type = 'variable' THEN
                IF NULLIF(node->>'name', '') IS NULL THEN
                    RAISE EXCEPTION 'formula AST variable requires a name';
                END IF;
                RETURN ARRAY[node->>'name'];
            ELSIF node_type = 'unary' THEN
                IF node->>'operator' <> 'negate' THEN
                    RAISE EXCEPTION 'unsupported formula AST unary operator';
                END IF;
                RETURN formula_ast_variables(node->'operand');
            ELSIF node_type = 'binary' THEN
                IF node->>'operator' NOT IN (
                    'add', 'subtract', 'multiply', 'divide', 'power'
                ) THEN
                    RAISE EXCEPTION 'unsupported formula AST binary operator';
                END IF;
                RETURN formula_ast_variables(node->'left')
                    || formula_ast_variables(node->'right');
            END IF;
            RAISE EXCEPTION 'unsupported formula AST node';
        END;
        $$;

        CREATE FUNCTION evaluate_formula_ast(node jsonb, bindings jsonb)
        RETURNS numeric
        LANGUAGE plpgsql
        IMMUTABLE
        AS $$
        DECLARE
            node_type text := node->>'type';
            operator_name text;
            left_value numeric;
            right_value numeric;
            variable_name text;
        BEGIN
            IF node_type = 'number' THEN
                IF jsonb_typeof(node->'value') <> 'number' THEN
                    RAISE EXCEPTION 'formula AST constant must be numeric';
                END IF;
                RETURN (node->>'value')::numeric;
            ELSIF node_type = 'variable' THEN
                variable_name := node->>'name';
                IF variable_name IS NULL OR NOT bindings ? variable_name THEN
                    RAISE EXCEPTION 'formula AST input is missing';
                END IF;
                RETURN (bindings->>variable_name)::numeric;
            ELSIF node_type = 'unary' THEN
                IF node->>'operator' <> 'negate' THEN
                    RAISE EXCEPTION 'unsupported formula AST unary operator';
                END IF;
                RETURN -evaluate_formula_ast(node->'operand', bindings);
            ELSIF node_type = 'binary' THEN
                operator_name := node->>'operator';
                left_value := evaluate_formula_ast(node->'left', bindings);
                right_value := evaluate_formula_ast(node->'right', bindings);
                IF operator_name = 'add' THEN
                    RETURN left_value + right_value;
                ELSIF operator_name = 'subtract' THEN
                    RETURN left_value - right_value;
                ELSIF operator_name = 'multiply' THEN
                    RETURN left_value * right_value;
                ELSIF operator_name = 'divide' THEN
                    RETURN left_value / right_value;
                ELSIF operator_name = 'power' THEN
                    RETURN power(left_value, right_value);
                END IF;
                RAISE EXCEPTION 'unsupported formula AST binary operator';
            END IF;
            RAISE EXCEPTION 'unsupported formula AST node';
        END;
        $$;

        CREATE FUNCTION render_formula_ast(node jsonb)
        RETURNS text
        LANGUAGE plpgsql
        IMMUTABLE
        AS $$
        DECLARE
            node_type text := node->>'type';
            operator_symbol text;
        BEGIN
            IF node_type = 'number' THEN
                IF jsonb_typeof(node->'value') <> 'number' THEN
                    RAISE EXCEPTION 'formula AST constant must be numeric';
                END IF;
                RETURN node->>'value';
            ELSIF node_type = 'variable' THEN
                IF NULLIF(node->>'name', '') IS NULL THEN
                    RAISE EXCEPTION 'formula AST variable requires a name';
                END IF;
                RETURN node->>'name';
            ELSIF node_type = 'unary' AND node->>'operator' = 'negate' THEN
                RETURN '(-' || render_formula_ast(node->'operand') || ')';
            ELSIF node_type = 'binary' THEN
                operator_symbol := CASE node->>'operator'
                    WHEN 'add' THEN '+'
                    WHEN 'subtract' THEN '-'
                    WHEN 'multiply' THEN '*'
                    WHEN 'divide' THEN '/'
                    WHEN 'power' THEN '**'
                    ELSE NULL
                END;
                IF operator_symbol IS NULL THEN
                    RAISE EXCEPTION 'unsupported formula AST binary operator';
                END IF;
                RETURN '(' || render_formula_ast(node->'left') || ' '
                    || operator_symbol || ' '
                    || render_formula_ast(node->'right') || ')';
            END IF;
            RAISE EXCEPTION 'unsupported formula AST node';
        END;
        $$;

        -- The renderer is now the presentation authority for the same AST
        -- that the database evaluates. Canonicalize legacy expressions inside
        -- this one migration transaction, then immediately restore the
        -- published-definition trigger.
        DROP TRIGGER IF EXISTS trg_formulas_published_definition_immutable
            ON formulas;
        UPDATE formulas
           SET expression = render_formula_ast(
               compiled_ast_json::jsonb->'root'
           )
         WHERE compiled_ast_json IS NOT NULL
           AND compiled_ast_json::jsonb->>'version' = 'formula-ast-v1'
           AND expression IS DISTINCT FROM render_formula_ast(
               compiled_ast_json::jsonb->'root'
           );
        CREATE TRIGGER trg_formulas_published_definition_immutable
        BEFORE UPDATE OR DELETE ON formulas
        FOR EACH ROW EXECUTE FUNCTION guard_published_formula_definition();

        CREATE FUNCTION validate_formula_run_exact_evaluation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            formula_row formulas%ROWTYPE;
            dependency_keys text[];
            ast_keys text[];
            input_keys text[];
            bindings jsonb;
            input_count integer;
            calculated_value numeric;
            recorded_value numeric;
        BEGIN
            SELECT * INTO formula_row
              FROM formulas
             WHERE id = NEW.formula_id;
            IF formula_row.id IS NULL
               OR formula_row.user_id IS DISTINCT FROM NEW.user_id
               OR formula_row.output_key IS DISTINCT FROM NEW.output_key_snapshot
               OR formula_row.compiled_ast_json IS NULL
               OR formula_row.compiled_ast_json::jsonb->>'version'
                  <> 'formula-ast-v1'
               OR formula_row.expression IS DISTINCT FROM render_formula_ast(
                   formula_row.compiled_ast_json::jsonb->'root'
               )
               OR NEW.is_dirty IS DISTINCT FROM false
               OR jsonb_typeof(NEW.input_fact_ids_json) <> 'array'
               OR jsonb_array_length(NEW.input_fact_ids_json) = 0
               OR jsonb_typeof(NEW.result_value_json::jsonb->'value') <> 'number' THEN
                RAISE EXCEPTION 'formula run requires canonical execution identity'
                    USING ERRCODE = '23514';
            END IF;

            SELECT array_agg(DISTINCT item ORDER BY item)
              INTO dependency_keys
              FROM jsonb_array_elements_text(
                  formula_row.dependencies_json::jsonb
              ) item;
            SELECT array_agg(DISTINCT item ORDER BY item)
              INTO ast_keys
              FROM unnest(
                  formula_ast_variables(
                      formula_row.compiled_ast_json::jsonb->'root'
                  )
              ) item;
            IF dependency_keys IS DISTINCT FROM ast_keys THEN
                RAISE EXCEPTION 'formula dependencies do not match canonical AST'
                    USING ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1 FROM jsonb_array_elements(NEW.input_fact_ids_json) item
                 WHERE jsonb_typeof(item) <> 'number'
            ) THEN
                RAISE EXCEPTION 'formula input identities must be numeric'
                    USING ERRCODE = '23514';
            END IF;

            SELECT count(*),
                   array_agg(DISTINCT fact.metric_key ORDER BY fact.metric_key),
                   jsonb_object_agg(
                       fact.metric_key, to_jsonb(fact.value_numeric)
                   )
              INTO input_count, input_keys, bindings
              FROM jsonb_array_elements_text(
                       NEW.input_fact_ids_json
                   ) input_id
              JOIN metric_facts fact ON fact.id = input_id::bigint
             WHERE fact.user_id = NEW.user_id
               AND fact.stock_id = NEW.stock_id
               AND fact.is_current = true
               AND fact.value_numeric IS NOT NULL
               AND fact.period IS NOT DISTINCT FROM NEW.period
               AND fact.period_type IS NOT DISTINCT FROM NEW.period_type
               AND fact.period_end_date IS NOT DISTINCT FROM NEW.period_end_date
               AND fact.as_of_date IS NOT DISTINCT FROM NEW.as_of_date
               AND (
                   (
                       fact.source_type = 'manual'
                       AND (
                           fact.source_document_id IS NULL
                           OR EXISTS (
                               SELECT 1
                                 FROM pdf_documents document
                                 JOIN metric_extractions extraction
                                   ON extraction.id = fact.source_ref_id
                                WHERE document.id = fact.source_document_id
                                  AND document.user_id = fact.user_id
                                  AND (
                                      document.stock_id IS NULL
                                      OR document.stock_id = fact.stock_id
                                  )
                                  AND document.lifecycle_state = 'active'
                                  AND extraction.user_id = fact.user_id
                                  AND extraction.document_id = document.id
                                  AND extraction.parse_generation =
                                      document.current_parse_generation
                           )
                       )
                   ) OR (
                       fact.source_type = 'parsed'
                       AND parsed_metric_fact_has_exact_authority(fact.id)
                       AND NOT EXISTS (
                           SELECT 1 FROM metric_facts manual_override
                            WHERE manual_override.user_id = fact.user_id
                              AND manual_override.stock_id = fact.stock_id
                              AND manual_override.metric_key = fact.metric_key
                              AND manual_override.period_type IS NOT DISTINCT FROM
                                  fact.period_type
                              AND manual_override.period_end_date IS NOT DISTINCT FROM
                                  fact.period_end_date
                              AND manual_override.as_of_date IS NOT DISTINCT FROM
                                  fact.as_of_date
                              AND manual_override.source_type = 'manual'
                              AND manual_override.is_current = true
                       )
                   ) OR (
                       fact.source_type = 'calculated'
                       AND fact.value_json->>'formula_lineage_version' = 'formula-v2'
                       AND EXISTS (
                           SELECT 1 FROM calculated_runs input_run
                            WHERE input_run.id = fact.source_ref_id
                              AND input_run.user_id = fact.user_id
                              AND input_run.stock_id = fact.stock_id
                              AND input_run.is_dirty = false
                       )
                   )
               );

            IF input_count <> jsonb_array_length(NEW.input_fact_ids_json)
               OR input_count <> cardinality(dependency_keys)
               OR input_keys IS DISTINCT FROM dependency_keys THEN
                RAISE EXCEPTION
                    'formula run inputs must exactly match dependencies and period slot'
                    USING ERRCODE = '23514';
            END IF;

            calculated_value := evaluate_formula_ast(
                formula_row.compiled_ast_json::jsonb->'root', bindings
            );
            recorded_value := (
                NEW.result_value_json::jsonb->>'value'
            )::numeric;
            IF abs(calculated_value - recorded_value)
               > 0.000000001 * greatest(1, abs(calculated_value)) THEN
                RAISE EXCEPTION 'formula run result does not match exact evaluation'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_calculated_runs_exact_evaluation
        BEFORE INSERT ON calculated_runs
        FOR EACH ROW EXECUTE FUNCTION validate_formula_run_exact_evaluation();

        -- Runs created before this validator cannot prove that the stored
        -- result came from exact evaluation. Retain their lineage but retire
        -- every prior output fail-closed; a new run must pass this trigger.
        UPDATE calculated_runs
           SET is_dirty = true
         WHERE is_dirty = false;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM calculated_runs) THEN
                RAISE EXCEPTION
                    'cannot remove formula exact-evaluation guard while runs exist';
            END IF;
        END;
        $$;
        DROP TRIGGER IF EXISTS trg_calculated_runs_exact_evaluation
            ON calculated_runs;
        DROP FUNCTION IF EXISTS validate_formula_run_exact_evaluation();
        DROP FUNCTION IF EXISTS render_formula_ast(jsonb);
        DROP FUNCTION IF EXISTS evaluate_formula_ast(jsonb, jsonb);
        DROP FUNCTION IF EXISTS formula_ast_variables(jsonb);
        """
    )
