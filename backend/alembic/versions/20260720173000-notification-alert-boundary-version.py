"""Version notification valuation/decision boundaries and normalize in-app frequency.

Revision ID: 20260720173000
Revises: 20260720172000
Create Date: 2026-07-20 17:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720173000"
down_revision = "20260720172000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_price_alert_states",
        sa.Column("last_valuation_fact_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_notification_price_alert_states_valuation_fact",
        "notification_price_alert_states",
        "metric_facts",
        ["last_valuation_fact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "notification_price_alert_states",
        sa.Column("last_research_revision_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_notification_price_alert_states_research_revision",
        "notification_price_alert_states",
        "research_case_revisions",
        ["last_research_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "notification_price_alert_states",
        sa.Column("last_threshold_ratio", sa.Numeric(8, 6), nullable=True),
    )
    op.add_column(
        "notification_price_alert_states",
        sa.Column("last_hysteresis_ratio", sa.Numeric(8, 6), nullable=True),
    )

    # Earlier unshipped revisions preserved the legacy email preference label
    # (daily/weekly) on an in-app-only row. In-app history is immediate; retain
    # the old label solely so downgrade can restore the exact prior data.
    op.add_column(
        "notification_subscriptions",
        sa.Column(
            "legacy_frequency_before_in_app_normalization",
            sa.String(length=24),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE notification_subscriptions
        SET legacy_frequency_before_in_app_normalization = frequency,
            frequency = 'immediate'
        WHERE destination_id IS NULL
          AND frequency <> 'immediate'
        """
    )
    op.create_check_constraint(
        "ck_notification_subscriptions_in_app_immediate",
        "notification_subscriptions",
        "destination_id IS NOT NULL OR frequency = 'immediate'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_notification_subscriptions_in_app_immediate",
        "notification_subscriptions",
        type_="check",
    )
    op.execute(
        """
        UPDATE notification_subscriptions
        SET frequency = legacy_frequency_before_in_app_normalization
        WHERE legacy_frequency_before_in_app_normalization IS NOT NULL
        """
    )
    op.drop_column(
        "notification_subscriptions",
        "legacy_frequency_before_in_app_normalization",
    )
    op.drop_constraint(
        "fk_notification_price_alert_states_valuation_fact",
        "notification_price_alert_states",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_notification_price_alert_states_research_revision",
        "notification_price_alert_states",
        type_="foreignkey",
    )
    op.drop_column(
        "notification_price_alert_states",
        "last_research_revision_id",
    )
    op.drop_column(
        "notification_price_alert_states",
        "last_hysteresis_ratio",
    )
    op.drop_column(
        "notification_price_alert_states",
        "last_threshold_ratio",
    )
    op.drop_column(
        "notification_price_alert_states",
        "last_valuation_fact_id",
    )
