"""Add orthogonal Value Line evidence retirement lifecycle.

Revision ID: 20260909120000
Revises: 20260904340000
Create Date: 2026-09-09 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260909120000"
down_revision: Union[str, None] = "20260904340000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pdf_documents",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pdf_documents",
        sa.Column("source_unavailable_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_pdf_documents_user_active",
        "pdf_documents",
        ["user_id", "id"],
        unique=False,
        postgresql_where=sa.text("archived_at IS NULL AND source_unavailable_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_pdf_documents_user_active", table_name="pdf_documents")
    op.drop_column("pdf_documents", "source_unavailable_at")
    op.drop_column("pdf_documents", "archived_at")
