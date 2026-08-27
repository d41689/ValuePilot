"""Configurable intrinsic-value alert policy.

Revision ID: 20260720161000
Revises: 20260720160000
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720161000"
down_revision = "20260720160000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_subscriptions",
        sa.Column("threshold_ratio", sa.Numeric(8, 6), nullable=True),
    )
    op.add_column(
        "notification_subscriptions",
        sa.Column(
            "hysteresis_ratio",
            sa.Numeric(8, 6),
            server_default="0.020000",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_notification_subscriptions_threshold_ratio",
        "notification_subscriptions",
        "threshold_ratio IS NULL OR threshold_ratio BETWEEN 0 AND 0.95",
    )
    op.create_check_constraint(
        "ck_notification_subscriptions_hysteresis_ratio",
        "notification_subscriptions",
        "hysteresis_ratio BETWEEN 0 AND 0.25",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_notification_subscriptions_hysteresis_ratio",
        "notification_subscriptions",
        type_="check",
    )
    op.drop_constraint(
        "ck_notification_subscriptions_threshold_ratio",
        "notification_subscriptions",
        type_="check",
    )
    op.drop_column("notification_subscriptions", "hysteresis_ratio")
    op.drop_column("notification_subscriptions", "threshold_ratio")
