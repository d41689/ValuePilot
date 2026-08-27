"""Enforce append-only manager representativeness review decisions.

Revision ID: 20260826120000
Revises: 20260720173000
Create Date: 2026-08-26 12:00:00.000000
"""

from alembic import op


revision = "20260826120000"
down_revision = "20260720173000"
branch_labels = None
depends_on = None


_TABLE = "institution_manager_representativeness_reviews"
_TRIGGER = "trg_institution_manager_representativeness_reviews_append_only"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION reject_research_append_only_mutation()
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE}")
