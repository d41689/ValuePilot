"""Audited account-erasure marker and narrow append-only update bypass.

Revision ID: 20260720171000
Revises: 20260720170000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720171000"
down_revision = "20260720170000"
branch_labels = None
depends_on = None


def _append_only_function(*, allow_erasure: bool) -> str:
    bypass = """
            IF TG_OP = 'UPDATE'
               AND current_setting('valuepilot.account_erasure', true) = 'on' THEN
                RETURN NEW;
            END IF;
    """ if allow_erasure else ""
    return f"""
        CREATE OR REPLACE FUNCTION reject_research_append_only_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
{bypass}
            RAISE EXCEPTION '% is append-only; % is forbidden', TG_TABLE_NAME, TG_OP;
        END;
        $$
    """


def upgrade() -> None:
    op.create_table(
        "account_erasure_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_account_erasure_events_user"),
    )
    op.create_index(
        "ix_account_erasure_events_created",
        "account_erasure_events",
        ["created_at"],
    )
    op.execute(_append_only_function(allow_erasure=True))
    op.execute(
        """
        CREATE TRIGGER trg_account_erasure_events_append_only
        BEFORE UPDATE OR DELETE ON account_erasure_events
        FOR EACH ROW EXECUTE FUNCTION reject_research_append_only_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_account_erasure_events_append_only "
        "ON account_erasure_events"
    )
    op.execute(_append_only_function(allow_erasure=False))
    op.drop_index("ix_account_erasure_events_created", table_name="account_erasure_events")
    op.drop_table("account_erasure_events")
