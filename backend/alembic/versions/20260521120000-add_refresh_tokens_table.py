"""Add refresh_tokens table

Gives refresh tokens a server-side lifecycle so they can be revoked (logout)
and so a replayed/already-rotated token can be detected. Each issued refresh
token gets one row keyed by its JWT ``jti``; rows sharing a ``family_id`` form
one rotation lineage and are revoked together.

Resolves the docs/BACKLOG.md item "Refresh tokens have no revocation / reuse
detection" — see docs/tasks/2026-05-21_refresh-token-revocation.md.

Revision ID: 20260521120000
Revises: 20260513140000
Create Date: 2026-05-21 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260521120000"
down_revision = "20260513140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.String(length=64), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_refresh_tokens_jti"),
    )
    op.create_index(
        "ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"]
    )
    op.create_index(
        "ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
