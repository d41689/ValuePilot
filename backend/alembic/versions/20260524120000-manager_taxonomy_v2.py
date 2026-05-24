"""manager taxonomy v2 — two-layer label + metadata

Adds the value-investor-oriented taxonomy to ``institution_managers``:

- ``style_primary`` (NOT NULL, default ``unknown``): the primary investment
  DNA — value_deep / value_concentrated / quality_compounder / activist /
  growth_long_short / special_situations / multi_strategy_macro /
  endowment_passive / unknown.
- ``capital_structure`` (NOT NULL, default ``unknown``): permanent_capital /
  locked_lp / standard_lp / mutual_fund_etf / endowment_foundation / unknown.
- ``market_cap_focus`` (nullable): micro / small / mid / large / mega / all.
- ``geo_focus`` (nullable): us / global / em / europe / asia.
- ``historical_turnover`` (nullable): low / med / high.
- ``position_concentration_top10_pct`` (nullable Numeric(6,2)).
- ``ideology_tags`` (nullable JSONB list).

Legacy ``manager_type`` is kept and continues to be the column read by
Oracle's Lens. Seeding derives ``manager_type`` from ``style_primary`` via
``app.services.oracles_lens.manager_style.derive_legacy_manager_type``.

Task doc: ``docs/tasks/2026-05-24_manager-taxonomy-v2.md``

Revision ID: 20260524120000
Revises: 20260521120000
Create Date: 2026-05-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260524120000"
down_revision = "20260521120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "institution_managers",
        sa.Column(
            "style_primary",
            sa.String(length=40),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "institution_managers",
        sa.Column(
            "capital_structure",
            sa.String(length=40),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "institution_managers",
        sa.Column("market_cap_focus", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "institution_managers",
        sa.Column("geo_focus", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "institution_managers",
        sa.Column("historical_turnover", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "institution_managers",
        sa.Column(
            "position_concentration_top10_pct",
            sa.Numeric(6, 2),
            nullable=True,
        ),
    )
    op.add_column(
        "institution_managers",
        sa.Column(
            "ideology_tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_institution_managers_style_primary",
        "institution_managers",
        ["style_primary"],
    )
    op.create_index(
        "ix_institution_managers_capital_structure",
        "institution_managers",
        ["capital_structure"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_institution_managers_capital_structure",
        table_name="institution_managers",
    )
    op.drop_index(
        "ix_institution_managers_style_primary",
        table_name="institution_managers",
    )
    op.drop_column("institution_managers", "ideology_tags")
    op.drop_column("institution_managers", "position_concentration_top10_pct")
    op.drop_column("institution_managers", "historical_turnover")
    op.drop_column("institution_managers", "geo_focus")
    op.drop_column("institution_managers", "market_cap_focus")
    op.drop_column("institution_managers", "capital_structure")
    op.drop_column("institution_managers", "style_primary")
