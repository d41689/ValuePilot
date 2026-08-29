"""Scope SEC current-slot uniqueness to the approved mapping version.

Revision ID: 20260828280000
Revises: 20260828270000
Create Date: 2026-08-29 04:00:00
"""

from alembic import op


revision = "20260828280000"
down_revision = "20260828270000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Recreate the unpublished predecessor index for databases that already
    # ran 2700. Unknown legacy mappings must not prevent an approved v2 fact
    # from occupying the product-visible slot.
    op.execute("DROP INDEX IF EXISTS uq_metric_facts_current_sec_period_slot")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_metric_facts_current_sec_period_slot
        ON metric_facts (
            stock_id,
            metric_key,
            period_type,
            period_end_date
        )
        WHERE source_type = 'sec'
          AND is_current = true
          AND value_json->>'mapping_version' = 'sec-us-gaap-v2'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM metric_facts
                WHERE source_type = 'sec'
                  AND is_current = true
                  AND value_json->>'mapping_version' = 'sec-us-gaap-v2'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade approved SEC slot uniqueness while v2 facts exist';
            END IF;
        END;
        $$;
        """
    )
    # The v2-scoped index is also the 2700 contract in a fresh migration
    # chain, so leave it in place for the predecessor downgrade to own.
