"""Authorize the append-only SEC parser v2.4 revision.

Revision ID: 20260901230000
Revises: 20260901220000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901230000"
down_revision = "20260901220000"
branch_labels = None
depends_on = None


V22 = "xbrl-lineage-v2.2"
V23 = "xbrl-lineage-v2.3"
V24 = "xbrl-lineage-v2.4"

_UNRESOLVED_INPUT_DIRECT_IDENTITY = """OR raw.context_id IS DISTINCT FROM p.context_id OR a.context_id IS DISTINCT FROM p.context_id
        OR raw.period_start IS DISTINCT FROM p.period_start_date
        OR coalesce(raw.period_end,raw.period_instant) IS DISTINCT FROM p.period_end_date
        OR a.statement_period_end IS DISTINCT FROM p.period_end_date
        OR a.fiscal_year IS DISTINCT FROM p.fiscal_year
        OR a.fiscal_quarter_ordinal IS DISTINCT FROM p.fiscal_quarter_ordinal"""

_UNRESOLVED_INPUT_DERIVED_IDENTITY = """OR (
          NOT (p.reason_code LIKE 'unresolved_derived_%'
            OR (p.reason_code='unresolved_value'
              AND jsonb_array_length(p.locator_json->'ordered_input_occurrences')=2))
          AND (raw.context_id IS DISTINCT FROM p.context_id
            OR a.context_id IS DISTINCT FROM p.context_id
            OR raw.period_start IS DISTINCT FROM p.period_start_date
            OR coalesce(raw.period_end,raw.period_instant) IS DISTINCT FROM p.period_end_date
            OR a.statement_period_end IS DISTINCT FROM p.period_end_date
            OR a.fiscal_year IS DISTINCT FROM p.fiscal_year
            OR a.fiscal_quarter_ordinal IS DISTINCT FROM p.fiscal_quarter_ordinal))
        OR ((p.reason_code LIKE 'unresolved_derived_%'
            OR (p.reason_code='unresolved_value'
              AND jsonb_array_length(p.locator_json->'ordered_input_occurrences')=2))
          AND (jsonb_array_length(p.locator_json->'ordered_input_occurrences')<>2
            OR p.period_type<>'Q' OR p.period_basis<>'duration'
            OR p.fiscal_quarter_ordinal NOT IN (2,3,4)
            OR p.period_start_date IS NULL
            OR p.period_end_date-p.period_start_date+1 NOT BETWEEN 70 AND 110
            OR NEW.input_ordinal NOT IN (1,2)
            OR raw.period_start IS NULL OR raw.period_end IS NULL
            OR raw.period_instant IS NOT NULL
            OR (NEW.input_ordinal=1 AND raw.period_end<>p.period_end_date)
            OR (NEW.input_ordinal=2 AND raw.period_end<>p.period_start_date-1)
            OR a.statement_period_end IS DISTINCT FROM raw.period_end
            OR a.fiscal_year IS DISTINCT FROM p.fiscal_year
            OR (p.locator_json->'ordered_input_occurrences'->(NEW.input_ordinal-1)->>'raw_fact_id')::bigint IS DISTINCT FROM NEW.raw_fact_id
            OR (p.locator_json->'ordered_input_occurrences'->(NEW.input_ordinal-1)->>'parse_run_id')::bigint IS DISTINCT FROM s.parse_run_id))"""

_UNRESOLVED_PROVENANCE_DIRECT_IDENTITY = """OR raw.context_id IS DISTINCT FROM p.context_id OR a.context_id IS DISTINCT FROM p.context_id
            OR raw.period_start IS DISTINCT FROM p.period_start_date
            OR coalesce(raw.period_end,raw.period_instant) IS DISTINCT FROM p.period_end_date
            OR a.statement_period_end IS DISTINCT FROM p.period_end_date
            OR a.fiscal_year IS DISTINCT FROM p.fiscal_year
            OR a.fiscal_quarter_ordinal IS DISTINCT FROM p.fiscal_quarter_ordinal
            OR (p.period_basis='instant' AND (raw.period_instant IS NULL OR raw.period_start IS NOT NULL))
            OR (p.period_basis='duration' AND (raw.period_start IS NULL OR raw.period_end IS NULL OR raw.period_instant IS NOT NULL))"""

_UNRESOLVED_PROVENANCE_DERIVED_IDENTITY = """OR (
              NOT (p.reason_code LIKE 'unresolved_derived_%'
                OR (p.reason_code='unresolved_value'
                  AND jsonb_array_length(p.locator_json->'ordered_input_occurrences')=2))
              AND (raw.context_id IS DISTINCT FROM p.context_id
                OR a.context_id IS DISTINCT FROM p.context_id
                OR raw.period_start IS DISTINCT FROM p.period_start_date
                OR coalesce(raw.period_end,raw.period_instant) IS DISTINCT FROM p.period_end_date
                OR a.statement_period_end IS DISTINCT FROM p.period_end_date
                OR a.fiscal_year IS DISTINCT FROM p.fiscal_year
                OR a.fiscal_quarter_ordinal IS DISTINCT FROM p.fiscal_quarter_ordinal
                OR (p.period_basis='instant' AND (raw.period_instant IS NULL OR raw.period_start IS NOT NULL))
                OR (p.period_basis='duration' AND (raw.period_start IS NULL OR raw.period_end IS NULL OR raw.period_instant IS NOT NULL))))
            OR ((p.reason_code LIKE 'unresolved_derived_%'
                OR (p.reason_code='unresolved_value'
                  AND jsonb_array_length(p.locator_json->'ordered_input_occurrences')=2))
              AND (jsonb_array_length(p.locator_json->'ordered_input_occurrences')<>2
                OR p.period_type<>'Q' OR p.period_basis<>'duration'
                OR p.fiscal_quarter_ordinal NOT IN (2,3,4)
                OR p.period_start_date IS NULL
                OR p.period_end_date-p.period_start_date+1 NOT BETWEEN 70 AND 110
                OR ui.input_ordinal NOT IN (1,2)
                OR raw.period_start IS NULL OR raw.period_end IS NULL
                OR raw.period_instant IS NOT NULL
                OR (ui.input_ordinal=1 AND raw.period_end<>p.period_end_date)
                OR (ui.input_ordinal=2 AND raw.period_end<>p.period_start_date-1)
                OR a.statement_period_end IS DISTINCT FROM raw.period_end
                OR a.fiscal_year IS DISTINCT FROM p.fiscal_year
                OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'raw_fact_id')::bigint IS DISTINCT FROM ui.raw_fact_id
                OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'parse_run_id')::bigint IS DISTINCT FROM s.parse_run_id))"""


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
          RAISE EXCEPTION 'parser-v2.4 guard function source mismatch: %', function_name;
        END IF;
        EXECUTE replace(definition,{old_sql},{new_sql});
      END LOOP;
    END $$;
    """)


