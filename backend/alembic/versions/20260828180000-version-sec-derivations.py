"""Version SEC derivations by their complete input identity.

Revision ID: 20260828180000
Revises: 20260828170000
Create Date: 2026-08-28 18:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828180000"
down_revision = "20260828170000"
branch_labels = None
depends_on = None


def _replace_sec_metric_fact_guard(*, forbid_restore: bool) -> None:
    restore_guard = (
        """
            IF OLD.source_type = 'sec'
               AND OLD.is_current = false
               AND NEW.is_current = true THEN
                RAISE EXCEPTION
                    'retired canonical SEC metric facts cannot be restored to current';
            END IF;
        """
        if forbid_restore
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION enforce_sec_metric_fact_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.source_type = 'sec' THEN
                    RAISE EXCEPTION 'canonical SEC metric facts are retained';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.source_type = 'sec' AND (
                to_jsonb(NEW) - 'is_current' - 'updated_at'
                IS DISTINCT FROM
                to_jsonb(OLD) - 'is_current' - 'updated_at'
            ) THEN
                RAISE EXCEPTION
                    'canonical SEC metric fact provenance and value are immutable';
            END IF;
            {restore_guard}
            RETURN NEW;
        END;
        $$;
        """
    )


def upgrade() -> None:
    op.add_column(
        "sec_metric_publications",
        sa.Column(
            "derivation_key",
            sa.String(length=64),
            server_default="direct",
            nullable=False,
        ),
    )
    op.drop_constraint(
        "uq_sec_metric_publications_raw_mapping_role",
        "sec_metric_publications",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sec_metric_publications_raw_mapping_role_derivation",
        "sec_metric_publications",
        [
            "raw_fact_id",
            "mapping_version",
            "publication_role",
            "derivation_key",
        ],
    )
    _replace_sec_metric_fact_guard(forbid_restore=True)


def downgrade() -> None:
    # The preceding schema cannot represent multiple input versions for one
    # derived raw fact. Refuse before changing a trigger or constraint.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM sec_metric_publications
                WHERE publication_role = 'derived_discrete_quarter'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade versioned SEC derivation lineage';
            END IF;
        END;
        $$
        """
    )
    _replace_sec_metric_fact_guard(forbid_restore=False)
    op.drop_constraint(
        "uq_sec_metric_publications_raw_mapping_role_derivation",
        "sec_metric_publications",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sec_metric_publications_raw_mapping_role",
        "sec_metric_publications",
        ["raw_fact_id", "mapping_version", "publication_role"],
    )
    op.drop_column("sec_metric_publications", "derivation_key")
