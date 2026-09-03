"""Authorize append-only SEC parser v2.7 repeated-anchor identity.

Revision ID: 20260901260000
Revises: 20260901250000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901260000"
down_revision = "20260901250000"
branch_labels = None
depends_on = None


V24 = "xbrl-lineage-v2.4"
V25 = "xbrl-lineage-v2.5"
V26 = "xbrl-lineage-v2.6"
V27 = "xbrl-lineage-v2.7"


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
          RAISE EXCEPTION 'parser-v2.7 guard function source mismatch: %', function_name;
        END IF;
        EXECUTE replace(definition,{old_sql},{new_sql});
      END LOOP;
    END $$;
    """)


def _replacement_fragments() -> dict[str, str]:
    old_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1','xbrl-lineage-v2.2',"
        "'xbrl-lineage-v2.3','xbrl-lineage-v2.4','xbrl-lineage-v2.5',"
        "'xbrl-lineage-v2.6']"
    )
    new_versions = old_versions[:-1] + ",'xbrl-lineage-v2.7']"
    old_generated = (
        "run.parser_version=ANY (ARRAY['xbrl-lineage-v2.2',"
        "'xbrl-lineage-v2.3','xbrl-lineage-v2.4','xbrl-lineage-v2.5',"
        "'xbrl-lineage-v2.6'])"
    )
    new_generated = old_generated[:-2] + ",'xbrl-lineage-v2.7'])"
    old_classifier = (
        f"expected_type:=CASE WHEN run.parser_version='{V26}' THEN "
        "sec_statement_type_v26(NEW.statement_role)"
    )
    new_classifier = (
        f"expected_type:=CASE WHEN run.parser_version=ANY (ARRAY['{V26}','{V27}']) "
        "THEN sec_statement_type_v26(NEW.statement_role)"
    )
    old_role = f"run.parser_version='{V26}' AND\n      (expected_type IS NULL"
    new_role = (
        f"run.parser_version=ANY (ARRAY['{V26}','{V27}']) AND\n"
        "      (expected_type IS NULL"
    )
    old_period = f"""OR (run.parser_version=ANY (ARRAY['{V25}','{V26}']) AND
              NEW.locator_json->'period_start' IS DISTINCT FROM
                coalesce(to_jsonb(fact.period_start::text),'null'::jsonb))
           OR (run.parser_version<>ALL (ARRAY['{V25}','{V26}']) AND
              NEW.locator_json->>'period_start' IS DISTINCT FROM
                coalesce(fact.period_start::text,''))"""
    new_period = f"""OR (run.parser_version=ANY (ARRAY['{V25}','{V26}','{V27}']) AND
              NEW.locator_json->'period_start' IS DISTINCT FROM
                coalesce(to_jsonb(fact.period_start::text),'null'::jsonb))
           OR (run.parser_version<>ALL (ARRAY['{V25}','{V26}','{V27}']) AND
              NEW.locator_json->>'period_start' IS DISTINCT FROM
                coalesce(fact.period_start::text,''))"""
    old_recorded_count = (
        f"run.parser_version=ANY (ARRAY['{V24}','{V25}','{V26}'])"
    )
    new_recorded_count = (
        f"run.parser_version=ANY (ARRAY['{V24}','{V25}','{V26}','{V27}'])"
    )
    old_v26_exact = f"run.parser_version='{V26}'"
    new_v26_exact = f"run.parser_version=ANY (ARRAY['{V26}','{V27}'])"
    old_row_label = f"run.parser_version<>'{V26}'"
    new_row_label = f"run.parser_version<>ALL (ARRAY['{V26}','{V27}'])"
    old_legacy_unique = (
        f"run.parser_version<>ALL (ARRAY['{V24}','{V25}'])"
    )
    # Preserve the terminal v2.6 meaning. Only v2.7 uses the exact recorded
    # occurrence count rather than the legacy whole-report uniqueness rule.
    new_legacy_unique = (
        f"run.parser_version<>ALL (ARRAY['{V24}','{V25}','{V27}'])"
    )
    return locals()


def upgrade() -> None:
    fragments = _replacement_fragments()
    _replace_function_source(
        (
            "validate_sec_parser_v2_structured_unit",
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
        ),
        fragments["old_versions"],
        fragments["new_versions"],
    )
    _replace_function_source(
        (
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
            "guard_sec_statement_occurrence_insert",
        ),
        fragments["old_generated"],
        fragments["new_generated"],
    )
    _replace_function_source(
        ("guard_sec_statement_report_reference_insert",),
        fragments["old_classifier"],
        fragments["new_classifier"],
    )
    _replace_function_source(
        ("guard_sec_statement_report_reference_insert",),
        fragments["old_role"],
        fragments["new_role"],
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        fragments["old_period"],
        fragments["new_period"],
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        fragments["old_recorded_count"],
        fragments["new_recorded_count"],
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        fragments["old_legacy_unique"],
        fragments["new_legacy_unique"],
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        fragments["old_row_label"],
        fragments["new_row_label"],
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        fragments["old_v26_exact"],
        fragments["new_v26_exact"],
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_financial_parse_runs, sec_statement_fact_authorities, "
        "sec_statement_occurrence_evidence, sec_statement_report_references "
        "IN ACCESS EXCLUSIVE MODE"
    )
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM sec_financial_parse_runs WHERE parser_version=:version"
    ), {"version": V27}).scalar_one()
    if count:
        raise RuntimeError("downgrade refused: retained parser-v2.7 lineage exists")
    fragments = _replacement_fragments()
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        fragments["new_v26_exact"],
        fragments["old_v26_exact"],
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        fragments["new_row_label"],
        fragments["old_row_label"],
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        fragments["new_legacy_unique"],
        fragments["old_legacy_unique"],
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        fragments["new_recorded_count"],
        fragments["old_recorded_count"],
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        fragments["new_period"],
        fragments["old_period"],
    )
    _replace_function_source(
        ("guard_sec_statement_report_reference_insert",),
        fragments["new_role"],
        fragments["old_role"],
    )
    _replace_function_source(
        ("guard_sec_statement_report_reference_insert",),
        fragments["new_classifier"],
        fragments["old_classifier"],
    )
    _replace_function_source(
        (
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
            "guard_sec_statement_occurrence_insert",
        ),
        fragments["new_generated"],
        fragments["old_generated"],
    )
    _replace_function_source(
        (
            "validate_sec_parser_v2_structured_unit",
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
        ),
        fragments["new_versions"],
        fragments["old_versions"],
    )
