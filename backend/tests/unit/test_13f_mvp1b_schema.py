from __future__ import annotations

from itertools import count
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models.institutions import (
    CUSIP_MAPPING_STATUSES,
    FILING_PARSE_STATUSES,
    HOLDING_CUSIP_MAPPING_STATUSES,
    PARSE_RUN_STATUSES,
    CusipTickerMap,
    Filing13F,
    Holding13F,
    InstitutionManager,
    ParseRun13F,
)


_CIK_COUNTER = count(7000000000)


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_COUNTER)).zfill(10)
    manager = InstitutionManager(
        canonical_name="MVP 1B Manager",
        legal_name="MVP 1B Manager",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _filing(db_session, manager: InstitutionManager, accession: str = "0001067983-26-000001") -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        cik=manager.cik,
        accession_no=accession,
        accession_number=accession,
        form_type="13F-HR",
        period_of_report=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        filing_date=date(2026, 5, 15),
        accepted_at=datetime(2026, 5, 15, 16, 0, tzinfo=timezone.utc),
        report_quarter="2026-Q1",
        quarter_end_date=date(2026, 3, 31),
        official_filing_deadline=date(2026, 5, 15),
        is_active_for_manager_period=True,
        parse_status="pending",
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def test_mvp1b_schema_columns_and_indexes_exist(db_session):
    inspector = inspect(db_session.bind)

    filing_columns = {column["name"] for column in inspector.get_columns("filings_13f")}
    assert {
        "cik",
        "accession_number",
        "report_type",
        "coverage_completeness",
        "coverage_type",
        "other_managers_included",
        "other_managers_reporting",
        "confidential_treatment_status",
        "filing_date",
        "accepted_at",
        "report_quarter",
        "quarter_end_date",
        "official_filing_deadline",
        "is_amendment",
        "amends_accession_number",
        "amendment_type",
        "amendment_type_raw",
        "is_active_for_manager_period",
        "raw_filing_url",
        "raw_infotable_url",
        "parse_status",
        "parse_warning",
        "parse_error",
        "parser_version",
        "form_spec_version",
        "xml_schema_version",
        "total_13f_reported_value_usd",
        "total_13f_common_value_usd",
        "holdings_count",
        "common_holdings_count",
        "amendment_status",
        "amendment_sort_warning",
        "updated_at",
    } <= filing_columns

    parse_run_columns = {column["name"] for column in inspector.get_columns("parse_runs")}
    assert {
        "id",
        "accession_number",
        "job_run_id",
        "parser_version",
        "fingerprint_version",
        "started_at",
        "finished_at",
        "status",
        "holdings_count",
        "error",
        "is_current",
        "created_at",
    } <= parse_run_columns

    holding_columns = {column["name"] for column in inspector.get_columns("holdings_13f")}
    assert {
        "parse_run_id",
        "manager_id",
        "accession_number",
        "report_quarter",
        "quarter_end_date",
        "name_of_issuer",
        "value_raw",
        "value_unit_raw",
        "value_parse_rule",
        "value_usd",
        "ssh_prnamt",
        "ssh_prnamt_type",
        "other_managers_raw",
        "holding_attribution_status",
        "cusip_mapping_status",
        "portfolio_weight_pct",
        "holding_row_fingerprint",
        "fingerprint_version",
        "source_row_index",
        "updated_at",
    } <= holding_columns

    cusip_columns = {column["name"] for column in inspector.get_columns("cusip_ticker_map")}
    assert {
        "stock_id",
        "candidate_rank",
        "effective_from_quarter",
        "effective_to_quarter",
        "evidence_url",
        "reviewed_by",
        "reviewed_at",
        "mapping_status",
        "created_at",
    } <= cusip_columns

    filing_indexes = {index["name"] for index in inspector.get_indexes("filings_13f")}
    assert "uq_active_filing_per_manager_period" in filing_indexes
    assert "idx_filings_manager_qend" in filing_indexes
    assert "idx_filings_manager_quarter" in filing_indexes
    assert "idx_filings_parser_version" in filing_indexes

    parse_run_indexes = {index["name"] for index in inspector.get_indexes("parse_runs")}
    assert "uq_parse_runs_current_accession" in parse_run_indexes
    assert "idx_parse_runs_accession" in parse_run_indexes

    holding_indexes = {index["name"] for index in inspector.get_indexes("holdings_13f")}
    assert "idx_holdings_parse_run" in holding_indexes
    assert "idx_holdings_manager_qend" in holding_indexes
    assert "idx_holdings_cusip" in holding_indexes
    assert "idx_holdings_attribution" in holding_indexes

    cusip_indexes = {index["name"] for index in inspector.get_indexes("cusip_ticker_map")}
    assert "idx_cusip_map_temporal" in cusip_indexes


@pytest.mark.parametrize("status", sorted(FILING_PARSE_STATUSES))
def test_filing_parse_status_accepts_prd_values(status):
    filing = Filing13F(
        manager_id=1,
        accession_no="0000000000-26-000001",
        accession_number="0000000000-26-000001",
        period_of_report=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        form_type="13F-HR",
        parse_status=status,
    )

    assert filing.parse_status == status


@pytest.mark.parametrize("status", sorted(PARSE_RUN_STATUSES))
def test_parse_run_status_accepts_independent_prd_values(status):
    run = ParseRun13F(accession_number="0000000000-26-000001", parser_version="test", status=status)

    assert run.status == status


@pytest.mark.parametrize("status", sorted(HOLDING_CUSIP_MAPPING_STATUSES))
def test_holding_cusip_mapping_status_accepts_prd_values(status):
    holding = Holding13F(
        filing_id=1,
        parse_run_id=1,
        manager_id=1,
        accession_number="0000000000-26-000001",
        row_fingerprint="legacy",
        holding_row_fingerprint="fingerprint",
        cusip="037833100",
        issuer_name="APPLE INC",
        name_of_issuer="APPLE INC",
        value_thousands=1,
        value_raw="1000",
        value_unit_raw="dollars",
        value_parse_rule="schema_dollars",
        value_usd=1000,
        source_row_index=0,
        cusip_mapping_status=status,
    )

    assert holding.cusip_mapping_status == status


@pytest.mark.parametrize("status", sorted(CUSIP_MAPPING_STATUSES))
def test_cusip_mapping_status_accepts_prd_values(status):
    mapping = CusipTickerMap(
        cusip="037833100",
        source="openfigi",
        ticker="AAPL",
        exchange="NASDAQ",
        effective_from_quarter="2026-Q1",
        mapping_status=status,
    )

    assert mapping.mapping_status == status


def test_only_one_active_filing_per_manager_quarter(db_session):
    manager = _manager(db_session)
    _filing(db_session, manager, "0001067983-26-000001")

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                Filing13F(
                    manager_id=manager.id,
                    cik=manager.cik,
                    accession_no="0001067983-26-000002",
                    accession_number="0001067983-26-000002",
                    form_type="13F-HR",
                    period_of_report=date(2026, 3, 31),
                    filed_at=date(2026, 5, 16),
                    quarter_end_date=date(2026, 3, 31),
                    is_active_for_manager_period=True,
                )
            )
            db_session.flush()


