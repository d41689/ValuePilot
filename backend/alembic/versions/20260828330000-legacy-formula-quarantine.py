"""Quarantine unversioned user-formula outputs.

Revision ID: 20260828330000
Revises: 20260828320000
Create Date: 2026-08-29 09:00:00
"""

from alembic import op


revision = "20260828330000"
down_revision = "20260828320000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Older FormulaEngine rows identify themselves with formula_id but have no
    # exact input-fact/run lineage. Preserve them for audit, but never leave
    # them eligible as the current canonical output.
    op.execute(
        """
        UPDATE metric_facts
           SET is_current = false
         WHERE source_type = 'calculated'
           AND value_json ? 'formula_id'
           AND value_json->>'formula_lineage_version'
               IS DISTINCT FROM 'formula-v2'
           AND is_current = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM metric_facts
                 WHERE source_type = 'calculated'
                   AND value_json ? 'formula_id'
                   AND value_json->>'formula_lineage_version'
                       IS DISTINCT FROM 'formula-v2'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade legacy formula quarantine while unversioned formula history exists';
            END IF;
        END;
        $$;
        """
    )
