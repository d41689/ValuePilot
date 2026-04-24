"""Widen cusip_ticker_map.source from VARCHAR(20) to VARCHAR(50).

Revision ID: 20260423120000
Revises: 20260423000000
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20260423120000"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "cusip_ticker_map",
        "source",
        existing_type=sa.String(20),
        type_=sa.String(50),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "cusip_ticker_map",
        "source",
        existing_type=sa.String(50),
        type_=sa.String(20),
        existing_nullable=True,
    )
