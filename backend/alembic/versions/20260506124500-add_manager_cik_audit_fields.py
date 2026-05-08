"""Add manager CIK audit fields.

Revision ID: 20260506124500
Revises: 20260506123000
Create Date: 2026-05-06 12:45:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260506124500"
down_revision = "20260506123000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("institution_managers", sa.Column("candidate_cik", sa.String(10), nullable=True))
    op.add_column("institution_managers", sa.Column("candidate_legal_name", sa.Text(), nullable=True))
    op.add_column("institution_managers", sa.Column("candidate_similarity_score", sa.Float(), nullable=True))
    op.add_column("institution_managers", sa.Column("candidate_source", sa.String(80), nullable=True))
    op.add_column("institution_managers", sa.Column("candidate_evidence_url", sa.Text(), nullable=True))
    op.add_column("institution_managers", sa.Column("candidate_found_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("institution_managers", sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True))
    op.add_column("institution_managers", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("institution_managers", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column(
        "institution_managers",
        sa.Column("prior_rejected_candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_foreign_key(
        "fk_institution_managers_reviewed_by_user_id_users",
        "institution_managers",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
    )
    op.create_index("ix_institution_managers_candidate_cik", "institution_managers", ["candidate_cik"])


def downgrade() -> None:
    op.drop_index("ix_institution_managers_candidate_cik", table_name="institution_managers")
    op.drop_constraint(
        "fk_institution_managers_reviewed_by_user_id_users",
        "institution_managers",
        type_="foreignkey",
    )
    op.drop_column("institution_managers", "prior_rejected_candidates")
    op.drop_column("institution_managers", "review_note")
    op.drop_column("institution_managers", "reviewed_at")
    op.drop_column("institution_managers", "reviewed_by_user_id")
    op.drop_column("institution_managers", "candidate_found_at")
    op.drop_column("institution_managers", "candidate_evidence_url")
    op.drop_column("institution_managers", "candidate_source")
    op.drop_column("institution_managers", "candidate_similarity_score")
    op.drop_column("institution_managers", "candidate_legal_name")
    op.drop_column("institution_managers", "candidate_cik")
