"""Add durable user-scoped expensive-operation rate limits.

Revision ID: 20260720172000
Revises: 20260720171000
Create Date: 2026-07-20 17:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720172000"
down_revision = "20260720171000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_rate_limit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(length=48), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "operation IN ("
            "'coverage_price_refresh', 'document_upload', "
            "'destination_verification', 'destination_delivery_test'"
            ")",
            name="ck_api_rate_limit_events_operation",
        ),
    )
    op.create_index(
        "ix_api_rate_limit_events_user_operation_time",
        "api_rate_limit_events",
        ["user_id", "operation", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_api_rate_limit_events_user_operation_time",
        table_name="api_rate_limit_events",
    )
    op.drop_table("api_rate_limit_events")
