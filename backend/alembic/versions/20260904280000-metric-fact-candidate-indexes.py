"""Index compact metric-fact candidate scopes before timeline ranking.

Revision ID: 20260904280000
Revises: 20260904270000
"""

from alembic import op


revision = "20260904280000"
down_revision = "20260904270000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_metric_facts_candidate_stock_id",
        "metric_facts",
        ["stock_id", "id"],
    )
    op.create_index(
        "ix_metric_facts_candidate_metric_id",
        "metric_facts",
        ["metric_key", "id"],
    )
    op.create_index(
        "ix_metric_facts_candidate_document_id",
        "metric_facts",
        ["source_document_id", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_metric_facts_candidate_document_id", table_name="metric_facts"
    )
    op.drop_index(
        "ix_metric_facts_candidate_metric_id", table_name="metric_facts"
    )
    op.drop_index(
        "ix_metric_facts_candidate_stock_id", table_name="metric_facts"
    )