def test_only_one_current_parse_run_per_accession(db_session):
    accession = "0001067983-26-000001"
    db_session.add(
        ParseRun13F(
            accession_number=accession,
            parser_version="v1",
            status="succeeded",
            is_current=True,
        )
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                ParseRun13F(
                    accession_number=accession,
                    parser_version="v2",
                    status="succeeded",
                    is_current=True,
                )
            )
            db_session.flush()


def test_holding_fingerprint_unique_per_parse_run_only(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    run1 = ParseRun13F(accession_number=filing.accession_number, parser_version="v1", status="succeeded")
    run2 = ParseRun13F(accession_number=filing.accession_number, parser_version="v2", status="succeeded")
    db_session.add_all([run1, run2])
    db_session.flush()

    def holding(parse_run_id: int, source_row_index: int) -> Holding13F:
        return Holding13F(
            filing_id=filing.id,
            parse_run_id=parse_run_id,
            manager_id=manager.id,
            accession_number=filing.accession_number,
            report_quarter="2026-Q1",
            quarter_end_date=date(2026, 3, 31),
            row_fingerprint=f"legacy-{parse_run_id}-{source_row_index}",
            holding_row_fingerprint="same-raw-row",
            cusip="037833100",
            issuer_name="APPLE INC",
            name_of_issuer="APPLE INC",
            value_thousands=1,
            value_raw="1000",
            value_unit_raw="dollars",
            value_parse_rule="schema_dollars",
            value_usd=1000,
            source_row_index=source_row_index,
        )

    db_session.add_all([holding(run1.id, 0), holding(run2.id, 0)])
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(holding(run1.id, 1))
            db_session.flush()


def test_cusip_mapping_candidate_uniqueness(db_session):
    mapping_kwargs = {
        "cusip": "037833100",
        "source": "openfigi",
        "ticker": "AAPL",
        "exchange": "NASDAQ",
        "effective_from_quarter": "2026-Q1",
        "mapping_status": "needs_review",
    }
    db_session.add(CusipTickerMap(**mapping_kwargs))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(CusipTickerMap(**mapping_kwargs))
            db_session.flush()
