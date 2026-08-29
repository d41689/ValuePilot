"""Protect published formula identity and definition.

Revision ID: 20260828390000
Revises: 20260828380000
Create Date: 2026-08-29 15:00:00
"""

from alembic import op


revision = "20260828390000"
down_revision = "20260828380000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_published_formula_definition()
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

        CREATE TRIGGER trg_formulas_published_definition_immutable
        BEFORE UPDATE OR DELETE ON formulas
        FOR EACH ROW EXECUTE FUNCTION guard_published_formula_definition();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM calculated_runs) THEN
                RAISE EXCEPTION
                    'cannot downgrade formula definition guard while runs exist';
            END IF;
        END;
        $$;
        DROP TRIGGER IF EXISTS trg_formulas_published_definition_immutable
            ON formulas;
        DROP FUNCTION IF EXISTS guard_published_formula_definition();
        """
    )
