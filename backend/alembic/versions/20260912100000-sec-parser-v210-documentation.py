"""Authorize SEC parser v2.10 with unused empty documentation compatibility.

Revision ID: 20260912100000
Revises: 20260909150000
Create Date: 2026-09-12 10:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "20260912100000"
down_revision = "20260909150000"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "validate_sec_parser_v2_structured_unit",
    "guard_sec_statement_report_reference_insert",
    "guard_sec_statement_fact_authority_insert",
    "guard_sec_statement_occurrence_insert",
)
OCCURRENCE = ("guard_sec_statement_occurrence_insert",)
OLD_VERSION = "'xbrl-lineage-v2.9']"
NEW_VERSION = "'xbrl-lineage-v2.9','xbrl-lineage-v2.10']"
OLD_NEGATED = "IF run.parser_version IN ('xbrl-lineage-v2.8','xbrl-lineage-v2.9')"
NEW_NEGATED = "IF run.parser_version IN ('xbrl-lineage-v2.8','xbrl-lineage-v2.9','xbrl-lineage-v2.10')"
OLD_SCOPE = "IF run.parser_version<>'xbrl-lineage-v2.9'"
NEW_SCOPE = "IF run.parser_version NOT IN ('xbrl-lineage-v2.9','xbrl-lineage-v2.10')"


def _replace(names: tuple[str, ...], old: str, new: str) -> None:
    connection = op.get_bind()
    for name in names:
        definition = connection.execute(sa.text(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND p.proname=:name"
        ), {"name": name}).scalar_one()
        if old not in definition:
            raise RuntimeError(f"parser-v2.10 guard source mismatch: {name}")
        # Only migration-owned function source and constant fragments enter DDL.
        connection.execute(sa.text(definition.replace(old, new)))


def upgrade() -> None:
    # Retained linkbase parsing remains the trusted parser's responsibility;
    # every existing database occurrence/lineage guard also governs v2.10.
    _replace(FUNCTIONS, OLD_VERSION, NEW_VERSION)
    _replace(OCCURRENCE, OLD_NEGATED, NEW_NEGATED)
    _replace(OCCURRENCE, OLD_SCOPE, NEW_SCOPE)


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_financial_parse_runs, sec_statement_fact_authorities, "
        "sec_statement_occurrence_evidence, sec_statement_report_references "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if op.get_bind().execute(sa.text(
        "SELECT count(*) FROM sec_financial_parse_runs "
        "WHERE parser_version='xbrl-lineage-v2.10'"
    )).scalar_one():
        raise RuntimeError("downgrade refused: retained parser-v2.10 lineage exists")
    _replace(OCCURRENCE, NEW_SCOPE, OLD_SCOPE)
    _replace(OCCURRENCE, NEW_NEGATED, OLD_NEGATED)
    _replace(FUNCTIONS, NEW_VERSION, OLD_VERSION)
