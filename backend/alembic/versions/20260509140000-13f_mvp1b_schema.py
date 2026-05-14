"""13F MVP1B filing parse holdings schema.

Revision ID: 20260509140000
Revises: 20260509120000
Create Date: 2026-05-09 14:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260509140000"
down_revision = "20260509120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("filings_13f", sa.Column("accession_number", sa.String(20), nullable=True))
    op.add_column("filings_13f", sa.Column("cik", sa.String(10), nullable=True))
    op.add_column("filings_13f", sa.Column("report_type", sa.String(40), nullable=True))
    op.add_column("filings_13f", sa.Column("coverage_completeness", sa.String(30), nullable=False, server_default="unknown"))
    op.add_column("filings_13f", sa.Column("coverage_type", sa.String(40), nullable=False, server_default="normal"))
    op.add_column("filings_13f", sa.Column("other_managers_included", postgresql.JSONB(), nullable=True))
    op.add_column("filings_13f", sa.Column("other_managers_reporting", postgresql.JSONB(), nullable=True))
    op.add_column("filings_13f", sa.Column("confidential_treatment_status", sa.String(40), nullable=False, server_default="none"))
    op.add_column("filings_13f", sa.Column("filing_date", sa.Date(), nullable=True))
    op.add_column("filings_13f", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("filings_13f", sa.Column("report_quarter", sa.String(10), nullable=True))
    op.add_column("filings_13f", sa.Column("quarter_end_date", sa.Date(), nullable=True))
    op.add_column("filings_13f", sa.Column("official_filing_deadline", sa.Date(), nullable=True))
    op.add_column("filings_13f", sa.Column("is_amendment", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("filings_13f", sa.Column("amends_accession_number", sa.String(20), nullable=True))
    op.add_column("filings_13f", sa.Column("amendment_type", sa.String(80), nullable=True))
    op.add_column("filings_13f", sa.Column("amendment_type_raw", sa.Text(), nullable=True))
    op.add_column("filings_13f", sa.Column("is_active_for_manager_period", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("filings_13f", sa.Column("raw_filing_url", sa.Text(), nullable=True))
    op.add_column("filings_13f", sa.Column("raw_infotable_url", sa.Text(), nullable=True))
    op.add_column("filings_13f", sa.Column("parse_status", sa.String(30), nullable=False, server_default="pending"))
    op.add_column("filings_13f", sa.Column("parse_warning", sa.Text(), nullable=True))
    op.add_column("filings_13f", sa.Column("parse_error", sa.Text(), nullable=True))
    op.add_column("filings_13f", sa.Column("parser_version", sa.String(80), nullable=True))
    op.add_column("filings_13f", sa.Column("form_spec_version", sa.String(80), nullable=True))
    op.add_column("filings_13f", sa.Column("xml_schema_version", sa.String(120), nullable=True))
    op.add_column("filings_13f", sa.Column("total_13f_reported_value_usd", sa.BigInteger(), nullable=True))
    op.add_column("filings_13f", sa.Column("total_13f_common_value_usd", sa.BigInteger(), nullable=True))
    op.add_column("filings_13f", sa.Column("holdings_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("filings_13f", sa.Column("common_holdings_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("filings_13f", sa.Column("amendment_status", sa.String(40), nullable=False, server_default="no_amendments_seen"))
    op.add_column("filings_13f", sa.Column("amendment_sort_warning", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("filings_13f", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.execute("UPDATE filings_13f SET accession_number = accession_no WHERE accession_number IS NULL")
    op.execute("UPDATE filings_13f SET filing_date = filed_at WHERE filing_date IS NULL")
    op.execute("UPDATE filings_13f SET amends_accession_number = amends_accession_no WHERE amends_accession_number IS NULL")
    op.create_index("uq_filings_13f_accession_number", "filings_13f", ["accession_number"], unique=True)
    op.create_index(
        "uq_active_filing_per_manager_period",
        "filings_13f",
        ["manager_id", "quarter_end_date"],
        unique=True,
        postgresql_where=sa.text("is_active_for_manager_period = true"),
    )
    op.create_index("idx_filings_manager_qend", "filings_13f", ["manager_id", "quarter_end_date"])
    op.create_index("idx_filings_manager_quarter", "filings_13f", ["manager_id", "report_quarter"])
    op.create_index("idx_filings_active", "filings_13f", ["is_active_for_manager_period"])
    op.create_index("idx_filings_parser_version", "filings_13f", ["parser_version"])

    op.create_table(
        "parse_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("accession_number", sa.String(20), nullable=False),
        sa.Column("job_run_id", sa.BigInteger(), sa.ForeignKey("job_runs.id"), nullable=True),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("fingerprint_version", sa.String(40), nullable=False, server_default="v1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("holdings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_parse_runs_accession", "parse_runs", ["accession_number"])
    op.create_index(
        "uq_parse_runs_current_accession",
        "parse_runs",
        ["accession_number"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    op.add_column("holdings_13f", sa.Column("parse_run_id", sa.BigInteger(), sa.ForeignKey("parse_runs.id"), nullable=True))
    op.add_column("holdings_13f", sa.Column("manager_id", sa.BigInteger(), sa.ForeignKey("institution_managers.id"), nullable=True))
    op.add_column("holdings_13f", sa.Column("accession_number", sa.String(20), nullable=True))
    op.add_column("holdings_13f", sa.Column("report_quarter", sa.String(10), nullable=True))
    op.add_column("holdings_13f", sa.Column("quarter_end_date", sa.Date(), nullable=True))
    op.add_column("holdings_13f", sa.Column("name_of_issuer", sa.Text(), nullable=True))
    op.add_column("holdings_13f", sa.Column("value_raw", sa.String(40), nullable=True))
    op.add_column("holdings_13f", sa.Column("value_unit_raw", sa.String(20), nullable=True))
    op.add_column("holdings_13f", sa.Column("value_parse_rule", sa.String(40), nullable=True))
    op.add_column("holdings_13f", sa.Column("value_usd", sa.BigInteger(), nullable=True))
    op.add_column("holdings_13f", sa.Column("ssh_prnamt", sa.BigInteger(), nullable=True))
    op.add_column("holdings_13f", sa.Column("ssh_prnamt_type", sa.String(10), nullable=True))
    op.add_column("holdings_13f", sa.Column("other_managers_raw", sa.Text(), nullable=True))
    op.add_column("holdings_13f", sa.Column("holding_attribution_status", sa.String(40), nullable=True))
    op.add_column("holdings_13f", sa.Column("cusip_mapping_status", sa.String(40), nullable=False, server_default="pending_mapping"))
    op.add_column("holdings_13f", sa.Column("portfolio_weight_pct", sa.Numeric(12, 6), nullable=True))
    op.add_column("holdings_13f", sa.Column("holding_row_fingerprint", sa.String(64), nullable=True))
    op.add_column("holdings_13f", sa.Column("fingerprint_version", sa.String(40), nullable=False, server_default="v1"))
    op.add_column("holdings_13f", sa.Column("source_row_index", sa.Integer(), nullable=True))
    op.add_column("holdings_13f", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_unique_constraint("uq_holdings_fingerprint", "holdings_13f", ["parse_run_id", "holding_row_fingerprint"])
    op.create_index("idx_holdings_parse_run", "holdings_13f", ["parse_run_id"])
    op.create_index("idx_holdings_manager_qend", "holdings_13f", ["manager_id", "quarter_end_date"])
    op.create_index("idx_holdings_manager_quarter", "holdings_13f", ["manager_id", "report_quarter"])
    op.create_index("idx_holdings_cusip", "holdings_13f", ["cusip"])
    op.create_index("idx_holdings_stock_id", "holdings_13f", ["stock_id"])
    op.create_index("idx_holdings_put_call", "holdings_13f", ["put_call"])
    op.create_index("idx_holdings_attribution", "holdings_13f", ["holding_attribution_status"])

    op.add_column("cusip_ticker_map", sa.Column("stock_id", sa.BigInteger(), sa.ForeignKey("stocks.id"), nullable=True))
    op.add_column("cusip_ticker_map", sa.Column("candidate_rank", sa.Integer(), nullable=True))
    op.add_column("cusip_ticker_map", sa.Column("effective_from_quarter", sa.String(10), nullable=True))
    op.add_column("cusip_ticker_map", sa.Column("effective_to_quarter", sa.String(10), nullable=True))
    op.add_column("cusip_ticker_map", sa.Column("evidence_url", sa.Text(), nullable=True))
    op.add_column("cusip_ticker_map", sa.Column("reviewed_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("cusip_ticker_map", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cusip_ticker_map", sa.Column("mapping_status", sa.String(30), nullable=False, server_default="needs_review"))
    op.add_column("cusip_ticker_map", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_unique_constraint(
        "uq_cusip_mapping",
        "cusip_ticker_map",
        ["cusip", "source", "ticker", "exchange", "effective_from_quarter"],
    )
    op.create_index(
        "idx_cusip_map_temporal",
        "cusip_ticker_map",
        ["cusip", "effective_from_quarter", "effective_to_quarter"],
        postgresql_where=sa.text("mapping_status IN ('confirmed', 'superseded')"),
    )


def downgrade() -> None:
    op.drop_index("idx_cusip_map_temporal", table_name="cusip_ticker_map")
    op.drop_constraint("uq_cusip_mapping", "cusip_ticker_map", type_="unique")
    op.drop_column("cusip_ticker_map", "created_at")
    op.drop_column("cusip_ticker_map", "mapping_status")
    op.drop_column("cusip_ticker_map", "reviewed_at")
    op.drop_column("cusip_ticker_map", "reviewed_by")
    op.drop_column("cusip_ticker_map", "evidence_url")
    op.drop_column("cusip_ticker_map", "effective_to_quarter")
    op.drop_column("cusip_ticker_map", "effective_from_quarter")
    op.drop_column("cusip_ticker_map", "candidate_rank")
    op.drop_column("cusip_ticker_map", "stock_id")

    op.drop_index("idx_holdings_attribution", table_name="holdings_13f")
    op.drop_index("idx_holdings_put_call", table_name="holdings_13f")
    op.drop_index("idx_holdings_stock_id", table_name="holdings_13f")
    op.drop_index("idx_holdings_cusip", table_name="holdings_13f")
    op.drop_index("idx_holdings_manager_quarter", table_name="holdings_13f")
    op.drop_index("idx_holdings_manager_qend", table_name="holdings_13f")
    op.drop_index("idx_holdings_parse_run", table_name="holdings_13f")
    op.drop_constraint("uq_holdings_fingerprint", "holdings_13f", type_="unique")
    op.drop_column("holdings_13f", "updated_at")
    op.drop_column("holdings_13f", "source_row_index")
    op.drop_column("holdings_13f", "fingerprint_version")
    op.drop_column("holdings_13f", "holding_row_fingerprint")
    op.drop_column("holdings_13f", "portfolio_weight_pct")
    op.drop_column("holdings_13f", "cusip_mapping_status")
    op.drop_column("holdings_13f", "holding_attribution_status")
    op.drop_column("holdings_13f", "other_managers_raw")
    op.drop_column("holdings_13f", "ssh_prnamt_type")
    op.drop_column("holdings_13f", "ssh_prnamt")
    op.drop_column("holdings_13f", "value_usd")
    op.drop_column("holdings_13f", "value_parse_rule")
    op.drop_column("holdings_13f", "value_unit_raw")
    op.drop_column("holdings_13f", "value_raw")
    op.drop_column("holdings_13f", "name_of_issuer")
    op.drop_column("holdings_13f", "quarter_end_date")
    op.drop_column("holdings_13f", "report_quarter")
    op.drop_column("holdings_13f", "accession_number")
    op.drop_column("holdings_13f", "manager_id")
    op.drop_column("holdings_13f", "parse_run_id")

    op.drop_index("uq_parse_runs_current_accession", table_name="parse_runs")
    op.drop_index("idx_parse_runs_accession", table_name="parse_runs")
    op.drop_table("parse_runs")

    op.drop_index("idx_filings_parser_version", table_name="filings_13f")
    op.drop_index("idx_filings_active", table_name="filings_13f")
    op.drop_index("idx_filings_manager_quarter", table_name="filings_13f")
    op.drop_index("idx_filings_manager_qend", table_name="filings_13f")
    op.drop_index("uq_active_filing_per_manager_period", table_name="filings_13f")
    op.drop_index("uq_filings_13f_accession_number", table_name="filings_13f")
    op.drop_column("filings_13f", "updated_at")
    op.drop_column("filings_13f", "amendment_sort_warning")
    op.drop_column("filings_13f", "amendment_status")
    op.drop_column("filings_13f", "common_holdings_count")
    op.drop_column("filings_13f", "holdings_count")
    op.drop_column("filings_13f", "total_13f_common_value_usd")
    op.drop_column("filings_13f", "total_13f_reported_value_usd")
    op.drop_column("filings_13f", "xml_schema_version")
    op.drop_column("filings_13f", "form_spec_version")
    op.drop_column("filings_13f", "parser_version")
    op.drop_column("filings_13f", "parse_error")
    op.drop_column("filings_13f", "parse_warning")
    op.drop_column("filings_13f", "parse_status")
    op.drop_column("filings_13f", "raw_infotable_url")
    op.drop_column("filings_13f", "raw_filing_url")
    op.drop_column("filings_13f", "is_active_for_manager_period")
    op.drop_column("filings_13f", "amendment_type_raw")
    op.drop_column("filings_13f", "amendment_type")
    op.drop_column("filings_13f", "amends_accession_number")
    op.drop_column("filings_13f", "is_amendment")
    op.drop_column("filings_13f", "official_filing_deadline")
    op.drop_column("filings_13f", "quarter_end_date")
    op.drop_column("filings_13f", "report_quarter")
    op.drop_column("filings_13f", "accepted_at")
    op.drop_column("filings_13f", "filing_date")
    op.drop_column("filings_13f", "confidential_treatment_status")
    op.drop_column("filings_13f", "other_managers_reporting")
    op.drop_column("filings_13f", "other_managers_included")
    op.drop_column("filings_13f", "coverage_type")
    op.drop_column("filings_13f", "coverage_completeness")
    op.drop_column("filings_13f", "report_type")
    op.drop_column("filings_13f", "cik")
    op.drop_column("filings_13f", "accession_number")
