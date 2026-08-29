"""Retain account-erasure files while another document references the blob.

Revision ID: 20260828210000
Revises: 20260828200000
Create Date: 2026-08-28 21:00:00
"""

from alembic import op


revision = "20260828210000"
down_revision = "20260828200000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_account_erasure_file_deletions_status",
        "account_erasure_file_deletions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_erasure_file_deletions_status",
        "account_erasure_file_deletions",
        "status IN ('pending', 'deleted', 'failed', 'retained_shared')",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM account_erasure_file_deletions
                WHERE status = 'retained_shared'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade shared erasure storage while retained rows exist';
            END IF;
        END;
        $$
        """
    )
    op.drop_constraint(
        "ck_account_erasure_file_deletions_status",
        "account_erasure_file_deletions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_erasure_file_deletions_status",
        "account_erasure_file_deletions",
        "status IN ('pending', 'deleted', 'failed')",
    )
