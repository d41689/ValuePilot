"""Authorize append-only SEC parser v2.5 balance/cash-flow authority.

Revision ID: 20260901240000
Revises: 20260901230000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901240000"
down_revision = "20260901230000"
branch_labels = None
depends_on = None


V24 = "xbrl-lineage-v2.4"
V25 = "xbrl-lineage-v2.5"


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
          RAISE EXCEPTION 'parser-v2.5 guard function source mismatch: %', function_name;
        END IF;
        EXECUTE replace(definition,{old_sql},{new_sql});
      END LOOP;
    END $$;
    """)


_OLD_CLASSIFIER = """expected_type:=CASE
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%balance%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%financial position%' THEN 'balance_sheet'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%cash flow%' THEN 'cash_flow'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%comprehensive%' THEN 'comprehensive_income'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%income%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%operations%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%earnings%' THEN 'income_statement'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%equity%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%stockholder%' THEN 'equity' END;"""

_NEW_CLASSIFIER = f"""expected_type:=CASE WHEN run.parser_version='{V25}' THEN CASE
        WHEN btrim(NEW.statement_role)='' THEN NULL
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%balance%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%financial position%' THEN 'balance_sheet'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%cash flow%'
          OR regexp_replace(lower(NEW.statement_role||' '||NEW.report_name),'[^a-z0-9]','','g') LIKE '%statementofcashflows%'
          OR regexp_replace(lower(NEW.statement_role||' '||NEW.report_name),'[^a-z0-9]','','g') LIKE '%statementsofcashflows%' THEN 'cash_flow'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%comprehensive%' THEN 'comprehensive_income'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%income%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%operations%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%earnings%' THEN 'income_statement'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%equity%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%stockholder%' THEN 'equity' END
      ELSE CASE
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%balance%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%financial position%' THEN 'balance_sheet'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%cash flow%' THEN 'cash_flow'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%comprehensive%' THEN 'comprehensive_income'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%income%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%operations%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%earnings%' THEN 'income_statement'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%equity%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%stockholder%' THEN 'equity' END END;"""

_ROLE_GUARD_WITH_V25_OLD_SEMANTICS = """(run.parser_version=ANY (ARRAY['xbrl-lineage-v2.2','xbrl-lineage-v2.3','xbrl-lineage-v2.4','xbrl-lineage-v2.5']) AND (btrim(NEW.statement_role)='' OR lower(NEW.statement_role) !~ '(balance|financial position|cash flow|comprehensive|income|operations|earnings|equity|stockholder)'))"""

_ROLE_GUARD_WITH_V25_COMPACT_CASH_FLOW = """((run.parser_version=ANY (ARRAY['xbrl-lineage-v2.2','xbrl-lineage-v2.3','xbrl-lineage-v2.4']) AND (btrim(NEW.statement_role)='' OR lower(NEW.statement_role) !~ '(balance|financial position|cash flow|comprehensive|income|operations|earnings|equity|stockholder)')) OR (run.parser_version='xbrl-lineage-v2.5' AND (btrim(NEW.statement_role)='' OR (lower(NEW.statement_role) !~ '(balance|financial position|cash flow|comprehensive|income|operations|earnings|equity|stockholder)' AND regexp_replace(lower(NEW.statement_role),'[^a-z0-9]','','g') !~ 'statements?ofcashflows'))))"""


