"""Add 13F ingestion tables.

Revision ID: a1b2c3d4e5f6
Revises: 4d5e6f7a8b9c
Create Date: 2026-04-23 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "4d5e6f7a8b9c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "institution_managers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("cik", sa.String(10), nullable=True, unique=True),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("name_normalized", sa.Text(), nullable=True),
        sa.Column(
            "parent_manager_id",
            sa.BigInteger(),
            sa.ForeignKey("institution_managers.id"),
            nullable=True,
        ),
        sa.Column("dataroma_code", sa.String(20), nullable=True),
        sa.Column("match_status", sa.String(20), nullable=False, server_default="seeded"),
        sa.Column("is_superinvestor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dataroma_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_institution_managers_parent_manager_id",
        "institution_managers",
        ["parent_manager_id"],
    )
    op.create_index(
        "uq_institution_managers_dataroma_code",
        "institution_managers",
        ["dataroma_code"],
        unique=True,
        postgresql_where=sa.text("dataroma_code IS NOT NULL"),
    )

    op.create_table(
        "raw_source_documents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_system", sa.String(20), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("cik", sa.String(10), nullable=True),
        sa.Column("accession_no", sa.String(20), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("raw_sha256", sa.String(64), nullable=True),
        sa.Column("body_path", sa.Text(), nullable=False),
        sa.Column(
            "parse_status", sa.String(20), nullable=False, server_default="pending"
        ),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "uq_raw_source_documents_system_url",
        "raw_source_documents",
        ["source_system", "source_url"],
        unique=True,
    )

    op.create_table(
        "filings_13f",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "manager_id",
            sa.BigInteger(),
            sa.ForeignKey("institution_managers.id"),
            nullable=False,
        ),
        sa.Column("accession_no", sa.String(20), nullable=False, unique=True),
        sa.Column("period_of_report", sa.Date(), nullable=False),
        sa.Column("filed_at", sa.Date(), nullable=False),
        sa.Column("form_type", sa.String(10), nullable=False),
        sa.Column("amends_accession_no", sa.String(20), nullable=True),
        sa.Column("version_rank", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "is_latest_for_period",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "has_confidential_treatment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("reported_total_value_thousands", sa.BigInteger(), nullable=True),
        sa.Column("computed_total_value_thousands", sa.BigInteger(), nullable=True),
        sa.Column(
            "raw_primary_doc_id",
            sa.BigInteger(),
            sa.ForeignKey("raw_source_documents.id"),
            nullable=True,
        ),
        sa.Column(
            "raw_infotable_doc_id",
            sa.BigInteger(),
            sa.ForeignKey("raw_source_documents.id"),
            nullable=True,
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Partial unique index: only one filing per (manager, period) can be latest
    op.create_index(
        "uq_filings_13f_latest_per_period",
        "filings_13f",
        ["manager_id", "period_of_report"],
        unique=True,
        postgresql_where=sa.text("is_latest_for_period = TRUE"),
    )

    op.create_table(
        "holdings_13f",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "filing_id",
            sa.BigInteger(),
            sa.ForeignKey("filings_13f.id"),
            nullable=False,
        ),
        sa.Column("row_fingerprint", sa.String(64), nullable=False),
        sa.Column("cusip", sa.String(9), nullable=False),
        sa.Column("issuer_name", sa.Text(), nullable=False),
        sa.Column("title_of_class", sa.Text(), nullable=True),
        sa.Column("value_thousands", sa.BigInteger(), nullable=False),
        sa.Column("shares", sa.BigInteger(), nullable=True),
        sa.Column("share_type", sa.String(10), nullable=True),
        sa.Column("put_call", sa.String(10), nullable=True),
        sa.Column("investment_discretion", sa.String(10), nullable=True),
        sa.Column("voting_sole", sa.BigInteger(), nullable=True),
        sa.Column("voting_shared", sa.BigInteger(), nullable=True),
        sa.Column("voting_none", sa.BigInteger(), nullable=True),
        sa.Column(
            "stock_id",
            sa.BigInteger(),
            sa.ForeignKey("stocks.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "filing_id", "row_fingerprint", name="uq_holdings_13f_filing_fingerprint"
        ),
    )

    op.create_table(
        "cusip_ticker_map",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("cusip", sa.String(9), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=True),
        sa.Column("issuer_name", sa.Text(), nullable=True),
        sa.Column("security_type", sa.String(30), nullable=True),
        sa.Column("exchange", sa.String(30), nullable=True),
        sa.Column(
            "is_13f_reportable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("source", sa.String(20), nullable=True),
        sa.Column("mapping_reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(20), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "cusip", "valid_from", name="uq_cusip_ticker_map_cusip_valid_from"
        ),
    )


def downgrade() -> None:
    op.drop_table("cusip_ticker_map")
    op.drop_table("holdings_13f")
    op.drop_table("filings_13f")
    op.drop_table("raw_source_documents")
    op.drop_table("institution_managers")
