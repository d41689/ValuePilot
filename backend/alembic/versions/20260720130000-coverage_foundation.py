"""targeted coverage and EOD currency foundation

Revision ID: 20260720130000
Revises: 20260720120000
Create Date: 2026-07-20 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720130000"
down_revision = "20260720120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical rows deliberately remain NULL: currency cannot be inferred
    # safely from ticker text or exchange alone.
    op.add_column(
        "stock_prices",
        sa.Column("currency", sa.String(length=3), nullable=True),
    )
    op.create_check_constraint(
        "ck_stock_prices_currency_iso_shape",
        "stock_prices",
        "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
    )
    op.create_table(
        "research_coverage_requirements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("stock_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("priority_policy_version", sa.String(length=48), nullable=False),
        sa.Column("matched_rule", sa.String(length=80), nullable=False),
        sa.Column("priority_rank", sa.Integer(), nullable=False),
        sa.Column("rank_components", postgresql.JSONB(), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("source_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freshness_policy_version", sa.String(length=48), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_action", sa.String(length=80), nullable=True),
        sa.Column("first_unmet_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('eod_price', 'value_line_current_report', "
            "'valuation_input', 'identity_review', 'cusip_review')",
            name="ck_research_coverage_kind",
        ),
        sa.CheckConstraint(
            "state IN ('ready', 'missing', 'stale', 'blocked', "
            "'in_progress', 'failed')",
            name="ck_research_coverage_state",
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "stock_id",
            "kind",
            "priority_policy_version",
            name="uq_research_coverage_user_stock_kind_policy",
        ),
    )
    op.create_index(
        "ix_research_coverage_user_current_rank",
        "research_coverage_requirements",
        ["user_id", "is_current", "priority_rank"],
        unique=False,
    )
    op.create_index(
        "ix_research_coverage_user_state",
        "research_coverage_requirements",
        ["user_id", "state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_coverage_user_state",
        table_name="research_coverage_requirements",
    )
    op.drop_index(
        "ix_research_coverage_user_current_rank",
        table_name="research_coverage_requirements",
    )
    op.drop_table("research_coverage_requirements")
    op.drop_constraint(
        "ck_stock_prices_currency_iso_shape", "stock_prices", type_="check"
    )
    op.drop_column("stock_prices", "currency")