def upgrade() -> None:
    old_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1',"
        "'xbrl-lineage-v2.2','xbrl-lineage-v2.3','xbrl-lineage-v2.4']"
    )
    new_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1',"
        "'xbrl-lineage-v2.2','xbrl-lineage-v2.3','xbrl-lineage-v2.4',"
        "'xbrl-lineage-v2.5']"
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
    old_generated = (
        "run.parser_version=ANY (ARRAY['xbrl-lineage-v2.2',"
        "'xbrl-lineage-v2.3','xbrl-lineage-v2.4'])"
    )
    new_generated = (
        "run.parser_version=ANY (ARRAY['xbrl-lineage-v2.2',"
        "'xbrl-lineage-v2.3','xbrl-lineage-v2.4','xbrl-lineage-v2.5'])"
    )
    _replace_function_source(
        (
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
            "guard_sec_statement_occurrence_insert",
        ),
        old_generated,
        new_generated,
    )
    old_repeat = f"""OR (run.parser_version<>'{V24}' AND
              (length(report_text)-length(replace(
                report_text,NEW.locator_json->>'anchor_start_tag','')))
                / length(NEW.locator_json->>'anchor_start_tag')<>1)
           OR (run.parser_version='{V24}' AND ("""
    new_repeat = f"""OR (run.parser_version<>ALL (ARRAY['{V24}','{V25}']) AND
              (length(report_text)-length(replace(
                report_text,NEW.locator_json->>'anchor_start_tag','')))
                / length(NEW.locator_json->>'anchor_start_tag')<>1)
           OR (run.parser_version=ANY (ARRAY['{V24}','{V25}']) AND ("""
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",), old_repeat, new_repeat
    )
    old_semantic = (
        f"CASE WHEN run.parser_version='{V24}' THEN chr(31)||"
        "coalesce(NEW.locator_json->>'anchor_start_tag_occurrence_count','') "
        "ELSE '' END"
    )
    new_semantic = (
        f"CASE WHEN run.parser_version=ANY (ARRAY['{V24}','{V25}']) THEN chr(31)||"
        "coalesce(NEW.locator_json->>'anchor_start_tag_occurrence_count','') "
        "ELSE '' END"
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",), old_semantic, new_semantic
    )
    old_period_start = (
        "OR NEW.locator_json->>'period_start' IS DISTINCT FROM "
        "coalesce(fact.period_start::text,'')"
    )
    new_period_start = f"""OR (run.parser_version='{V25}' AND
              NEW.locator_json->'period_start' IS DISTINCT FROM
                coalesce(to_jsonb(fact.period_start::text),'null'::jsonb))
           OR (run.parser_version<>'{V25}' AND
              NEW.locator_json->>'period_start' IS DISTINCT FROM
                coalesce(fact.period_start::text,''))"""
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        old_period_start,
        new_period_start,
    )
    _replace_function_source(
        ("guard_sec_statement_report_reference_insert",),
        _OLD_CLASSIFIER,
        _NEW_CLASSIFIER,
    )
    _replace_function_source(
        ("guard_sec_statement_report_reference_insert",),
        _ROLE_GUARD_WITH_V25_OLD_SEMANTICS,
        _ROLE_GUARD_WITH_V25_COMPACT_CASH_FLOW,
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_financial_parse_runs, sec_statement_fact_authorities, "
        "sec_statement_occurrence_evidence, sec_statement_report_references "
        "IN ACCESS EXCLUSIVE MODE"
    )
    count = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM sec_financial_parse_runs "
            "WHERE parser_version=:version"
        ),
        {"version": V25},
    ).scalar_one()
    if count:
        raise RuntimeError("downgrade refused: retained parser-v2.5 lineage exists")
    _replace_function_source(
        ("guard_sec_statement_report_reference_insert",),
        _ROLE_GUARD_WITH_V25_COMPACT_CASH_FLOW,
        _ROLE_GUARD_WITH_V25_OLD_SEMANTICS,
    )
    _replace_function_source(
        ("guard_sec_statement_report_reference_insert",),
        _NEW_CLASSIFIER,
        _OLD_CLASSIFIER,
    )
    old_period_start = (
        "OR NEW.locator_json->>'period_start' IS DISTINCT FROM "
        "coalesce(fact.period_start::text,'')"
    )
    new_period_start = f"""OR (run.parser_version='{V25}' AND
              NEW.locator_json->'period_start' IS DISTINCT FROM
                coalesce(to_jsonb(fact.period_start::text),'null'::jsonb))
           OR (run.parser_version<>'{V25}' AND
              NEW.locator_json->>'period_start' IS DISTINCT FROM
                coalesce(fact.period_start::text,''))"""
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        new_period_start,
        old_period_start,
    )
    old_semantic = (
        f"CASE WHEN run.parser_version='{V24}' THEN chr(31)||"
        "coalesce(NEW.locator_json->>'anchor_start_tag_occurrence_count','') "
        "ELSE '' END"
    )
    new_semantic = (
        f"CASE WHEN run.parser_version=ANY (ARRAY['{V24}','{V25}']) THEN chr(31)||"
        "coalesce(NEW.locator_json->>'anchor_start_tag_occurrence_count','') "
        "ELSE '' END"
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",), new_semantic, old_semantic
    )
    old_repeat = f"""OR (run.parser_version<>'{V24}' AND
              (length(report_text)-length(replace(
                report_text,NEW.locator_json->>'anchor_start_tag','')))
                / length(NEW.locator_json->>'anchor_start_tag')<>1)
           OR (run.parser_version='{V24}' AND ("""
    new_repeat = f"""OR (run.parser_version<>ALL (ARRAY['{V24}','{V25}']) AND
              (length(report_text)-length(replace(
                report_text,NEW.locator_json->>'anchor_start_tag','')))
                / length(NEW.locator_json->>'anchor_start_tag')<>1)
           OR (run.parser_version=ANY (ARRAY['{V24}','{V25}']) AND ("""
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",), new_repeat, old_repeat
    )
    old_generated = (
        "run.parser_version=ANY (ARRAY['xbrl-lineage-v2.2',"
        "'xbrl-lineage-v2.3','xbrl-lineage-v2.4'])"
    )
    new_generated = (
        "run.parser_version=ANY (ARRAY['xbrl-lineage-v2.2',"
        "'xbrl-lineage-v2.3','xbrl-lineage-v2.4','xbrl-lineage-v2.5'])"
    )
    _replace_function_source(
        (
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
            "guard_sec_statement_occurrence_insert",
        ),
        new_generated,
        old_generated,
    )
    old_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1',"
        "'xbrl-lineage-v2.2','xbrl-lineage-v2.3','xbrl-lineage-v2.4']"
    )
    new_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1',"
        "'xbrl-lineage-v2.2','xbrl-lineage-v2.3','xbrl-lineage-v2.4',"
        "'xbrl-lineage-v2.5']"
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
