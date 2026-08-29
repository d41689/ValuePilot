"""Add independent direct and derived SEC publication roles.

Revision ID: 20260828150000
Revises: 20260828140000
Create Date: 2026-08-28 15:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828150000"
down_revision = "20260828140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sec_metric_publications",
        sa.Column(
            "publication_role",
            sa.String(length=40),
            server_default="direct",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_sec_metric_publications_role",
        "sec_metric_publications",
        "publication_role IN ('direct', 'derived_discrete_quarter')",
    )
    op.drop_constraint(
        "uq_sec_metric_publications_raw_mapping",
        "sec_metric_publications",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sec_metric_publications_raw_mapping_role",
        "sec_metric_publications",
        ["raw_fact_id", "mapping_version", "publication_role"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM sec_metric_publications
                WHERE publication_role = 'derived_discrete_quarter'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade SEC publication roles while derived lineage exists';
            END IF;
        END;
        $$
        """
    )
    op.drop_constraint(
        "uq_sec_metric_publications_raw_mapping_role",
        "sec_metric_publications",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sec_metric_publications_raw_mapping",
        "sec_metric_publications",
        ["raw_fact_id", "mapping_version"],
    )
    op.drop_constraint(
        "ck_sec_metric_publications_role",
        "sec_metric_publications",
        type_="check",
    )
    op.drop_column("sec_metric_publications", "publication_role")
