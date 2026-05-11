"""13f mvp3 value unit overrides

Revision ID: 20260511130000
Revises: 20260511120000
Create Date: 2026-05-11 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260511130000"
down_revision = "20260511120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "filing_value_unit_overrides",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_id", sa.BigInteger(), nullable=False),
        sa.Column("accession_number", sa.String(length=20), nullable=False),
        sa.Column("old_parse_rule", sa.String(length=80), nullable=False),
        sa.Column("new_override_value", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewer_id", sa.BigInteger(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_parse_run_id", sa.BigInteger(), nullable=True),
        sa.Column("result_parse_run_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="pending_reparse", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["baseline_parse_run_id"], ["parse_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["filing_id"], ["filings_13f.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["result_parse_run_id"], ["parse_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_filing_value_unit_overrides_filing_id",
        "filing_value_unit_overrides",
        ["filing_id"],
        unique=False,
    )
    op.create_index(
        "ix_filing_value_unit_overrides_accession",
        "filing_value_unit_overrides",
        ["accession_number"],
        unique=False,
    )
    op.create_index(
        "ix_filing_value_unit_overrides_status",
        "filing_value_unit_overrides",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_filing_value_unit_overrides_reviewed_at",
        "filing_value_unit_overrides",
        ["reviewed_at"],
        unique=False,
    )

    op.add_column(
        "filings_13f",
        sa.Column("effective_value_unit_override", sa.String(length=20), server_default="infer", nullable=False),
    )
    op.add_column(
        "filings_13f",
        sa.Column("effective_value_unit_override_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_filings_13f_effective_value_unit_override",
        "filings_13f",
        "filing_value_unit_overrides",
        ["effective_value_unit_override_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_filings_13f_effective_value_unit_override",
        "filings_13f",
        ["effective_value_unit_override"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_filings_13f_effective_value_unit_override", table_name="filings_13f")
    op.drop_constraint("fk_filings_13f_effective_value_unit_override", "filings_13f", type_="foreignkey")
    op.drop_column("filings_13f", "effective_value_unit_override_id")
    op.drop_column("filings_13f", "effective_value_unit_override")

    op.drop_index("ix_filing_value_unit_overrides_reviewed_at", table_name="filing_value_unit_overrides")
    op.drop_index("ix_filing_value_unit_overrides_status", table_name="filing_value_unit_overrides")
    op.drop_index("ix_filing_value_unit_overrides_accession", table_name="filing_value_unit_overrides")
    op.drop_index("ix_filing_value_unit_overrides_filing_id", table_name="filing_value_unit_overrides")
    op.drop_table("filing_value_unit_overrides")
