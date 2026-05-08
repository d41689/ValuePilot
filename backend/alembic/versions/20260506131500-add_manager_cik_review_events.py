"""Add manager CIK review events.

Revision ID: 20260506131500
Revises: 20260506130000
Create Date: 2026-05-06 13:15:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260506131500"
down_revision = "20260506130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "institution_manager_cik_review_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("manager_id", sa.BigInteger(), sa.ForeignKey("institution_managers.id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("old_cik", sa.String(10), nullable=True),
        sa.Column("new_cik", sa.String(10), nullable=True),
        sa.Column("old_match_status", sa.String(20), nullable=True),
        sa.Column("new_match_status", sa.String(20), nullable=True),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("affected_filings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("affected_quarters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("requires_downstream_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_manager_cik_review_events_manager_id",
        "institution_manager_cik_review_events",
        ["manager_id"],
    )
    op.create_index(
        "ix_manager_cik_review_events_created_at",
        "institution_manager_cik_review_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_manager_cik_review_events_created_at", table_name="institution_manager_cik_review_events")
    op.drop_index("ix_manager_cik_review_events_manager_id", table_name="institution_manager_cik_review_events")
    op.drop_table("institution_manager_cik_review_events")
