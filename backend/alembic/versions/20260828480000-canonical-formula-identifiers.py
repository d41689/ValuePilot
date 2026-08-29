"""Allow formulas to bind canonical dotted metric keys safely.

Revision ID: 20260828480000
Revises: 20260828470000
Create Date: 2026-08-29 23:00:00
"""

from alembic import op


revision = "20260828480000"
down_revision = "20260828470000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION formula_ast_variables(node jsonb)
        RETURNS text[]
        LANGUAGE plpgsql
        IMMUTABLE
        AS $$
        DECLARE
            node_type text := node->>'type';
            variable_name text;
        BEGIN
            IF node_type = 'number' THEN
                RETURN ARRAY[]::text[];
            ELSIF node_type = 'variable' THEN
                variable_name := node->>'name';
                IF variable_name IS NULL
                   OR variable_name !~
                      '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
                    RAISE EXCEPTION
                        'formula AST variable requires a canonical metric key';
                END IF;
                RETURN ARRAY[variable_name];
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

        CREATE OR REPLACE FUNCTION render_formula_ast(node jsonb)
        RETURNS text
        LANGUAGE plpgsql
        IMMUTABLE
        AS $$
        DECLARE
            node_type text := node->>'type';
            operator_symbol text;
            variable_name text;
        BEGIN
            IF node_type = 'number' THEN
                IF jsonb_typeof(node->'value') <> 'number' THEN
                    RAISE EXCEPTION 'formula AST constant must be numeric';
                END IF;
                RETURN node->>'value';
            ELSIF node_type = 'variable' THEN
                variable_name := node->>'name';
                IF variable_name IS NULL
                   OR variable_name !~
                      '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$' THEN
                    RAISE EXCEPTION
                        'formula AST variable requires a canonical metric key';
                END IF;
                RETURN 'metric(' || to_jsonb(variable_name)::text || ')';
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
        """
    )


def downgrade() -> None:
    op.execute(
        r"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM formulas formula
                 WHERE formula.compiled_ast_json IS NOT NULL
                   AND EXISTS (
                       SELECT 1
                         FROM unnest(
                             formula_ast_variables(
                                 formula.compiled_ast_json::jsonb->'root'
                             )
                         ) variable_name
                        WHERE variable_name LIKE '%.%'
                   )
            ) THEN
                RAISE EXCEPTION
                    'cannot remove canonical formula identifiers while dotted dependencies exist';
            END IF;
        END;
        $$;

        CREATE OR REPLACE FUNCTION formula_ast_variables(node jsonb)
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

        CREATE OR REPLACE FUNCTION render_formula_ast(node jsonb)
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

        DROP TRIGGER IF EXISTS trg_formulas_published_definition_immutable
            ON formulas;
        UPDATE formulas
           SET expression = render_formula_ast(
               compiled_ast_json::jsonb->'root'
           )
         WHERE compiled_ast_json IS NOT NULL
           AND compiled_ast_json::jsonb->>'version' = 'formula-ast-v1';
        CREATE TRIGGER trg_formulas_published_definition_immutable
        BEFORE UPDATE OR DELETE ON formulas
        FOR EACH ROW EXECUTE FUNCTION guard_published_formula_definition();
        """
    )
