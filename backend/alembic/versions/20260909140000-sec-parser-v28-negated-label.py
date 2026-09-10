"""Authorize exact negatedLabel display identity for SEC parser v2.8.

Revision ID: 20260909140000
Revises: 20260909120000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260909140000"
down_revision = "20260909120000"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "validate_sec_parser_v2_structured_unit",
    "guard_sec_statement_report_reference_insert",
    "guard_sec_statement_fact_authority_insert",
    "guard_sec_statement_occurrence_insert",
)
OLD_VERSION = "'xbrl-lineage-v2.7']"
NEW_VERSION = "'xbrl-lineage-v2.7','xbrl-lineage-v2.8']"
OLD_NUMERIC = "IF display_value*multiplier<>fact_value THEN"
NEW_NUMERIC = """IF run.parser_version='xbrl-lineage-v2.8'
           AND NEW.locator_json->>'preferred_label_role'=
               'http://www.xbrl.org/2009/role/negatedLabel'
        THEN display_value:=-display_value; END IF;
        IF display_value*multiplier<>fact_value THEN"""


def _replace(functions: tuple[str, ...], old: str, new: str) -> None:
    connection = op.get_bind()
    for name in functions:
        definition = connection.execute(sa.text(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname=current_schema() AND p.proname=:name"
        ), {"name": name}).scalar_one()
        if old not in definition:
            raise RuntimeError(f"parser-v2.8 guard source mismatch: {name}")
        # Only migration-owned function source and constant fragments enter DDL.
        connection.execute(sa.text(definition.replace(old, new)))


def upgrade() -> None:
    # Extend each existing v2.7 array membership without changing its meaning.
    _replace(FUNCTIONS, OLD_VERSION, NEW_VERSION)
    _replace(("guard_sec_statement_occurrence_insert",), OLD_NUMERIC, NEW_NUMERIC)


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_financial_parse_runs, sec_statement_fact_authorities, "
        "sec_statement_occurrence_evidence, sec_statement_report_references "
        "IN ACCESS EXCLUSIVE MODE"
    )
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM sec_financial_parse_runs "
        "WHERE parser_version='xbrl-lineage-v2.8'"
    )).scalar_one()
    if count:
        raise RuntimeError("downgrade refused: retained parser-v2.8 lineage exists")
    _replace(("guard_sec_statement_occurrence_insert",), NEW_NUMERIC, OLD_NUMERIC)
    _replace(FUNCTIONS, NEW_VERSION, OLD_VERSION)