def upgrade() -> None:
    old_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1',"
        "'xbrl-lineage-v2.2','xbrl-lineage-v2.3']"
    )
    new_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1',"
        "'xbrl-lineage-v2.2','xbrl-lineage-v2.3','xbrl-lineage-v2.4']"
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
    old_generated = f"run.parser_version=ANY (ARRAY['{V22}','{V23}'])"
    new_generated = (
        f"run.parser_version=ANY (ARRAY['{V22}','{V23}','{V24}'])"
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
    repeated_anchor_old = """OR (length(report_text)-length(replace(
                report_text,NEW.locator_json->>'anchor_start_tag','')))
                / length(NEW.locator_json->>'anchor_start_tag')<>1"""
    repeated_anchor_new = f"""OR (run.parser_version<>'{V24}' AND
              (length(report_text)-length(replace(
                report_text,NEW.locator_json->>'anchor_start_tag','')))
                / length(NEW.locator_json->>'anchor_start_tag')<>1)
           OR (run.parser_version='{V24}' AND (
              jsonb_typeof(NEW.locator_json->'anchor_start_tag_occurrence_count')<>'number'
              OR (NEW.locator_json->>'anchor_start_tag_occurrence_count')::integer<=0
              OR (length(report_text)-length(replace(
                   report_text,NEW.locator_json->>'anchor_start_tag','')))
                   / length(NEW.locator_json->>'anchor_start_tag')
                 <>(NEW.locator_json->>'anchor_start_tag_occurrence_count')::integer))"""
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        repeated_anchor_old,
        repeated_anchor_new,
    )
    semantic_old = (
        "coalesce(NEW.locator_json->>'anchor_start_tag_sha256',''),"
        "'UTF8')),'hex');"
    )
    semantic_new = (
        "coalesce(NEW.locator_json->>'anchor_start_tag_sha256','')||"
        f"CASE WHEN run.parser_version='{V24}' THEN chr(31)||"
        "coalesce(NEW.locator_json->>'anchor_start_tag_occurrence_count','') "
        "ELSE '' END,'UTF8')),'hex');"
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        semantic_old,
        semantic_new,
    )
    _replace_function_source(
        ("guard_sec_publication_unresolved_input_insert",),
        _UNRESOLVED_INPUT_DIRECT_IDENTITY,
        _UNRESOLVED_INPUT_DERIVED_IDENTITY,
    )
    _replace_function_source(
        ("validate_sec_publication_provenance",),
        _UNRESOLVED_PROVENANCE_DIRECT_IDENTITY,
        _UNRESOLVED_PROVENANCE_DERIVED_IDENTITY,
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_financial_parse_runs, sec_statement_fact_authorities, "
        "sec_statement_occurrence_evidence, sec_statement_report_references "
        "IN ACCESS EXCLUSIVE MODE"
    )
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM sec_financial_parse_runs WHERE parser_version=:version"
    ), {"version": V24}).scalar_one()
    if count:
        raise RuntimeError("downgrade refused: retained parser-v2.4 lineage exists")
    _replace_function_source(
        ("validate_sec_publication_provenance",),
        _UNRESOLVED_PROVENANCE_DERIVED_IDENTITY,
        _UNRESOLVED_PROVENANCE_DIRECT_IDENTITY,
    )
    _replace_function_source(
        ("guard_sec_publication_unresolved_input_insert",),
        _UNRESOLVED_INPUT_DERIVED_IDENTITY,
        _UNRESOLVED_INPUT_DIRECT_IDENTITY,
    )
    semantic_old = (
        "coalesce(NEW.locator_json->>'anchor_start_tag_sha256',''),"
        "'UTF8')),'hex');"
    )
    semantic_new = (
        "coalesce(NEW.locator_json->>'anchor_start_tag_sha256','')||"
        f"CASE WHEN run.parser_version='{V24}' THEN chr(31)||"
        "coalesce(NEW.locator_json->>'anchor_start_tag_occurrence_count','') "
        "ELSE '' END,'UTF8')),'hex');"
    )
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        semantic_new,
        semantic_old,
    )
    repeated_anchor_old = """OR (length(report_text)-length(replace(
                report_text,NEW.locator_json->>'anchor_start_tag','')))
                / length(NEW.locator_json->>'anchor_start_tag')<>1"""
    repeated_anchor_new = f"""OR (run.parser_version<>'{V24}' AND
              (length(report_text)-length(replace(
                report_text,NEW.locator_json->>'anchor_start_tag','')))
                / length(NEW.locator_json->>'anchor_start_tag')<>1)
           OR (run.parser_version='{V24}' AND (
              jsonb_typeof(NEW.locator_json->'anchor_start_tag_occurrence_count')<>'number'
              OR (NEW.locator_json->>'anchor_start_tag_occurrence_count')::integer<=0
              OR (length(report_text)-length(replace(
                   report_text,NEW.locator_json->>'anchor_start_tag','')))
                   / length(NEW.locator_json->>'anchor_start_tag')
                 <>(NEW.locator_json->>'anchor_start_tag_occurrence_count')::integer))"""
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        repeated_anchor_new,
        repeated_anchor_old,
    )
    old_generated = f"run.parser_version=ANY (ARRAY['{V22}','{V23}'])"
    new_generated = (
        f"run.parser_version=ANY (ARRAY['{V22}','{V23}','{V24}'])"
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
        "'xbrl-lineage-v2.2','xbrl-lineage-v2.3']"
    )
    new_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1',"
        "'xbrl-lineage-v2.2','xbrl-lineage-v2.3','xbrl-lineage-v2.4']"
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
