"""13F MVP3 quality findings.

Revision ID: 20260511120000
Revises: 20260510120000
Create Date: 2026-05-11 12:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260511120000"
down_revision = "20260510120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quality_findings_13f",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "validation_run_id",
            sa.BigInteger(),
            sa.ForeignKey("quality_reports_13f.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("quarter", sa.String(10), nullable=True),
        sa.Column("manager_id", sa.BigInteger(), sa.ForeignKey("institution_managers.id"), nullable=True),
        sa.Column("accession_number", sa.String(20), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_quality_findings_13f_run", "quality_findings_13f", ["validation_run_id"])
    op.create_index("ix_quality_findings_13f_rule", "quality_findings_13f", ["rule_code"])
    op.create_index("ix_quality_findings_13f_status", "quality_findings_13f", ["status"])
    op.create_index("ix_quality_findings_13f_quarter", "quality_findings_13f", ["quarter"])
    op.create_index("ix_quality_findings_13f_manager", "quality_findings_13f", ["manager_id"])
    op.create_index("ix_quality_findings_13f_accession", "quality_findings_13f", ["accession_number"])


def downgrade() -> None:
    op.drop_index("ix_quality_findings_13f_accession", table_name="quality_findings_13f")
    op.drop_index("ix_quality_findings_13f_manager", table_name="quality_findings_13f")
    op.drop_index("ix_quality_findings_13f_quarter", table_name="quality_findings_13f")
    op.drop_index("ix_quality_findings_13f_status", table_name="quality_findings_13f")
    op.drop_index("ix_quality_findings_13f_rule", table_name="quality_findings_13f")
    op.drop_index("ix_quality_findings_13f_run", table_name="quality_findings_13f")
    op.drop_table("quality_findings_13f")
