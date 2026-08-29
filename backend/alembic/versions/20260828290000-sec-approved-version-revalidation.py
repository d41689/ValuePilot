"""Revalidate every fact claiming an approved SEC mapping version.

Revision ID: 20260828290000
Revises: 20260828280000
Create Date: 2026-08-29 05:00:00
"""

from alembic import op


revision = "20260828290000"
down_revision = "20260828280000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A version is approved if any registry row owns that version. The
    # validators themselves still require the raw concept to match its exact
    # registry row. Thus a forged concept under v2 fails migration, while a
    # wholly unknown legacy version such as v1 remains quarantined.
    op.execute(
        "UPDATE metric_facts SET is_current = is_current "
        "WHERE source_type = 'sec' "
        "AND EXISTS ("
        "SELECT 1 FROM sec_metric_publications publication "
        "JOIN sec_metric_mapping_registry mapping "
        "ON mapping.mapping_version = publication.mapping_version "
        "WHERE publication.metric_fact_id = metric_facts.id"
        ")"
    )
    op.execute("SET CONSTRAINTS trg_metric_facts_sec_publication IMMEDIATE")
    op.execute(
        "SET CONSTRAINTS trg_metric_facts_sec_provenance_metadata IMMEDIATE"
    )
    op.execute(
        "SET CONSTRAINTS trg_metric_facts_sec_derived_input_lineage IMMEDIATE"
    )


def downgrade() -> None:
    # This revision records a completed validation and introduces no schema
    # state that can or should be undone.
    pass
