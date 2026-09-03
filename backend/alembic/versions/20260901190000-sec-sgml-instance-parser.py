"""Authorize the append-only SEC SGML/instance parser revision.

Revision ID: 20260901190000
Revises: 20260901180000
"""

from alembic import op


revision = "20260901190000"
down_revision = "20260901180000"
branch_labels = None
depends_on = None


def _replace_function_source(functions: list[str], old: str, new: str) -> None:
    names = ",".join(repr(name) for name in functions)
    old_sql = "'" + old.replace("'", "''") + "'"
    new_sql = "'" + new.replace("'", "''") + "'"
    op.execute(
        f"""
        DO $$
        DECLARE function_name text; definition text;
        BEGIN
          FOREACH function_name IN ARRAY ARRAY[{names}] LOOP
            SELECT pg_get_functiondef(p.oid) INTO definition
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname=current_schema() AND p.proname=function_name;
            IF definition IS NULL OR position({old_sql} in definition)=0 THEN
              RAISE EXCEPTION 'parser guard function source mismatch: %', function_name;
            END IF;
            EXECUTE replace(definition, {old_sql}, {new_sql});
          END LOOP;
        END $$;
        """
    )


def upgrade() -> None:
    _replace_function_source(
        ["validate_sec_parser_v2_structured_unit"],
        "parser_version_value = 'xbrl-lineage-v2'",
        "parser_version_value = ANY (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1'])",
    )
    _replace_function_source(
        [
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
        ],
        "run.parser_version<>'xbrl-lineage-v2'",
        "run.parser_version<>ALL (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1'])",
    )


def downgrade() -> None:
    _replace_function_source(
        ["validate_sec_parser_v2_structured_unit"],
        "parser_version_value = ANY (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1'])",
        "parser_version_value = 'xbrl-lineage-v2'",
    )
    _replace_function_source(
        [
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
        ],
        "run.parser_version<>ALL (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1'])",
        "run.parser_version<>'xbrl-lineage-v2'",
    )
