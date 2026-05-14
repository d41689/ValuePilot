"""Pre-MVP8-01 widen cusip_ticker_map.ticker

OpenFIGI's mapCusips response can return non-equity identifiers for
some CUSIPs (e.g. bond CUSIPs match to instruments like
``"BRKR 6.375 09/01/28"`` — 19 chars). The original column was
sized at VARCHAR(10) which only fits typical equity tickers; bond /
preferred / warrant identifiers overflow. Per CLAUDE.md schema
band-aid rule, the fix is an Alembic migration, not truncation.

Discovered during Pre-MVP8-01 data-env readiness execution
2026-05-13 — see
``docs/tasks/2026-05-13_pre-mvp8-01-data-env-readiness.md``.

Revision ID: 20260513140000
Revises: 20260512130000
Create Date: 2026-05-13 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260513140000"
down_revision = "20260512130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "cusip_ticker_map",
        "ticker",
        existing_type=sa.String(10),
        type_=sa.String(50),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "cusip_ticker_map",
        "ticker",
        existing_type=sa.String(50),
        type_=sa.String(10),
        existing_nullable=True,
    )
