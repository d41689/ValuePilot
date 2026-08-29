"""Scope document fact dedupe to immutable parsed observations.

Revision ID: 20260828320000
Revises: 20260828310000
Create Date: 2026-08-29 08:00:00
"""

from alembic import op


revision = "20260828320000"
down_revision = "20260828310000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The original all-source constraint prevented a parsed observation and
    # its append-only manual correction from coexisting, and also prevented a
    # second manual correction after the first was demoted. Parsed extraction
    # idempotency is the only behavior this legacy key should enforce.
    op.drop_constraint("uq_metric_facts_dedupe", "metric_facts", type_="unique")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_metric_facts_parsed_document_slot
        ON metric_facts (
            stock_id,
            metric_key,
            period_type,
            period_end_date,
            source_document_id
        )
        WHERE source_type = 'parsed'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM metric_facts
                GROUP BY stock_id, metric_key, period_type, period_end_date,
                         source_document_id
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade source-scoped fact dedupe while append-only corrections coexist';
            END IF;
        END;
        $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_metric_facts_parsed_document_slot")
    op.create_unique_constraint(
        "uq_metric_facts_dedupe",
        "metric_facts",
        [
            "stock_id",
            "metric_key",
            "period_type",
            "period_end_date",
            "source_document_id",
        ],
    )
