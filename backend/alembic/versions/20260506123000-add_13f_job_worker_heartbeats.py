"""Add 13F job worker heartbeats.

Revision ID: 20260506123000
Revises: 20260506120000
Create Date: 2026-05-06 12:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260506123000"
down_revision = "20260506120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_runs", sa.Column("worker_id", sa.String(120), nullable=True))
    op.add_column("job_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "job_worker_heartbeats",
        sa.Column("worker_id", sa.String(120), primary_key=True),
        sa.Column("worker_type", sa.String(60), nullable=False, server_default="13f_admin"),
        sa.Column("hostname", sa.String(120), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="idle"),
        sa.Column("current_job_id", sa.BigInteger(), sa.ForeignKey("job_runs.id"), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_worker_heartbeats_status", "job_worker_heartbeats", ["status"])
    op.create_index("ix_job_worker_heartbeats_last_heartbeat_at", "job_worker_heartbeats", ["last_heartbeat_at"])


def downgrade() -> None:
    op.drop_index("ix_job_worker_heartbeats_last_heartbeat_at", table_name="job_worker_heartbeats")
    op.drop_index("ix_job_worker_heartbeats_status", table_name="job_worker_heartbeats")
    op.drop_table("job_worker_heartbeats")
    op.drop_column("job_runs", "heartbeat_at")
    op.drop_column("job_runs", "worker_id")
