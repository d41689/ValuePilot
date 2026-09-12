"""Authorize exact dollar accounting negatives and share millions in v2.11.

Revision ID: 20260912120000
Revises: 20260912110000
Create Date: 2026-09-12 12:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "20260912120000"
down_revision = "20260912110000"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "validate_sec_parser_v2_structured_unit",
    "guard_sec_statement_report_reference_insert",
    "guard_sec_statement_fact_authority_insert",
    "guard_sec_statement_occurrence_insert",
)
OCCURRENCE = ("guard_sec_statement_occurrence_insert",)
OLD_VERSION = "'xbrl-lineage-v2.10']"
NEW_VERSION = "'xbrl-lineage-v2.10','xbrl-lineage-v2.11']"
OLD_NEGATED = "IF run.parser_version IN ('xbrl-lineage-v2.8','xbrl-lineage-v2.9','xbrl-lineage-v2.10')"
NEW_NEGATED = "IF run.parser_version IN ('xbrl-lineage-v2.8','xbrl-lineage-v2.9','xbrl-lineage-v2.10','xbrl-lineage-v2.11')"
OLD_SCOPE = "IF run.parser_version NOT IN ('xbrl-lineage-v2.9','xbrl-lineage-v2.10')"
NEW_SCOPE = "IF run.parser_version NOT IN ('xbrl-lineage-v2.9','xbrl-lineage-v2.10','xbrl-lineage-v2.11')"
OLD_DISPLAY = "display_negative:=display_text ~ '^[(].*[)]$';"
NEW_DISPLAY = OLD_DISPLAY + r"""
        IF run.parser_version='xbrl-lineage-v2.11'
           AND display_text ~ '^\$[[:space:]]*[(]'
        THEN
          IF display_text !~ '^\$[[:space:]]*[(][[:space:]]*(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:[.][0-9]+)?[[:space:]]*[)]$'
          THEN RAISE EXCEPTION 'generated statement numeric identity malformed'; END IF;
          display_negative:=true;
        END IF;"""


def _replace(names: tuple[str, ...], old: str, new: str) -> None:
    connection = op.get_bind()
    for name in names:
        definition = connection.execute(sa.text(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND p.proname=:name"
        ), {"name": name}).scalar_one()
        if old not in definition:
            raise RuntimeError(f"parser-v2.11 guard source mismatch: {name}")
        connection.execute(sa.text(definition.replace(old, new)))


def upgrade() -> None:
    _replace(FUNCTIONS, OLD_VERSION, NEW_VERSION)
    _replace(OCCURRENCE, OLD_NEGATED, NEW_NEGATED)
    _replace(OCCURRENCE, OLD_SCOPE, NEW_SCOPE)
    _replace(OCCURRENCE, OLD_DISPLAY, NEW_DISPLAY)


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_financial_parse_runs, sec_statement_fact_authorities, "
        "sec_statement_occurrence_evidence, sec_statement_report_references "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if op.get_bind().execute(sa.text(
        "SELECT count(*) FROM sec_financial_parse_runs WHERE parser_version='xbrl-lineage-v2.11'"
    )).scalar_one():
        raise RuntimeError("downgrade refused: retained parser-v2.11 lineage exists")
    _replace(OCCURRENCE, NEW_DISPLAY, OLD_DISPLAY)
    _replace(OCCURRENCE, NEW_SCOPE, OLD_SCOPE)
    _replace(OCCURRENCE, NEW_NEGATED, OLD_NEGATED)
    _replace(FUNCTIONS, NEW_VERSION, OLD_VERSION)
