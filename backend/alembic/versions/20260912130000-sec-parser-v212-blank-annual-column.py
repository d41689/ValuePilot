"""Authorize explicit blank adjacent annual-column evidence in parser v2.12.

Revision ID: 20260912130000
Revises: 20260912120000
Create Date: 2026-09-12 13:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "20260912130000"
down_revision = "20260912120000"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "validate_sec_parser_v2_structured_unit",
    "guard_sec_statement_report_reference_insert",
    "guard_sec_statement_fact_authority_insert",
    "guard_sec_statement_occurrence_insert",
)
OCCURRENCE = ("guard_sec_statement_occurrence_insert",)
REPLACEMENTS = (
    (FUNCTIONS, "'xbrl-lineage-v2.11']", "'xbrl-lineage-v2.11','xbrl-lineage-v2.12']"),
    (OCCURRENCE,
     "IN ('xbrl-lineage-v2.8','xbrl-lineage-v2.9','xbrl-lineage-v2.10','xbrl-lineage-v2.11')",
     "IN ('xbrl-lineage-v2.8','xbrl-lineage-v2.9','xbrl-lineage-v2.10','xbrl-lineage-v2.11','xbrl-lineage-v2.12')"),
    (OCCURRENCE,
     "NOT IN ('xbrl-lineage-v2.9','xbrl-lineage-v2.10','xbrl-lineage-v2.11')",
     "NOT IN ('xbrl-lineage-v2.9','xbrl-lineage-v2.10','xbrl-lineage-v2.11','xbrl-lineage-v2.12')"),
    (OCCURRENCE, "IF run.parser_version='xbrl-lineage-v2.11'",
     "IF run.parser_version IN ('xbrl-lineage-v2.11','xbrl-lineage-v2.12')"),
    (OCCURRENCE, "header_date_matches integer;",
     "header_date_matches integer; blank_column jsonb; blank_end date; blank_header_match text[];"),
)
OLD_DISPLAY = "display_text:=btrim(NEW.locator_json->>'display_value');"
BLANK_GUARD = r"""
        IF NEW.locator_json ? 'explicit_blank_prior_annual_column' THEN
          blank_column:=NEW.locator_json->'explicit_blank_prior_annual_column';
          IF run.parser_version<>'xbrl-lineage-v2.12'
             OR jsonb_typeof(blank_column) IS DISTINCT FROM 'object'
             OR blank_column->>'report_filename' IS DISTINCT FROM reference.filename
             OR blank_column->>'report_sha256' IS DISTINCT FROM NEW.report_sha256
             OR jsonb_typeof(blank_column->'row') IS DISTINCT FROM 'number'
             OR jsonb_typeof(blank_column->'column') IS DISTINCT FROM 'number'
             OR (blank_column->>'row')::integer IS DISTINCT FROM NEW.row_ordinal
             OR (blank_column->>'column')::integer IS DISTINCT FROM NEW.column_ordinal+1
             OR coalesce(blank_column->>'period_end','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
             OR jsonb_typeof(blank_column->'cell_inner_html') IS DISTINCT FROM 'string'
             OR replace(blank_column->>'cell_inner_html',chr(160),' ') !~ '^([[:space:]]|<span></span>)*$'
             OR blank_column->>'cell_inner_html_sha256' IS DISTINCT FROM
                encode(sha256(convert_to(blank_column->>'cell_inner_html','UTF8')),'hex')
             OR fact.period_start IS NULL OR fact.period_end IS NULL
             OR fact.period_end-fact.period_start+1 NOT BETWEEN 300 AND 380
             OR NEW.header_raw !~* '^(12 months ended|twelve months ended|year ended)[[:space:]]+'
          THEN RAISE EXCEPTION 'generated statement blank annual column mismatch'; END IF;
          blank_end:=(blank_column->>'period_end')::date;
          blank_header_match:=regexp_match(blank_column->>'column_header',
            '^(?:[1][2] months ended|twelve months ended|year ended)[[:space:]]+(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[.]?[[:space:]]+([0-9]{1,2}),?[[:space:]]+([0-9]{4})$', 'i');
          IF blank_header_match IS NULL
             OR to_date(left(blank_header_match[1],3)||' '||blank_header_match[2]||' '||blank_header_match[3],'Mon DD YYYY')<>blank_end
             OR fact.period_end-blank_end NOT BETWEEN 350 AND 380
             OR EXISTS (SELECT 1 FROM sec_raw_xbrl_facts other
                        WHERE other.parse_run_id=NEW.parse_run_id AND other.concept=NEW.concept
                          AND other.period_end=blank_end)
          THEN RAISE EXCEPTION 'generated statement blank annual column mismatch'; END IF;
        END IF;
        """ + OLD_DISPLAY


def _replace(names: tuple[str, ...], old: str, new: str) -> None:
    connection = op.get_bind()
    for name in names:
        definition = connection.execute(sa.text(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND p.proname=:name"
        ), {"name": name}).scalar_one()
        if old not in definition:
            raise RuntimeError(f"parser-v2.12 guard source mismatch: {name}")
        # Escape literal colons for SQLAlchemy's text parser; it unescapes them
        # before PostgreSQL sees the unchanged function/regex source.
        connection.execute(sa.text(definition.replace(old, new).replace(":", r"\:")))


def upgrade() -> None:
    for names, old, new in REPLACEMENTS:
        _replace(names, old, new)
    _replace(OCCURRENCE, OLD_DISPLAY, BLANK_GUARD)


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_financial_parse_runs, sec_statement_fact_authorities, "
        "sec_statement_occurrence_evidence, sec_statement_report_references "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if op.get_bind().execute(sa.text(
        "SELECT count(*) FROM sec_financial_parse_runs WHERE parser_version='xbrl-lineage-v2.12'"
    )).scalar_one():
        raise RuntimeError("downgrade refused: retained parser-v2.12 lineage exists")
    _replace(OCCURRENCE, BLANK_GUARD, OLD_DISPLAY)
    for names, old, new in reversed(REPLACEMENTS):
        _replace(names, new, old)
