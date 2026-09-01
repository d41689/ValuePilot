"""Authorize the append-only SEC parser v2.3 revision.

Revision ID: 20260901220000
Revises: 20260901210000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901220000"
down_revision = "20260901210000"
branch_labels = None
depends_on = None


V22 = "xbrl-lineage-v2.2"
V23 = "xbrl-lineage-v2.3"


def _replace_function_source(functions: tuple[str, ...], old: str, new: str) -> None:
    names = ",".join(repr(name) for name in functions)
    old_sql = "'" + old.replace("'", "''") + "'"
    new_sql = "'" + new.replace("'", "''") + "'"
    op.execute(f"""
    DO $$
    DECLARE function_name text; definition text;
    BEGIN
      FOREACH function_name IN ARRAY ARRAY[{names}] LOOP
        SELECT pg_get_functiondef(p.oid) INTO definition
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname=current_schema() AND p.proname=function_name;
        IF definition IS NULL OR position({old_sql} in definition)=0 THEN
          RAISE EXCEPTION 'parser-v2.3 guard function source mismatch: %', function_name;
        END IF;
        EXECUTE replace(definition,{old_sql},{new_sql});
      END LOOP;
    END $$;
    """)


def upgrade() -> None:
    old_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1','xbrl-lineage-v2.2']"
    )
    new_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1',"
        "'xbrl-lineage-v2.2','xbrl-lineage-v2.3']"
    )
    _replace_function_source(
        (
            "validate_sec_parser_v2_structured_unit",
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
        ),
        old_versions,
        new_versions,
    )
    _replace_function_source(
        (
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
            "guard_sec_statement_occurrence_insert",
        ),
        f"run.parser_version='{V22}'",
        f"run.parser_version=ANY (ARRAY['{V22}','{V23}'])",
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_financial_parse_runs, sec_statement_fact_authorities, "
        "sec_statement_occurrence_evidence, sec_statement_report_references "
        "IN ACCESS EXCLUSIVE MODE"
    )
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM sec_financial_parse_runs WHERE parser_version=:version"
    ), {"version": V23}).scalar_one()
    if count:
        raise RuntimeError("downgrade refused: retained parser-v2.3 lineage exists")
    _replace_function_source(
        (
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
            "guard_sec_statement_occurrence_insert",
        ),
        f"run.parser_version=ANY (ARRAY['{V22}','{V23}'])",
        f"run.parser_version='{V22}'",
    )
    old_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1','xbrl-lineage-v2.2']"
    )
    new_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1',"
        "'xbrl-lineage-v2.2','xbrl-lineage-v2.3']"
    )
    _replace_function_source(
        (
            "validate_sec_parser_v2_structured_unit",
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
        ),
        new_versions,
        old_versions,
    )
