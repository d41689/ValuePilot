"""Enforce causal ordering for SEC financial filing dates.

Revision ID: 20260830120000
Revises: 20260827120000
Create Date: 2026-08-30 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260830120000"
down_revision = "20260827120000"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_sec_financial_filings_period_order"
PERIOD_ORDER_SQL = (
    "(report_date IS NULL OR "
    "(report_date <= filed_on AND "
    "report_date <= (accepted_at AT TIME ZONE 'UTC')::date))"
)


def upgrade() -> None:
    connection = op.get_bind()
    invalid_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM sec_financial_filings WHERE NOT ("
            + PERIOD_ORDER_SQL
            + ")"
        )
    ).scalar_one()
    if invalid_count:
        raise RuntimeError(
            "existing SEC financial filing period metadata is invalid; "
            f"found {invalid_count} row(s). Resolve the source-data policy before "
            "applying this migration; rows were not rewritten or backdated."
        )
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "sec_financial_filings",
        PERIOD_ORDER_SQL,
    )


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        "sec_financial_filings",
        type_="check",
    )
