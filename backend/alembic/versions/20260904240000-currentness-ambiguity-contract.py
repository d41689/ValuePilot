"""Leave duplicate current slots to typed consumer ambiguity handling.

Revision ID: 20260904240000
Revises: 20260904230000
"""

from alembic import op


revision = "20260904240000"
down_revision = "20260904230000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Several canonical consumers deliberately retain malformed duplicate
    # projections so they can report typed ambiguity instead of turning a data
    # repair problem into a write outage. Existing source-specific uniqueness
    # constraints remain authoritative; the timeline preserves every state.
    op.drop_index("uq_metric_facts_current_canonical_slot", table_name="metric_facts")


def downgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_metric_facts_current_canonical_slot
        ON metric_facts (
          coalesce(user_id,0),stock_id,metric_key,source_type,
          coalesce(source_document_id,0),coalesce(period_type,''),
          coalesce(period_end_date,DATE '0001-01-01'),
          coalesce(as_of_date,DATE '0001-01-01')
        ) WHERE is_current=true
        """
    )
