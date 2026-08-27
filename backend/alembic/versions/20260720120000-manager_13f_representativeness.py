"""versioned manager 13F representativeness projection

Revision ID: 20260720120000
Revises: 20260524120000
Create Date: 2026-07-20 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720120000"
down_revision = "20260524120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "institution_managers",
        sa.Column(
            "thirteenf_representativeness",
            sa.String(length=24),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "institution_managers",
        sa.Column("representativeness_policy_version", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "institution_managers",
        sa.Column("representativeness_reviewer", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "institution_managers",
        sa.Column("representativeness_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "institution_managers",
        sa.Column("representativeness_rationale", sa.Text(), nullable=True),
    )
    op.add_column(
        "institution_managers",
        sa.Column(
            "representativeness_evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_institution_managers_13f_representativeness",
        "institution_managers",
        "thirteenf_representativeness IN "
        "('faithful', 'partial', 'unrepresentative', 'unknown')",
    )
    op.create_table(
        "institution_manager_representativeness_reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("manager_id", sa.BigInteger(), nullable=False),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("policy_version", sa.String(length=48), nullable=False),
        sa.Column("reviewer", sa.String(length=120), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "classification IN ('faithful', 'partial', 'unrepresentative', 'unknown')",
            name="ck_manager_representativeness_review_classification",
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"], ["institution_managers.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "manager_id",
            "policy_version",
            name="uq_manager_representativeness_review_policy",
        ),
    )
    op.create_index(
        "ix_manager_representativeness_reviews_manager_effective",
        "institution_manager_representativeness_reviews",
        ["manager_id", "effective_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_manager_representativeness_reviews_manager_effective",
        table_name="institution_manager_representativeness_reviews",
    )
    op.drop_table("institution_manager_representativeness_reviews")
    op.drop_constraint(
        "ck_institution_managers_13f_representativeness",
        "institution_managers",
        type_="check",
    )
    op.drop_column("institution_managers", "representativeness_evidence_json")
    op.drop_column("institution_managers", "representativeness_rationale")
    op.drop_column("institution_managers", "representativeness_reviewed_at")
    op.drop_column("institution_managers", "representativeness_reviewer")
    op.drop_column("institution_managers", "representativeness_policy_version")
    op.drop_column("institution_managers", "thirteenf_representativeness")
