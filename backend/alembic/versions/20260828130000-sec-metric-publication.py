"""Add canonical SEC metric publication audit.

Revision ID: 20260828130000
Revises: 20260828120000
Create Date: 2026-08-28 13:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260828130000"
down_revision = "20260828120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "metric_facts", "user_id", existing_type=sa.Integer(), nullable=True
    )
    op.create_check_constraint(
        "ck_metric_facts_public_sec_owner",
        "metric_facts",
        "(source_type = 'sec' AND user_id IS NULL) OR "
        "(source_type <> 'sec' AND user_id IS NOT NULL)",
    )
    op.create_table(
        "sec_metric_publications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("raw_fact_id", sa.BigInteger(), nullable=False),
        sa.Column("metric_fact_id", sa.Integer(), nullable=True),
        sa.Column("mapping_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("canonical_metric_key", sa.Text(), nullable=True),
        sa.Column("canonical_unit", sa.String(length=40), nullable=True),
        sa.Column("period_type", sa.String(length=24), nullable=True),
        sa.Column("period_end_date", sa.Date(), nullable=True),
        sa.Column("knowledge_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "decision_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('published', 'unresolved', 'rejected')",
            name="ck_sec_metric_publications_status",
        ),
        sa.CheckConstraint(
            "(status = 'published' AND metric_fact_id IS NOT NULL "
            "AND canonical_metric_key IS NOT NULL AND period_type IS NOT NULL "
            "AND period_end_date IS NOT NULL) OR "
            "(status <> 'published' AND metric_fact_id IS NULL)",
            name="ck_sec_metric_publications_shape",
        ),
        sa.ForeignKeyConstraint(
            ["raw_fact_id"], ["sec_raw_xbrl_facts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["metric_fact_id"], ["metric_facts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "raw_fact_id",
            "mapping_version",
            name="uq_sec_metric_publications_raw_mapping",
        ),
    )
    op.create_index(
        "ix_sec_metric_publications_raw_fact_id",
        "sec_metric_publications",
        ["raw_fact_id"],
    )
    op.execute(
        """
        CREATE TRIGGER trg_sec_metric_publications_append_only
        BEFORE UPDATE OR DELETE ON sec_metric_publications
        FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM sec_metric_publications)
               OR EXISTS (SELECT 1 FROM metric_facts WHERE source_type = 'sec') THEN
                RAISE EXCEPTION
                    'cannot downgrade canonical SEC publication while lineage exists';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_metric_publications_append_only "
        "ON sec_metric_publications"
    )
    op.drop_index(
        "ix_sec_metric_publications_raw_fact_id",
        table_name="sec_metric_publications",
    )
    op.drop_table("sec_metric_publications")
    op.drop_constraint(
        "ck_metric_facts_public_sec_owner", "metric_facts", type_="check"
    )
    op.alter_column(
        "metric_facts", "user_id", existing_type=sa.Integer(), nullable=False
    )
