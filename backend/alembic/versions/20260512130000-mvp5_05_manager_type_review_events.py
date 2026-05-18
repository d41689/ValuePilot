"""mvp5-05 manager_type review events

Adds an audit table that records every change to
``institution_managers.manager_type`` driven by the admin editor.
Mirrors the shape of ``institution_manager_cik_review_events`` but
stays scoped to manager_type so the table name doesn't lie about
its contents.

Revision ID: 20260512130000
Revises: 20260512120000
Create Date: 2026-05-12 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260512130000"
down_revision = "20260512120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "institution_manager_type_review_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("manager_id", sa.BigInteger(), nullable=False),
        sa.Column("old_manager_type", sa.String(length=40), nullable=True),
        sa.Column("new_manager_type", sa.String(length=40), nullable=False),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"], ["institution_managers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_manager_type_review_events_manager_id",
        "institution_manager_type_review_events",
        ["manager_id"],
    )
    op.create_index(
        "ix_manager_type_review_events_created_at",
        "institution_manager_type_review_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_manager_type_review_events_created_at",
        table_name="institution_manager_type_review_events",
    )
    op.drop_index(
        "ix_manager_type_review_events_manager_id",
        table_name="institution_manager_type_review_events",
    )
    op.drop_table("institution_manager_type_review_events")
