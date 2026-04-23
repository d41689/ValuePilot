"""Add report_date to pdf_documents.

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-04-22 09:30:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4d5e6f7a8b9c"
down_revision = "3c4d5e6f7a8b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pdf_documents", sa.Column("report_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("pdf_documents", "report_date")
