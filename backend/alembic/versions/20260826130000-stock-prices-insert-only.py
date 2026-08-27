"""Enforce insert-only canonical EOD price observations.

Revision ID: 20260826130000
Revises: 20260826120000
Create Date: 2026-08-26 13:00:00.000000
"""

from alembic import op


revision = "20260826130000"
down_revision = "20260826120000"
branch_labels = None
depends_on = None


_FUNCTION = "reject_stock_price_mutation"
_TRIGGER = "trg_stock_prices_insert_only"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {_FUNCTION}()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is insert-only; % is forbidden', TG_TABLE_NAME, TG_OP;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON stock_prices
        FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}()
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON stock_prices")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}()")
