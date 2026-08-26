"""research inbox action projection and immutable events

Revision ID: 20260720150000
Revises: 20260720140000
Create Date: 2026-07-20 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720150000"
down_revision = "20260720140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_inbox_actions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("logical_key", sa.String(length=240), nullable=False),
        sa.Column("action_family", sa.String(length=40), nullable=False),
        sa.Column("subject_type", sa.String(length=24), nullable=False),
        sa.Column("subject_key", sa.String(length=160), nullable=False),
        sa.Column("source_version", sa.String(length=200), nullable=False),
        sa.Column("supersedes_action_id", sa.BigInteger(), nullable=True),
        sa.Column("priority_policy_version", sa.String(length=48), nullable=False),
        sa.Column("matched_rule", sa.String(length=80), nullable=False),
        sa.Column("priority_rank", sa.Integer(), nullable=False),
        sa.Column("rank_components", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=24), server_default="open", nullable=False),
        sa.Column("snoozed_until", sa.Date(), nullable=True),
        sa.Column("target_case_id", sa.BigInteger(), nullable=True),
        sa.Column("stock_id", sa.BigInteger(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "state IN ('open', 'snoozed', 'dismissed', 'completed', 'superseded')",
            name="ck_research_inbox_actions_state",
        ),
        sa.CheckConstraint(
            "action_family IN ('review_due', 'continue_research', 'start_research', "
            "'coverage_gap', 'candidate_discovery', 'manager_activity')",
            name="ck_research_inbox_actions_family",
        ),
        sa.CheckConstraint(
            "((state = 'snoozed' AND snoozed_until IS NOT NULL) OR "
            "(state <> 'snoozed' AND snoozed_until IS NULL))",
            name="ck_research_inbox_actions_snooze_shape",
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_action_id"], ["research_inbox_actions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_case_id"], ["research_cases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "logical_key", "source_version",
            name="uq_research_inbox_action_source",
        ),
    )
    op.create_index(
        "ix_research_inbox_user_state_rank",
        "research_inbox_actions",
        ["user_id", "state", "priority_rank", "id"],
    )
    op.create_index(
        "ix_research_inbox_user_logical",
        "research_inbox_actions",
        ["user_id", "logical_key"],
    )
    op.create_table(
        "research_inbox_action_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("action_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["research_inbox_actions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_inbox_events_action_created",
        "research_inbox_action_events",
        ["action_id", "created_at"],
    )
    op.create_index(
        "ix_research_inbox_events_user_created",
        "research_inbox_action_events",
        ["user_id", "created_at"],
    )
    op.execute(
        """
        CREATE TRIGGER trg_research_inbox_action_events_append_only
        BEFORE UPDATE OR DELETE ON research_inbox_action_events
        FOR EACH ROW EXECUTE FUNCTION reject_research_append_only_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_research_inbox_action_events_append_only "
        "ON research_inbox_action_events"
    )
    op.drop_index("ix_research_inbox_events_user_created", table_name="research_inbox_action_events")
    op.drop_index("ix_research_inbox_events_action_created", table_name="research_inbox_action_events")
    op.drop_table("research_inbox_action_events")
    op.drop_index("ix_research_inbox_user_logical", table_name="research_inbox_actions")
    op.drop_index("ix_research_inbox_user_state_rank", table_name="research_inbox_actions")
    op.drop_table("research_inbox_actions")
