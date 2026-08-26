"""Manual portfolios, long-only positions and append-only decision journal.

Revision ID: 20260720170000
Revises: 20260720161000
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720170000"
down_revision = "20260720161000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_portfolios",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_manual_portfolios_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_manual_portfolios_user_status", "manual_portfolios", ["user_id", "status", "updated_at"])

    op.create_table(
        "manual_positions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("stock_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("average_unit_cost", sa.Numeric(24, 6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("research_case_id", sa.BigInteger(), nullable=True),
        sa.Column("research_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("opened_on", sa.Date(), nullable=False),
        sa.Column("closed_on", sa.Date(), nullable=True),
        sa.Column("last_reviewed_on", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "((state = 'open' AND quantity > 0 AND closed_on IS NULL) OR "
            "(state = 'closed' AND quantity = 0 AND closed_on IS NOT NULL))",
            name="ck_manual_positions_state_shape",
        ),
        sa.CheckConstraint(
            "average_unit_cost IS NULL OR average_unit_cost > 0",
            name="ck_manual_positions_average_cost",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_manual_positions_currency"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["manual_portfolios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["research_case_id"], ["research_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["research_revision_id"], ["research_case_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_manual_positions_open_portfolio_stock",
        "manual_positions",
        ["portfolio_id", "stock_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open'"),
    )
    op.create_index("ix_manual_positions_user_state", "manual_positions", ["user_id", "state", "updated_at"])
    op.create_index("ix_manual_positions_portfolio_created", "manual_positions", ["portfolio_id", "created_at"])

    op.create_table(
        "position_journal_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("position_id", sa.BigInteger(), nullable=False),
        sa.Column("portfolio_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("prior_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("new_quantity", sa.Numeric(28, 8), nullable=True),
        sa.Column("prior_average_unit_cost", sa.Numeric(24, 6), nullable=True),
        sa.Column("new_average_unit_cost", sa.Numeric(24, 6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("research_case_id", sa.BigInteger(), nullable=True),
        sa.Column("research_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("recorded_stock_id", sa.BigInteger(), nullable=False),
        sa.Column("recorded_ticker", sa.String(length=40), nullable=False),
        sa.Column("recorded_company_name", sa.Text(), nullable=False),
        sa.Column("recorded_exchange", sa.String(length=40), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("event_type IN ('open', 'resize', 'close', 'review')", name="ck_position_journal_events_type"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_position_journal_events_currency"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["manual_portfolios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["position_id"], ["manual_positions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_stock_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["research_case_id"], ["research_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["research_revision_id"], ["research_case_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("position_id", "sequence_number", name="uq_position_journal_events_sequence"),
    )
    op.create_index("ix_position_journal_events_position_created", "position_journal_events", ["position_id", "created_at"])
    op.create_index("ix_position_journal_events_user_effective", "position_journal_events", ["user_id", "effective_on"])

    op.execute(
        """
        CREATE TRIGGER trg_position_journal_events_append_only
        BEFORE UPDATE OR DELETE ON position_journal_events
        FOR EACH ROW EXECUTE FUNCTION reject_research_append_only_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_position_journal_events_append_only ON position_journal_events")
    op.drop_index("ix_position_journal_events_user_effective", table_name="position_journal_events")
    op.drop_index("ix_position_journal_events_position_created", table_name="position_journal_events")
    op.drop_table("position_journal_events")
    op.drop_index("ix_manual_positions_portfolio_created", table_name="manual_positions")
    op.drop_index("ix_manual_positions_user_state", table_name="manual_positions")
    op.drop_index("uq_manual_positions_open_portfolio_stock", table_name="manual_positions")
    op.drop_table("manual_positions")
    op.drop_index("ix_manual_portfolios_user_status", table_name="manual_portfolios")
    op.drop_table("manual_portfolios")
