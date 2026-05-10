from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from itertools import count

from app.models.institutions import (
    CusipTickerMap,
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    JobRun,
    JobWorkerHeartbeat,
    ParseRun13F,
    QualityReport13F,
    RawSourceDocument,
)
from app.models.stocks import Stock


_CIK_COUNTER = count(9300000000)
_ACCESSION_COUNTER = count(1)


def _clear_13f(db_session) -> None:
    db_session.query(Holding13F).delete()
    db_session.query(ParseRun13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(RawSourceDocument).delete()
    db_session.query(JobWorkerHeartbeat).delete()
    db_session.query(JobRun).delete()
    db_session.query(QualityReport13F).delete()
    db_session.query(InstitutionManagerCikReviewEvent).delete()
    db_session.query(InstitutionManager).delete()
    db_session.query(CusipTickerMap).delete()
    db_session.flush()


def _admin(user_factory):
    return user_factory(email="13f-read-model-admin@example.com", role="admin")


def _manager(db_session, name: str = "Admin Read Manager") -> InstitutionManager:
    cik = str(next(_CIK_COUNTER))
    manager = InstitutionManager(
        canonical_name=name,
        legal_name=name,
        edgar_legal_name=name,
        display_name=name,
        cik=cik,
        status="active",
        match_status="confirmed",
        is_featured=True,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _accession() -> str:
    return f"000{next(_ACCESSION_COUNTER):07d}-26-000001"


def _filing(
    db_session,
    manager: InstitutionManager,
    *,
    accession: str | None = None,
    form_type: str = "13F-HR",
    report_type: str = "holdings_report",
    coverage_completeness: str = "complete",
    coverage_type: str = "normal",
    parse_status: str = "succeeded",
    amendment_status: str = "no_amendments_seen",
    amendment_type: str | None = None,
    report_quarter: str = "2026-Q1",
    quarter_end_date: date = date(2026, 3, 31),
    active: bool = True,
    confidential: bool = False,
    accepted_at: datetime | None = None,
) -> Filing13F:
    accession = accession or _accession()
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=quarter_end_date,
        filed_at=quarter_end_date + timedelta(days=45),
        filing_date=quarter_end_date + timedelta(days=45),
        accepted_at=accepted_at or datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        form_type=form_type,
        report_type=report_type,
        coverage_completeness=coverage_completeness,
        coverage_type=coverage_type,
        quarter_end_date=quarter_end_date,
        report_quarter=report_quarter,
        official_filing_deadline=date(2026, 5, 15),
        parse_status=parse_status,
        is_active_for_manager_period=active,
        is_latest_for_period=active,
        has_confidential_treatment=confidential,
        confidential_treatment_status="applied" if confidential else "none",
        amendment_status=amendment_status,
        amendment_type=amendment_type,
        total_13f_common_value_usd=1_000_000 if coverage_completeness == "complete" else None,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _parse_run(
    db_session,
    filing: Filing13F,
    *,
    parser_version: str,
    status: str,
    current: bool,
    holdings_count: int = 0,
) -> ParseRun13F:
    run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version=parser_version,
        fingerprint_version="v1",
        started_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc),
        status=status,
        holdings_count=holdings_count,
        error=None if status == "succeeded" else "parse failed",
        is_current=current,
    )
    db_session.add(run)
    db_session.flush()
    return run


def _stock(db_session, ticker: str = "ADM") -> Stock:
    stock = Stock(ticker=ticker, exchange="NYSE", company_name=f"{ticker} Corp", is_active=True)
    db_session.add(stock)
    db_session.flush()
    return stock


def _holding(
    db_session,
    filing: Filing13F,
    parse_run: ParseRun13F,
    *,
    index: int,
    cusip: str | None = None,
    stock: Stock | None = None,
    put_call: str | None = None,
    mapping_status: str | None = None,
) -> Holding13F:
    status = mapping_status or ("linked" if stock else "unresolved")
    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=parse_run.id,
        manager_id=filing.manager_id,
        accession_number=filing.accession_number,
        report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date,
        row_fingerprint=f"{filing.accession_number}-{index}",
        holding_row_fingerprint=f"{filing.accession_number}-{index}",
        cusip=cusip or f"000000{index:03d}",
        issuer_name=f"Issuer {index}",
        name_of_issuer=f"Issuer {index}",
        title_of_class="COM",
        value_thousands=100,
        value_raw="100000",
        value_unit_raw="dollars",
        value_parse_rule="schema_dollars",
        value_usd=100000,
        shares=100,
        ssh_prnamt=100,
        share_type="SH",
        ssh_prnamt_type="SH",
        put_call=put_call,
        investment_discretion="SOLE",
        holding_attribution_status="direct",
        voting_sole=100,
        voting_shared=0,
        voting_none=0,
        stock_id=stock.id if stock else None,
        cusip_mapping_status=status,
        source_row_index=index,
    )
    db_session.add(holding)
    db_session.flush()
    return holding


