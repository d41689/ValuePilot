"""mvp4 01 oracles lens score schema

Creates ``oracles_lens_signals`` and ``oracles_lens_score_components``,
the precomputed-scoring tables consumed by MVP4-02 through MVP4-06.

Per the MVP4-01 pre-start condition resolutions:

- Storage = separate ``oracles_lens_signals`` table (not column
  extensions on existing tables).
- ``score_version`` ships as a string column from day one.
- Components live in a separate ``oracles_lens_score_components`` table
  rather than a JSONB blob — TL D5 revision, mirrors
  ``quality_findings_13f``.
- ``source_job_id`` FK → ``job_runs.id`` connects each score row to the
  ``oracles_lens_score_backfill`` JobRun that produced it.

Revision ID: 20260511140000
Revises: 20260511130000
Create Date: 2026-05-11 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260511140000"
down_revision = "20260511130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oracles_lens_signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stock_id", sa.BigInteger(), nullable=False),
        sa.Column("report_quarter", sa.String(length=10), nullable=False),
        sa.Column("quarter_end_date", sa.Date(), nullable=False),
        sa.Column("score_version", sa.String(length=20), nullable=False),
        sa.Column("raw_consensus_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("signal_weighted_consensus_score", sa.Numeric(18, 6), nullable=True),
        sa.Column("conviction_score", sa.Numeric(18, 6), nullable=True),
        sa.Column("distinctive_consensus_score", sa.Numeric(18, 6), nullable=True),
        sa.Column("add_intensity", sa.Numeric(18, 6), nullable=True),
        sa.Column("holding_streak_quarters", sa.Integer(), nullable=True),
        sa.Column("score_confidence", sa.String(length=20), nullable=False),
        sa.Column("caution_flag_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("score_explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_job_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"]),
        sa.ForeignKeyConstraint(["source_job_id"], ["job_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stock_id",
            "report_quarter",
            "score_version",
            name="uq_oracles_lens_signals_stock_quarter_version",
        ),
    )
    op.create_index(
        "idx_oracles_lens_signals_quarter_version",
        "oracles_lens_signals",
        ["report_quarter", "score_version"],
        unique=False,
    )
    op.create_index(
        "idx_oracles_lens_signals_ranking",
        "oracles_lens_signals",
        ["score_version", "signal_weighted_consensus_score"],
        unique=False,
    )

    op.create_table(
        "oracles_lens_score_components",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("score_id", sa.BigInteger(), nullable=False),
        sa.Column("component_name", sa.String(length=80), nullable=False),
        sa.Column("manager_id", sa.BigInteger(), nullable=True),
        sa.Column("numeric_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("string_value", sa.String(length=120), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["score_id"], ["oracles_lens_signals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["manager_id"], ["institution_managers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "score_id",
            "component_name",
            "manager_id",
            name="uq_oracles_lens_score_components_per_score_component_manager",
        ),
    )
    op.create_index(
        "idx_oracles_lens_score_components_score_component",
        "oracles_lens_score_components",
        ["score_id", "component_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_oracles_lens_score_components_score_component",
        table_name="oracles_lens_score_components",
    )
    op.drop_table("oracles_lens_score_components")

    op.drop_index("idx_oracles_lens_signals_ranking", table_name="oracles_lens_signals")
    op.drop_index("idx_oracles_lens_signals_quarter_version", table_name="oracles_lens_signals")
    op.drop_table("oracles_lens_signals")
