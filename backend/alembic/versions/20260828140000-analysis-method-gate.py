"""Add reviewed company analysis classification gate.

Revision ID: 20260828140000
Revises: 20260828130000
Create Date: 2026-08-28 14:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260828140000"
down_revision = "20260828130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_research_coverage_kind",
        "research_coverage_requirements",
        type_="check",
    )
    op.drop_constraint(
        "ck_research_coverage_state",
        "research_coverage_requirements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_research_coverage_kind",
        "research_coverage_requirements",
        "kind IN ('eod_price', 'value_line_current_report', 'valuation_input', "
        "'identity_review', 'cusip_review', 'method_applicability')",
    )
    op.create_check_constraint(
        "ck_research_coverage_state",
        "research_coverage_requirements",
        "state IN ('ready', 'missing', 'stale', 'blocked', 'in_progress', "
        "'failed', 'unsupported')",
    )
    op.create_table(
        "company_analysis_classifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stock_id", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("method_policy_version", sa.String(length=80), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=False),
        sa.Column(
            "evidence_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
        sa.Column("supersedes_classification_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "classification IN ('ordinary_operating', 'bank', 'insurer', "
            "'reit', 'high_sbc_acquisitive', 'cyclical_commodity')",
            name="ck_company_analysis_classifications_value",
        ),
        sa.CheckConstraint(
            "status IN ('reviewed', 'retired')",
            name="ck_company_analysis_classifications_status",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_company_analysis_classifications_interval",
        ),
        sa.CheckConstraint(
            "length(btrim(review_reason)) > 0",
            name="ck_company_analysis_classifications_reason",
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_classification_id"],
            ["company_analysis_classifications.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supersedes_classification_id",
            name="uq_company_analysis_classification_supersession",
        ),
    )
    op.create_index(
        "ix_company_analysis_classifications_stock_id",
        "company_analysis_classifications",
        ["stock_id"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_company_analysis_classification_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'company analysis classifications are append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_company_analysis_classifications_append_only
        BEFORE UPDATE OR DELETE ON company_analysis_classifications
        FOR EACH ROW EXECUTE FUNCTION reject_company_analysis_classification_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM company_analysis_classifications)
               OR EXISTS (
                   SELECT 1 FROM research_coverage_requirements
                   WHERE kind = 'method_applicability' OR state = 'unsupported'
               ) THEN
                RAISE EXCEPTION
                    'cannot downgrade analysis method gate while method state exists';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_company_analysis_classifications_append_only "
        "ON company_analysis_classifications"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_company_analysis_classification_mutation()")
    op.drop_index(
        "ix_company_analysis_classifications_stock_id",
        table_name="company_analysis_classifications",
    )
    op.drop_table("company_analysis_classifications")
    op.execute(
        "DELETE FROM research_coverage_requirements "
        "WHERE kind = 'method_applicability' OR state = 'unsupported'"
    )
    op.drop_constraint(
        "ck_research_coverage_state",
        "research_coverage_requirements",
        type_="check",
    )
    op.drop_constraint(
        "ck_research_coverage_kind",
        "research_coverage_requirements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_research_coverage_state",
        "research_coverage_requirements",
        "state IN ('ready', 'missing', 'stale', 'blocked', 'in_progress', 'failed')",
    )
    op.create_check_constraint(
        "ck_research_coverage_kind",
        "research_coverage_requirements",
        "kind IN ('eod_price', 'value_line_current_report', 'valuation_input', "
        "'identity_review', 'cusip_review')",
    )
