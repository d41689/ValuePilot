"""Enforce one current canonical SEC fact per period slot.

Revision ID: 20260828270000
Revises: 20260828260000
Create Date: 2026-08-29 03:00:00
"""

from alembic import op


revision = "20260828270000"
down_revision = "20260828260000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This is intentionally SEC-only and period-scoped. It must never become a
    # global (stock, metric) current-row deduplication rule.
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
                    'cannot downgrade SEC current-slot uniqueness while current facts exist';
            END IF;
        END;
        $$;
        """
    )
    op.execute("DROP INDEX uq_metric_facts_current_sec_period_slot")
