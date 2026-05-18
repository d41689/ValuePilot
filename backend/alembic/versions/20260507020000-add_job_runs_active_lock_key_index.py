"""Add partial unique index on job_runs.lock_key for active statuses.

Prevents concurrent callers from inserting duplicate active jobs for the same
lock_key (TOCTOU between SELECT and INSERT in trigger_job).

Revision ID: 20260507020000
Revises: 20260506131500
Create Date: 2026-05-07 02:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260507020000"
down_revision = "20260506131500"
branch_labels = None
depends_on = None

_INDEX = "uq_job_runs_active_lock_key"
_TABLE = "job_runs"
_WHERE = "status IN ('queued', 'running', 'cancel_requested')"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX} "
            f"ON {_TABLE} (lock_key) WHERE {_WHERE}"
        )
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
