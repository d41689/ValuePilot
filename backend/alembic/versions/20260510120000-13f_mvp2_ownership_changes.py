"""13F MVP2 ownership changes schema.

Revision ID: 20260510120000
Revises: 20260509140000
Create Date: 2026-05-10 12:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260510120000"
down_revision = "20260509140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ownership_changes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("manager_id", sa.BigInteger(), sa.ForeignKey("institution_managers.id"), nullable=False),
        sa.Column("stock_id", sa.BigInteger(), sa.ForeignKey("stocks.id"), nullable=True),
        sa.Column("report_quarter", sa.String(10), nullable=False),
        sa.Column("quarter_end_date", sa.Date(), nullable=False),
        sa.Column("previous_report_quarter", sa.String(10), nullable=True),
        sa.Column("previous_quarter_end_date", sa.Date(), nullable=True),
        sa.Column("current_filing_id", sa.BigInteger(), sa.ForeignKey("filings_13f.id"), nullable=True),
        sa.Column("previous_filing_id", sa.BigInteger(), sa.ForeignKey("filings_13f.id"), nullable=True),
        sa.Column("current_holding_id", sa.BigInteger(), sa.ForeignKey("holdings_13f.id"), nullable=True),
        sa.Column("previous_holding_id", sa.BigInteger(), sa.ForeignKey("holdings_13f.id"), nullable=True),
        sa.Column("current_parse_run_id", sa.BigInteger(), sa.ForeignKey("parse_runs.id"), nullable=True),
        sa.Column("previous_parse_run_id", sa.BigInteger(), sa.ForeignKey("parse_runs.id"), nullable=True),
        sa.Column("security_key", sa.String(120), nullable=False),
        sa.Column("current_cusip", sa.String(9), nullable=True),
        sa.Column("previous_cusip", sa.String(9), nullable=True),
        sa.Column("ssh_prnamt_type", sa.String(10), nullable=False, server_default="SH"),
        sa.Column("put_call", sa.String(10), nullable=True),
        sa.Column("position_type", sa.String(20), nullable=False, server_default="common"),
        sa.Column("change_status", sa.String(40), nullable=False),
        sa.Column("confidence_level", sa.String(40), nullable=False),
        sa.Column("is_primary_signal_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("caveat_codes", postgresql.JSONB(), nullable=True),
        sa.Column("unavailable_reason", sa.String(80), nullable=True),
        sa.Column("current_value_usd", sa.BigInteger(), nullable=True),
        sa.Column("previous_value_usd", sa.BigInteger(), nullable=True),
        sa.Column("value_delta_usd", sa.BigInteger(), nullable=True),
        sa.Column("value_delta_pct", sa.Numeric(18, 6), nullable=True),
        sa.Column("current_shares", sa.BigInteger(), nullable=True),
        sa.Column("previous_shares", sa.BigInteger(), nullable=True),
        sa.Column("share_delta", sa.BigInteger(), nullable=True),
        sa.Column("share_change_pct", sa.Numeric(18, 6), nullable=True),
        sa.Column("current_portfolio_weight_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("previous_portfolio_weight_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("mapping_confidence", sa.String(40), nullable=True),
        sa.Column("attribution_status", sa.String(40), nullable=True),
        sa.Column("has_confidential_treatment_caveat", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_combination_report_caveat", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_pending_amendment_caveat", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "uq_ownership_changes_manager_quarter_security_position",
        "ownership_changes",
        ["manager_id", "report_quarter", "security_key", "ssh_prnamt_type", "position_type"],
        unique=True,
    )
    op.create_index("idx_ownership_changes_stock_quarter", "ownership_changes", ["stock_id", "report_quarter"])
    op.create_index("idx_ownership_changes_manager_quarter", "ownership_changes", ["manager_id", "report_quarter"])
    op.create_index("idx_ownership_changes_change_status", "ownership_changes", ["change_status"])
    op.create_index("idx_ownership_changes_confidence", "ownership_changes", ["confidence_level"])
    op.create_index(
        "idx_ownership_changes_primary_signal",
        "ownership_changes",
        ["stock_id", "report_quarter"],
        postgresql_where=sa.text("is_primary_signal_eligible = true"),
    )


def downgrade() -> None:
    op.drop_index("idx_ownership_changes_primary_signal", table_name="ownership_changes")
    op.drop_index("idx_ownership_changes_confidence", table_name="ownership_changes")
    op.drop_index("idx_ownership_changes_change_status", table_name="ownership_changes")
    op.drop_index("idx_ownership_changes_manager_quarter", table_name="ownership_changes")
    op.drop_index("idx_ownership_changes_stock_quarter", table_name="ownership_changes")
    op.drop_index("uq_ownership_changes_manager_quarter_security_position", table_name="ownership_changes")
    op.drop_table("ownership_changes")
