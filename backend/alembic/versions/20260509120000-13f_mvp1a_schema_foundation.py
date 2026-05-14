"""13F MVP1A schema foundation.

Revision ID: 20260509120000
Revises: 20260507020000
Create Date: 2026-05-09 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260509120000"
down_revision = "20260507020000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("institution_managers", sa.Column("canonical_name", sa.Text(), nullable=True))
    op.add_column("institution_managers", sa.Column("edgar_legal_name", sa.Text(), nullable=True))
    op.add_column(
        "institution_managers",
        sa.Column("status", sa.String(20), nullable=False, server_default="candidate"),
    )
    op.add_column(
        "institution_managers",
        sa.Column("manager_type", sa.String(40), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "institution_managers",
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("institution_managers", sa.Column("source", sa.String(80), nullable=True))
    op.add_column("institution_managers", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column("institution_managers", sa.Column("confidence_score", sa.Integer(), nullable=True))
    op.add_column(
        "institution_managers",
        sa.Column("value_unit_override", sa.String(20), nullable=False, server_default="infer"),
    )
    op.add_column("institution_managers", sa.Column("confirmed_by", sa.BigInteger(), nullable=True))
    op.add_column("institution_managers", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "institution_managers",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("UPDATE institution_managers SET canonical_name = legal_name WHERE canonical_name IS NULL")
    op.execute("UPDATE institution_managers SET edgar_legal_name = legal_name WHERE edgar_legal_name IS NULL")
    op.execute(
        """
        UPDATE institution_managers
        SET status = CASE
            WHEN match_status = 'confirmed' THEN 'active'
            WHEN match_status = 'revoked' THEN 'needs_review'
            WHEN match_status = 'rejected' THEN 'ignored'
            ELSE 'candidate'
        END
        """
    )
    op.alter_column("institution_managers", "canonical_name", nullable=False)
    op.create_foreign_key(
        "fk_institution_managers_confirmed_by_users",
        "institution_managers",
        "users",
        ["confirmed_by"],
        ["id"],
    )
    op.create_index("ix_institution_managers_status", "institution_managers", ["status"])
    op.create_index("ix_institution_managers_cik_status", "institution_managers", ["cik", "status"])

    op.create_table(
        "edgar_sync_status",
        sa.Column("sync_date", sa.Date(), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("form_idx_url", sa.Text(), nullable=True),
        sa.Column("raw_document_id", sa.BigInteger(), sa.ForeignKey("raw_source_documents.id"), nullable=True),
        sa.Column("filings_seen_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tracked_13f_hr_found_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tracked_13f_nt_found_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_sync_status", "edgar_sync_status", ["status", "sync_date"])

    op.create_table(
        "no_index_expected_dates",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("holiday_name", sa.Text(), nullable=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_no_index_expected_dates_active", "no_index_expected_dates", ["active"])
    op.create_index("ix_no_index_expected_dates_source", "no_index_expected_dates", ["source"])

    op.add_column("job_runs", sa.Column("sync_date", sa.Date(), nullable=True))
    op.add_column("job_runs", sa.Column("lease_token", sa.String(120), nullable=True))
    op.add_column("job_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "job_runs",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_job_runs", "job_runs", ["status", "job_type", "created_at"])
    op.create_index("ix_job_runs_sync_date", "job_runs", ["sync_date"])
    op.create_index("ix_job_runs_lease_expires_at", "job_runs", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_lease_expires_at", table_name="job_runs")
    op.drop_index("ix_job_runs_sync_date", table_name="job_runs")
    op.drop_index("idx_job_runs", table_name="job_runs")
    op.drop_column("job_runs", "updated_at")
    op.drop_column("job_runs", "lease_expires_at")
    op.drop_column("job_runs", "lease_token")
    op.drop_column("job_runs", "sync_date")

    op.drop_index("ix_no_index_expected_dates_source", table_name="no_index_expected_dates")
    op.drop_index("ix_no_index_expected_dates_active", table_name="no_index_expected_dates")
    op.drop_table("no_index_expected_dates")

    op.drop_index("idx_sync_status", table_name="edgar_sync_status")
    op.drop_table("edgar_sync_status")

    op.drop_index("ix_institution_managers_cik_status", table_name="institution_managers")
    op.drop_index("ix_institution_managers_status", table_name="institution_managers")
    op.drop_constraint(
        "fk_institution_managers_confirmed_by_users",
        "institution_managers",
        type_="foreignkey",
    )
    op.drop_column("institution_managers", "updated_at")
    op.drop_column("institution_managers", "confirmed_at")
    op.drop_column("institution_managers", "confirmed_by")
    op.drop_column("institution_managers", "value_unit_override")
    op.drop_column("institution_managers", "confidence_score")
    op.drop_column("institution_managers", "source_url")
    op.drop_column("institution_managers", "source")
    op.drop_column("institution_managers", "is_featured")
    op.drop_column("institution_managers", "manager_type")
    op.drop_column("institution_managers", "status")
    op.drop_column("institution_managers", "edgar_legal_name")
    op.drop_column("institution_managers", "canonical_name")
