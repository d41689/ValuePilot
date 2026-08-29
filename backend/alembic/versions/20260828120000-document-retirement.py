"""Add policy-owned document retirement state.

Revision ID: 20260828120000
Revises: 20260827120000
Create Date: 2026-08-28 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828120000"
down_revision = "20260827120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pdf_documents",
        sa.Column(
            "lifecycle_state",
            sa.String(length=20),
            server_default="active",
            nullable=False,
        ),
    )
    op.add_column(
        "pdf_documents",
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pdf_documents",
        sa.Column("retired_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pdf_documents",
        sa.Column("retirement_reason", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_pdf_documents_retired_by_user_id_users",
        "pdf_documents",
        "users",
        ["retired_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_pdf_documents_lifecycle_state",
        "pdf_documents",
        "lifecycle_state IN ('active', 'archived', 'erased')",
    )
    op.create_check_constraint(
        "ck_pdf_documents_retirement_shape",
        "pdf_documents",
        "(lifecycle_state = 'active' AND retired_at IS NULL "
        "AND retired_by_user_id IS NULL AND retirement_reason IS NULL) OR "
        "(lifecycle_state IN ('archived', 'erased') AND retired_at IS NOT NULL "
        "AND retirement_reason IS NOT NULL AND length(btrim(retirement_reason)) > 0)",
    )
    op.create_index(
        "ix_pdf_documents_user_lifecycle",
        "pdf_documents",
        ["user_id", "lifecycle_state"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pdf_documents
                WHERE lifecycle_state <> 'active'
                   OR retired_at IS NOT NULL
                   OR retired_by_user_id IS NOT NULL
                   OR retirement_reason IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade document retirement while lifecycle history exists';
            END IF;
        END;
        $$
        """
    )
    op.drop_index("ix_pdf_documents_user_lifecycle", table_name="pdf_documents")
    op.drop_constraint(
        "ck_pdf_documents_retirement_shape", "pdf_documents", type_="check"
    )
    op.drop_constraint(
        "ck_pdf_documents_lifecycle_state", "pdf_documents", type_="check"
    )
    op.drop_constraint(
        "fk_pdf_documents_retired_by_user_id_users",
        "pdf_documents",
        type_="foreignkey",
    )
    op.drop_column("pdf_documents", "retirement_reason")
    op.drop_column("pdf_documents", "retired_by_user_id")
    op.drop_column("pdf_documents", "retired_at")
    op.drop_column("pdf_documents", "lifecycle_state")