def test_admin_filings_list_and_detail_expose_caveat_fields(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    filing = _filing(
        db_session,
        manager,
        report_type="combination_report",
        coverage_completeness="partial",
        coverage_type="combination_partial",
        confidential=True,
        amendment_status="amendments_pending",
        amendment_type="RESTATEMENT",
    )
    db_session.commit()

    list_response = client.get(
        "/api/v1/admin/13f/filings?page=1&page_size=50",
        headers=auth_headers(admin),
    )

    assert list_response.status_code == 200
    listing = list_response.json()
    assert listing["page"] == 1
    assert listing["page_size"] == 50
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["accession_number"] == filing.accession_number
    assert item["report_type"] == "combination_report"
    assert item["coverage_completeness"] == "partial"
    assert item["coverage_type"] == "combination_partial"
    assert item["has_confidential_treatment"] is True
    assert item["confidential_treatment_status"] == "applied"
    assert item["amendment_status"] == "amendments_pending"
    assert item["amendment_type"] == "RESTATEMENT"
    assert item["parse_status"] == "succeeded"
    assert item["official_filing_deadline"] == "2026-05-15"

    detail_response = client.get(
        f"/api/v1/admin/13f/filings/{filing.accession_number}",
        headers=auth_headers(admin),
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["accession_number"] == filing.accession_number
    assert detail["report_quarter"] == "2026-Q1"
    assert detail["is_active_for_manager_period"] is True
    assert detail["manager"]["id"] == manager.id


def test_parse_runs_endpoint_returns_audit_history(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    _parse_run(db_session, filing, parser_version="13f-parser/old", status="failed", current=False)
    current = _parse_run(db_session, filing, parser_version="13f-parser/new", status="succeeded", current=True, holdings_count=3)
    db_session.commit()

    response = client.get(
        f"/api/v1/admin/13f/filings/{filing.accession_number}/parse-runs",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accession_number"] == filing.accession_number
    assert [item["parser_version"] for item in payload["items"]] == [
        "13f-parser/new",
        "13f-parser/old",
    ]
    assert payload["items"][0]["id"] == current.id
    assert payload["items"][0]["is_current"] is True
    assert payload["items"][0]["holdings_count"] == 3


def test_jobs_list_filters_status_type_started_sync_date_and_quarter(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    matching = JobRun(
        job_type="fetch_daily_index",
        status="failed",
        sync_date=date(2026, 5, 15),
        quarter="2026-Q1",
        started_at=datetime(2026, 5, 15, 20, 0, tzinfo=timezone.utc),
        lock_key="fetch_daily_index:2026-05-15",
        dedupe_key="fetch_daily_index:2026-05-15",
    )
    other = JobRun(
        job_type="ingest_accession",
        status="failed",
        sync_date=date(2026, 5, 15),
        quarter="2026-Q1",
        started_at=datetime(2026, 5, 15, 20, 0, tzinfo=timezone.utc),
        lock_key="ingest_accession:0001",
        dedupe_key="0001",
    )
    db_session.add_all([matching, other])
    db_session.commit()

    response = client.get(
        "/api/v1/admin/13f/jobs"
        "?status=failed&job_type=fetch_daily_index&sync_date=2026-05-15"
        "&quarter=2026-Q1&started_from=2026-05-15T00:00:00%2B00:00"
        "&started_to=2026-05-16T00:00:00%2B00:00&page=1&page_size=50",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == matching.id
    assert payload["items"][0]["sync_date"] == "2026-05-15"
    assert payload["items"][0]["quarter"] == "2026-Q1"


def test_pending_amendments_endpoint_groups_by_type_and_status(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    restatement = _filing(
        db_session,
        manager,
        form_type="13F-HR/A",
        amendment_status="amendments_pending",
        amendment_type="RESTATEMENT",
    )
    _filing(
        db_session,
        manager,
        form_type="13F-HR/A",
        amendment_status="amendments_pending",
        amendment_type="OTHER",
        active=False,
    )
    _filing(db_session, manager, form_type="13F-HR/A", amendment_status="amendments_applied", active=False)
    db_session.commit()

    response = client.get(
        "/api/v1/admin/13f/amendments/pending?page=1&page_size=50",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["groups"]["RESTATEMENT"]["amendments_pending"] == 1
    assert payload["groups"]["OTHER"]["amendments_pending"] == 1
    accessions = {item["accession_number"] for item in payload["items"]}
    assert restatement.accession_number in accessions
    assert len(accessions) == 2


def test_holdings_coverage_summary_exposes_linked_unresolved_and_options(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    parse_run = _parse_run(db_session, filing, parser_version="13f-parser", status="succeeded", current=True)
    _holding(db_session, filing, parse_run, index=1, stock=_stock(db_session))
    _holding(db_session, filing, parse_run, index=2)
    _holding(db_session, filing, parse_run, index=3, put_call="CALL", mapping_status="linked")
    db_session.commit()

    response = client.get(
        "/api/v1/admin/13f/holdings/coverage?report_quarter=2026-Q1",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_quarter"] == "2026-Q1"
    assert payload["total_holdings_count"] == 3
    assert payload["common_holdings_count"] == 2
    assert payload["linked_common_holdings_count"] == 1
    assert payload["unresolved_common_holdings_count"] == 1
    assert payload["options_count"] == 1
    assert payload["linked_common_holding_ratio"] == 0.5


def test_unresolved_cusip_mappings_endpoint_groups_unresolved_holdings(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    parse_run = _parse_run(db_session, filing, parser_version="13f-parser", status="succeeded", current=True)
    _holding(db_session, filing, parse_run, index=7, cusip="000000007")
    _holding(db_session, filing, parse_run, index=70, cusip="000000007")
    _holding(db_session, filing, parse_run, index=8, mapping_status="needs_review")
    db_session.commit()

    response = client.get(
        "/api/v1/admin/13f/cusip-mappings/unresolved?page=1&page_size=50",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    by_cusip = {item["cusip"]: item for item in payload["items"]}
    assert by_cusip["000000007"]["holding_count"] == 2
    assert by_cusip["000000007"]["cusip_mapping_status"] == "unresolved"
    assert by_cusip["000000008"]["cusip_mapping_status"] == "needs_review"
