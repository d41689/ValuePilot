"""Bound consolidated generated statement candidate scope in parser v2.9.

Revision ID: 20260909150000
Revises: 20260909140000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260909150000"
down_revision = "20260909140000"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "validate_sec_parser_v2_structured_unit",
    "guard_sec_statement_report_reference_insert",
    "guard_sec_statement_fact_authority_insert",
    "guard_sec_statement_occurrence_insert",
)
OCCURRENCE = ("guard_sec_statement_occurrence_insert",)
OLD_VERSION = "'xbrl-lineage-v2.8']"
NEW_VERSION = "'xbrl-lineage-v2.8','xbrl-lineage-v2.9']"
OLD_NEGATED = "IF run.parser_version='xbrl-lineage-v2.8'"
NEW_NEGATED = "IF run.parser_version IN ('xbrl-lineage-v2.8','xbrl-lineage-v2.9')"
ANCHOR = "        SELECT jsonb_agg(candidate.id ORDER BY candidate.id) INTO equivalent_ids"
SCOPE_GUARD = r"""        IF NEW.locator_json ? 'candidate_scope' THEN
          report_text:=sec_statement_report_xml_text(reference.report_content);
          IF (SELECT count(*) FROM regexp_matches(report_text,'<table(?:[[:space:]>])','gi'))>1
             AND (coalesce((regexp_match(report_text,'(<table(?:[[:space:]][^>]*)?>)','i'))[1],'')
                    !~ 'class=[''"]report[''"]'
               OR (SELECT count(*) FROM regexp_matches(report_text,
                   '<table[^>]*[[:space:]]class=[''"]report[''"]','gi'))<>1)
          THEN RAISE EXCEPTION 'generated statement consolidated scope mismatch'; END IF;
          -- PostgreSQL POSIX greediness can span footer tables despite .*?.
          -- Nested tables are excluded below; use the first exact close tag.
          report_text:=substring(report_text from position('<table' in lower(report_text)));
          report_text:=left(report_text,position('</table>' in lower(report_text))+7);
          IF run.parser_version<>'xbrl-lineage-v2.9'
             OR NEW.locator_json->>'candidate_scope' IS DISTINCT FROM 'consolidated_empty_dimensions_v1'
             OR fact.dimensions_structured_json IS DISTINCT FROM '[]'::jsonb
             OR reference.statement_type NOT IN ('income_statement','comprehensive_income','balance_sheet','cash_flow')
             OR reference.report_name !~* '\mconsolidated\M'
             OR coalesce(NEW.locator_json->>'anchor_source_html','')=''
             OR position(NEW.locator_json->>'anchor_source_html' in report_text)=0
             OR EXISTS (
               SELECT 1 FROM sec_raw_xbrl_facts candidate,
                    jsonb_array_elements(candidate.dimensions_structured_json) dim,
                    regexp_matches(report_text,'defref_([A-Za-z0-9_.-]+)','g') target
               WHERE candidate.parse_run_id=run.id
                 AND substring(target[1] from position('_' in target[1])+1)
                     IN (dim->'axis'->>'local_name',dim->'member'->>'local_name'))
             OR (SELECT count(*) FROM regexp_matches(report_text,'<table(?:[[:space:]>])','gi'))<>1
             OR report_text ~ '(Axis|Member|Domain)(=|[''"])'
             OR left(upper(btrim(regexp_replace(regexp_replace(
                  coalesce((regexp_match(report_text,'<th(?:[[:space:]][^>]*)?>(.*?)</th>','is'))[1],''),
                  '<[^>]+>',' ','g'),'[[:space:]]+',' ','g'))),length(reference.report_name))
                IS DISTINCT FROM upper(reference.report_name)
          THEN RAISE EXCEPTION 'generated statement consolidated scope mismatch'; END IF;
        END IF;

"""


def _replace(names, old, new):
    connection = op.get_bind()
    for name in names:
        definition = connection.execute(sa.text(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND p.proname=:name"
        ), {"name": name}).scalar_one()
        if old not in definition:
            raise RuntimeError(f"parser-v2.9 guard source mismatch: {name}")
        connection.execute(sa.text(definition.replace(old, new)))


def upgrade():
    _replace(FUNCTIONS, OLD_VERSION, NEW_VERSION)
    _replace(OCCURRENCE, OLD_NEGATED, NEW_NEGATED)
    _replace(OCCURRENCE, ANCHOR, SCOPE_GUARD + ANCHOR)


def downgrade():
    op.execute("LOCK TABLE sec_financial_parse_runs, sec_statement_fact_authorities, "
               "sec_statement_occurrence_evidence, sec_statement_report_references IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT count(*) FROM sec_financial_parse_runs "
                                    "WHERE parser_version='xbrl-lineage-v2.9'")).scalar_one():
        raise RuntimeError("downgrade refused: retained parser-v2.9 lineage exists")
    _replace(OCCURRENCE, SCOPE_GUARD + ANCHOR, ANCHOR)
    _replace(OCCURRENCE, NEW_NEGATED, OLD_NEGATED)
    _replace(FUNCTIONS, NEW_VERSION, OLD_VERSION)
