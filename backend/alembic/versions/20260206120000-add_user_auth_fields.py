"""Add authentication fields to users table.

Adds hashed_password, role, tier, is_active, updated_at to support
multi-user RBAC. Existing rows get a placeholder password hash and
role='user' (the separate migrate_user_1.py script promotes user_id=1
to admin).

Revision ID: 3c4d5e6f7a8b
Revises: 2b9f6b3d4c8a
Create Date: 2026-02-06 12:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3c4d5e6f7a8b"
down_revision = "2b9f6b3d4c8a"
branch_labels = None
depends_on = None

# Placeholder bcrypt hash for "changeme" – forces password reset on first real login.
_PLACEHOLDER_HASH = "$2b$12$placeholderHashForExistingUsersXXXXXXXXXXXXXXXXXXXX"


def upgrade() -> None:
    # 1. Add columns with defaults so existing rows are backfilled automatically.
    op.add_column(
        "users",
        sa.Column(
            "hashed_password",
            sa.String(),
            nullable=False,
            server_default=_PLACEHOLDER_HASH,
        ),
    )
    op.add_column(
        "users",
        sa.Column("role", sa.String(), nullable=False, server_default="user"),
    )
    op.add_column(
        "users",
        sa.Column("tier", sa.String(), nullable=False, server_default="free"),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # 2. Drop server_default for hashed_password after backfill —
    #    new rows must supply a real hash explicitly.
    op.alter_column("users", "hashed_password", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "updated_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "tier")
    op.drop_column("users", "role")
    op.drop_column("users", "hashed_password")
