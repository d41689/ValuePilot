"""Add metric_facts value_text/source_document_id and JSONB.

Revision ID: 1a2b3c4d5e6f
Revises: 08307bdf4ed3
Create Date: 2026-01-20 12:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "1a2b3c4d5e6f"
down_revision = "08307bdf4ed3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("metric_facts", sa.Column("value_text", sa.Text(), nullable=True))
    op.add_column("metric_facts", sa.Column("source_document_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_metric_facts_source_document_id_pdf_documents",
        "metric_facts",
        "pdf_documents",
        ["source_document_id"],
        ["id"],
    )
    op.alter_column(
        "metric_facts",
        "value_json",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using="value_json::jsonb",
        existing_nullable=False,
        nullable=True,
    )
    op.create_unique_constraint(
        "uq_metric_facts_dedupe",
        "metric_facts",
        ["stock_id", "metric_key", "period_type", "period_end_date", "source_document_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_metric_facts_dedupe", "metric_facts", type_="unique")
    op.drop_constraint(
        "fk_metric_facts_source_document_id_pdf_documents",
        "metric_facts",
        type_="foreignkey",
    )
    op.alter_column(
        "metric_facts",
        "value_json",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.JSON(),
        postgresql_using="value_json::json",
        existing_nullable=True,
        nullable=False,
    )
    op.drop_column("metric_facts", "source_document_id")
    op.drop_column("metric_facts", "value_text")
