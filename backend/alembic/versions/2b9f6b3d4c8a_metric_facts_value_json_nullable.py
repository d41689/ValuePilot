"""Allow metric_facts.value_json to be nullable.

Revision ID: 2b9f6b3d4c8a
Revises: 1a2b3c4d5e6f
Create Date: 2026-01-20 20:10:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "2b9f6b3d4c8a"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "metric_facts",
        "value_json",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        existing_nullable=False,
    )


def downgrade() -> None:
    # Backfill NULLs before restoring NOT NULL constraint so downgrades are safe on
    # databases that accepted NULLs while this revision was applied.
    op.execute(
        sa.text("UPDATE metric_facts SET value_json = '{}'::jsonb WHERE value_json IS NULL")
    )
    op.alter_column(
        "metric_facts",
        "value_json",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        existing_nullable=True,
    )
