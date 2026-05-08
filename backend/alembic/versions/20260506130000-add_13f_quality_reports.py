"""Add 13F quality reports.

Revision ID: 20260506130000
Revises: 20260506124500
Create Date: 2026-05-06 13:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260506130000"
down_revision = "20260506124500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quality_reports_13f",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("quarter", sa.String(10), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("info_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unavailable_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("issues_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_job_id", sa.BigInteger(), sa.ForeignKey("job_runs.id"), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_quality_reports_13f_quarter", "quality_reports_13f", ["quarter"])
    op.create_index("ix_quality_reports_13f_status", "quality_reports_13f", ["status"])
    op.create_index("ix_quality_reports_13f_checked_at", "quality_reports_13f", ["checked_at"])


def downgrade() -> None:
    op.drop_index("ix_quality_reports_13f_checked_at", table_name="quality_reports_13f")
    op.drop_index("ix_quality_reports_13f_status", table_name="quality_reports_13f")
    op.drop_index("ix_quality_reports_13f_quarter", table_name="quality_reports_13f")
    op.drop_table("quality_reports_13f")
