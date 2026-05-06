"""Add stock market country identity fields.

Revision ID: 20260506100000
Revises: 20260423120000
Create Date: 2026-05-06 10:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260506100000"
down_revision = "20260423120000"
branch_labels = None
depends_on = None


US_ALIASES = "'US','NYSE','NASDAQ','NDQ','NAS','NMS','NCM','NGM','NSDQ','AMEX','NYSEMKT','NYSEAMERICAN','ARCA','BATS','OTC','PNK'"
CA_ALIASES = "'CA','CAN','TSE','TSX','TSXV','CVE'"


def upgrade() -> None:
    op.add_column(
        "stocks",
        sa.Column("market_country", sa.String(), nullable=False, server_default="UNKNOWN"),
    )
    op.add_column("stocks", sa.Column("listing_exchange", sa.String(), nullable=True))
    op.add_column("stocks", sa.Column("raw_exchange", sa.String(), nullable=True))
    op.create_index("ix_stocks_market_country", "stocks", ["market_country"])
    op.create_index("ix_stocks_listing_exchange", "stocks", ["listing_exchange"])

    op.execute(
        f"""
        UPDATE stocks
        SET raw_exchange = exchange,
            listing_exchange = CASE
                WHEN upper(exchange) IN ('NASDAQ','NAS','NMS','NCM','NGM','NSDQ') THEN 'NDQ'
                WHEN upper(exchange) = 'TSX' THEN 'TSE'
                WHEN upper(exchange) IN ('US','CA','CAN','UNKNOWN') THEN NULL
                ELSE upper(exchange)
            END,
            market_country = CASE
                WHEN upper(ticker) LIKE '%%.TO' THEN 'CA'
                WHEN upper(exchange) IN ({CA_ALIASES}) THEN 'CA'
                WHEN upper(exchange) IN ({US_ALIASES}) THEN 'US'
                ELSE COALESCE(NULLIF(upper(exchange), ''), 'UNKNOWN')
            END
        """
    )
    _merge_duplicate_active_stocks()
    op.execute("UPDATE stocks SET exchange = COALESCE(listing_exchange, market_country) WHERE is_active = true")


def downgrade() -> None:
    op.drop_index("ix_stocks_listing_exchange", table_name="stocks")
    op.drop_index("ix_stocks_market_country", table_name="stocks")
    op.drop_column("stocks", "raw_exchange")
    op.drop_column("stocks", "listing_exchange")
    op.drop_column("stocks", "market_country")


def _merge_duplicate_active_stocks() -> None:
    op.execute(
        """
        CREATE TEMP TABLE stock_identity_duplicates AS
        WITH ranked AS (
            SELECT
                id,
                first_value(id) OVER (
                    PARTITION BY upper(ticker), market_country
                    ORDER BY id
                ) AS canonical_id,
                row_number() OVER (
                    PARTITION BY upper(ticker), market_country
                    ORDER BY id
                ) AS rn
            FROM stocks
            WHERE is_active = true
        )
        SELECT id AS duplicate_id, canonical_id
        FROM ranked
        WHERE rn > 1
        """
    )
    for table in [
        "pdf_documents",
        "metric_facts",
        "calculated_runs",
        "stock_prices",
        "pool_memberships",
        "price_alerts",
        "holdings_13f",
    ]:
        op.execute(
            f"""
            UPDATE {table} target
            SET stock_id = duplicates.canonical_id
            FROM stock_identity_duplicates duplicates
            WHERE target.stock_id = duplicates.duplicate_id
            """
        )
    op.execute(
        """
        UPDATE stocks canonical
        SET listing_exchange = COALESCE(canonical.listing_exchange, duplicate.listing_exchange),
            raw_exchange = COALESCE(canonical.raw_exchange, duplicate.raw_exchange)
        FROM stock_identity_duplicates duplicates
        JOIN stocks duplicate ON duplicate.id = duplicates.duplicate_id
        WHERE canonical.id = duplicates.canonical_id
        """
    )
    op.execute(
        """
        UPDATE stocks target
        SET is_active = false,
            exchange = target.market_country
        FROM stock_identity_duplicates duplicates
        WHERE target.id = duplicates.duplicate_id
        """
    )
    op.execute("DROP TABLE stock_identity_duplicates")
