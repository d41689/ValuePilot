"""mvp4-08 quality_report is_dry_run

Adds an explicit ``is_dry_run`` boolean to ``quality_reports_13f`` so
dashboards can filter dry-run runs (historical-backfill validation
passes) out of real quality aggregations. Existing rows default to
``FALSE`` — they are interpreted as production runs.

Revision ID: 20260512120000
Revises: 20260511140000
Create Date: 2026-05-12 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260512120000"
down_revision = "20260511140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quality_reports_13f",
        sa.Column(
            "is_dry_run",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("quality_reports_13f", "is_dry_run")
