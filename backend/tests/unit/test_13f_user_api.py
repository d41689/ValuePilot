from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    OwnershipChange13F,
    ParseRun13F,
)
from app.models.stocks import Stock


_CIK_COUNTER = count(9200000000)


def _clear_13f(db_session) -> None:
    db_session.query(OwnershipChange13F).delete()
    db_session.query(Holding13F).delete()
    db_session.query(ParseRun13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(InstitutionManagerCikReviewEvent).delete()
    db_session.query(InstitutionManager).delete()
    db_session.flush()


def _manager(
    db_session,
    name: str = "Safe API Manager",
    *,
    manager_type: str = "fundamental_long",
    is_featured: bool = True,
) -> InstitutionManager:
    cik = str(next(_CIK_COUNTER))
    manager = InstitutionManager(
        canonical_name=name,
        legal_name=name,
        edgar_legal_name=name,
        display_name=name,
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type=manager_type,
        is_featured=is_featured,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session, ticker: str = "SAFE") -> Stock:
    stock = Stock(ticker=ticker, exchange="NYSE", company_name=f"{ticker} Corp", is_active=True)
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(
    db_session,
    manager: InstitutionManager,
    accession: str,
    *,
    form_type: str = "13F-HR",
    report_type: str = "holdings_report",
    coverage_completeness: str = "complete",
    coverage_type: str = "normal",
    has_confidential_treatment: bool = False,
    active: bool = True,
    report_quarter: str = "2026-Q1",
    quarter_end_date: date = date(2026, 3, 31),
) -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=quarter_end_date,
        filed_at=date(2026, 5, 14),
        filing_date=date(2026, 5, 14),
        accepted_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        form_type=form_type,
        report_type=report_type,
        coverage_completeness=coverage_completeness,
        coverage_type=coverage_type,
        other_managers_reporting=[{"name": "Reporting Manager", "file_number": "028-00001"}] if form_type == "13F-NT" else None,
        quarter_end_date=quarter_end_date,
        report_quarter=report_quarter,
        official_filing_deadline=date(2026, 5, 15),
        parse_status="succeeded",
        is_active_for_manager_period=active,
        is_latest_for_period=active,
        has_confidential_treatment=has_confidential_treatment,
        confidential_treatment_status="applied" if has_confidential_treatment else "none",
        amendment_status="no_amendments_seen",
        total_13f_common_value_usd=1_000_000 if coverage_completeness == "complete" else None,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _parse_run(db_session, filing: Filing13F, *, current: bool = True) -> ParseRun13F:
    parse_run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="test",
        fingerprint_version="v1",
        status="succeeded",
        holdings_count=0,
        is_current=current,
    )
    db_session.add(parse_run)
    db_session.flush()
    return parse_run


def _holding(
    db_session,
    filing: Filing13F,
    parse_run: ParseRun13F,
    *,
    index: int,
    put_call: str | None = None,
    stock: Stock | None = None,
    attribution_status: str = "direct",
    portfolio_weight_pct: float | None = None,
) -> Holding13F:
    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=parse_run.id,
        manager_id=filing.manager_id,
        accession_number=filing.accession_number,
        report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date,
        row_fingerprint=f"{filing.accession_number}-{index}",
        holding_row_fingerprint=f"{filing.accession_number}-{index}",
        cusip=f"{index:09d}",
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
        holding_attribution_status=attribution_status,
        voting_sole=100,
        voting_shared=0,
        voting_none=0,
        stock_id=stock.id if stock else None,
        cusip_mapping_status="linked" if stock else "unresolved",
        portfolio_weight_pct=None if put_call else (10.0 if portfolio_weight_pct is None else portfolio_weight_pct),
        source_row_index=index,
    )
    db_session.add(holding)
    db_session.flush()
    return holding


def _ownership_change(
    db_session,
    manager: InstitutionManager,
    stock: Stock,
    *,
    report_quarter: str = "2026-Q1",
    quarter_end_date: date = date(2026, 3, 31),
    change_status: str = "increased",
    confidence_level: str = "high_confidence",
    primary: bool = True,
    caveat_codes: list[str] | None = None,
    unavailable_reason: str | None = None,
) -> OwnershipChange13F:
    change = OwnershipChange13F(
        manager_id=manager.id,
        stock_id=stock.id,
        report_quarter=report_quarter,
        quarter_end_date=quarter_end_date,
        previous_report_quarter="2025-Q4",
        previous_quarter_end_date=date(2025, 12, 31),
        security_key=f"stock:{stock.id}",
        current_cusip="000000001",
        previous_cusip="000000001",
        ssh_prnamt_type="SH",
        position_type="common",
        change_status=change_status,
        confidence_level=confidence_level,
        is_primary_signal_eligible=primary,
        caveat_codes=caveat_codes or [],
        unavailable_reason=unavailable_reason,
        current_value_usd=200000,
        previous_value_usd=100000,
        current_shares=200,
        previous_shares=100,
        share_delta=100,
    )
    db_session.add(change)
    db_session.flush()
    return change


def test_holdings_changes_returns_200_unavailable_when_no_computed_rows(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings/changes")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"]["code"] == "NO_COMPUTED_CHANGES"
    assert payload["items"] is None


def test_holdings_changes_returns_precomputed_change_rows(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    increased = _stock(db_session, "ADD")
    no_prior = _stock(db_session, "NT")
    _ownership_change(db_session, manager, increased)
    _ownership_change(
        db_session,
        manager,
        no_prior,
        change_status="no_prior_data",
        confidence_level="unavailable",
        primary=False,
        caveat_codes=["prior_quarter_13f_nt"],
        unavailable_reason="prior_quarter_13f_nt",
    )
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings/changes?quarter=2026-Q1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available_with_caveat"
    assert payload["quarter"] == "2026-Q1"
    assert payload["reason"] is None
    assert len(payload["items"]) == 2
    by_ticker = {item["stock"]["ticker"]: item for item in payload["items"]}
    assert by_ticker["ADD"]["change_status"] == "increased"
    assert by_ticker["ADD"]["confidence_level"] == "high_confidence"
    assert by_ticker["ADD"]["is_primary_signal_eligible"] is True
    assert by_ticker["ADD"]["current_value_usd"] == 200000
    assert by_ticker["ADD"]["share_delta"] == 100
    assert by_ticker["NT"]["change_status"] == "no_prior_data"
    assert by_ticker["NT"]["confidence_level"] == "unavailable"
    assert by_ticker["NT"]["is_primary_signal_eligible"] is False
    assert by_ticker["NT"]["caveat_codes"] == ["prior_quarter_13f_nt"]
    assert by_ticker["NT"]["unavailable_reason"] == "prior_quarter_13f_nt"


def test_managers_endpoint_lists_only_active_cik_managers(client, db_session):
    _clear_13f(db_session)
    active = _manager(db_session, "Active Manager")
    inactive = _manager(db_session, "Inactive Manager")
    inactive.status = "inactive"
    no_cik = _manager(db_session, "No CIK Manager")
    no_cik.cik = None
    db_session.commit()

    response = client.get("/api/v1/13f/managers")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == [active.id]


def test_manager_quarters_exposes_nt_as_reported_elsewhere(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    _filing(db_session, manager, "0000000000-26-000010")
    _filing(
        db_session,
        manager,
        "0000000000-26-000011",
        form_type="13F-NT",
        report_type="notice_report",
        coverage_completeness="unknown",
        coverage_type="notice_reported_elsewhere",
        report_quarter="2025-Q4",
        quarter_end_date=date(2025, 12, 31),
    )
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/quarters")

    assert response.status_code == 200
    payload = response.json()
    statuses = {item["filing"]["form_type"]: item["status"] for item in payload["items"]}
    assert statuses["13F-HR"] == "available"
    assert statuses["13F-NT"] == "reported_elsewhere"


def test_nt_manager_holdings_response_uses_caveat_not_empty_positions(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    _filing(
        db_session,
        manager,
        "0000000001-26-000001",
        form_type="13F-NT",
        report_type="notice_report",
        coverage_completeness="unknown",
        coverage_type="notice_reported_elsewhere",
    )
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings?quarter=2026-Q1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"]["code"] == "NOTICE_REPORTED_ELSEWHERE"
    assert "reported by other manager" in payload["caveats"][0]["message"]
    assert payload["common_holdings"] is None
    assert payload["options"] is None


def test_partial_and_confidential_filings_include_caveat_metadata(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    filing = _filing(
        db_session,
        manager,
        "0000000002-26-000001",
        report_type="combination_report",
        coverage_completeness="partial",
        coverage_type="combination_partial",
        has_confidential_treatment=True,
    )
    parse_run = _parse_run(db_session, filing)
    _holding(db_session, filing, parse_run, index=1, stock=_stock(db_session))
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings?quarter=2026-Q1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available_with_caveat"
    codes = {item["code"] for item in payload["caveats"]}
    assert {"COMBINATION_REPORT", "CONFIDENTIAL_TREATMENT"}.issubset(codes)
    assert payload["common_holdings"][0]["portfolio_weight_pct"]["value"] is None
    assert payload["common_holdings"][0]["portfolio_weight_pct"]["unavailable_reason"] == "PARTIAL_COVERAGE"


def test_options_are_separated_and_common_weight_is_null(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0000000003-26-000001")
    parse_run = _parse_run(db_session, filing)
    _holding(db_session, filing, parse_run, index=1, stock=_stock(db_session, "COMN"))
    _holding(db_session, filing, parse_run, index=2, put_call="Call", stock=_stock(db_session, "OPTN"))
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings?quarter=2026-Q1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available"
    assert len(payload["common_holdings"]) == 1
    assert len(payload["options"]) == 1
    assert payload["common_holdings"][0]["put_call"] is None
    assert payload["common_holdings"][0]["portfolio_weight_pct"]["value"] == 10.0
    assert payload["options"][0]["put_call"] == "Call"
    assert payload["options"][0]["portfolio_weight_pct"]["value"] is None
    assert payload["options"][0]["portfolio_weight_pct"]["unavailable_reason"] == "OPTIONS_EXCLUDED_FROM_COMMON_WEIGHT"


def test_holdings_endpoint_uses_active_current_hr_query_contract(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    active = _filing(db_session, manager, "0000000004-26-000001")
    active_run = _parse_run(db_session, active, current=True)
    _holding(db_session, active, active_run, index=1, stock=_stock(db_session, "CURR"))

    inactive = _filing(db_session, manager, "0000000005-26-000001", active=False)
    inactive_run = _parse_run(db_session, inactive, current=True)
    _holding(db_session, inactive, inactive_run, index=2, stock=_stock(db_session, "OLD1"))

    stale_run = _parse_run(db_session, active, current=False)
    _holding(db_session, active, stale_run, index=3, stock=_stock(db_session, "OLD2"))
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings?quarter=2026-Q1")

    assert response.status_code == 200
    payload = response.json()
    names = [item["issuer_name"] for item in payload["common_holdings"]]
    assert names == ["Issuer 1"]


def test_stock_holders_aggregation_counts_only_direct_common_holders(client, db_session):
    _clear_13f(db_session)
    stock = _stock(db_session, "AGG")
    featured = _manager(db_session, "Featured Fundamental", manager_type="fundamental_long", is_featured=True)
    activist = _manager(db_session, "Activist Holder", manager_type="activist", is_featured=False)
    quant = _manager(db_session, "Quant Holder", manager_type="quant", is_featured=False)
    shared = _manager(db_session, "Shared Attribution", manager_type="fundamental_long", is_featured=True)
    unresolved = _manager(db_session, "Unresolved Attribution", manager_type="fundamental_long", is_featured=True)

    for index, (manager, attribution, weight) in enumerate(
        [
            (featured, "direct", 12.5),
            (activist, "direct", 20.0),
            (quant, "direct", 5.0),
            (shared, "shared", 30.0),
            (unresolved, "unresolved", 40.0),
        ],
        start=1,
    ):
        filing = _filing(db_session, manager, f"0000000100-26-{index:06d}")
        parse_run = _parse_run(db_session, filing)
        _holding(
            db_session,
            filing,
            parse_run,
            index=index,
            stock=stock,
            attribution_status=attribution,
            portfolio_weight_pct=weight,
        )
        if manager == featured:
            _holding(db_session, filing, parse_run, index=99, stock=stock, put_call="PUT")
        if manager == shared:
            _holding(
                db_session,
                filing,
                parse_run,
                index=100,
                stock=stock,
                attribution_status="shared",
                portfolio_weight_pct=31.0,
            )
    _ownership_change(db_session, featured, stock, change_status="new_position")
    _ownership_change(db_session, activist, stock, change_status="increased")
    _ownership_change(db_session, quant, stock, change_status="cusip_changed")
    _ownership_change(db_session, shared, stock, change_status="reduced", primary=False)
    db_session.commit()

    response = client.get(f"/api/v1/13f/stocks/{stock.id}/holders")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available_with_caveat"
    assert payload["stock_id"] == stock.id
    assert payload["as_of_quarter"] == "2026-Q1"
    assert payload["direct_holder_count"] == 2
    assert payload["value_manager_direct_count"] == 2
    assert payload["featured_holder_count"] == 1
    assert payload["attribution_caveat_count"] == 2
    assert [item["manager"]["id"] for item in payload["top_holders"]] == [activist.id, featured.id]
    assert payload["top_holders"][0]["portfolio_weight_pct"] == 20.0
    assert {item["change_status"] for item in payload["recent_changes"]} == {"new_position", "increased"}
    assert {item["manager"]["id"] for item in payload["recent_changes"]} == {featured.id, activist.id}


def test_stock_holders_aggregation_surfaces_data_caveats(client, db_session):
    _clear_13f(db_session)
    stock = _stock(db_session, "CAVE")
    confidential = _manager(db_session, "Confidential Manager")
    combination = _manager(db_session, "Combination Manager")
    confidential_filing = _filing(
        db_session,
        confidential,
        "0000000200-26-000001",
        has_confidential_treatment=True,
    )
    combination_filing = _filing(
        db_session,
        combination,
        "0000000200-26-000002",
        report_type="combination_report",
        coverage_completeness="partial",
        coverage_type="combination_partial",
    )
    for index, (filing, manager) in enumerate([(confidential_filing, confidential), (combination_filing, combination)], start=1):
        parse_run = _parse_run(db_session, filing)
        _holding(db_session, filing, parse_run, index=index, stock=stock, portfolio_weight_pct=10.0 + index)
        _ownership_change(db_session, manager, stock, change_status="increased")
    db_session.commit()

    response = client.get(f"/api/v1/13f/stocks/{stock.id}/holders")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available_with_caveat"
    codes = {item["code"] for item in payload["data_caveats"]}
    assert {"CONFIDENTIAL_TREATMENT", "COMBINATION_REPORT", "FILING_WINDOW_OPEN"}.issubset(codes)


def test_stock_holders_aggregation_unavailable_when_no_holders(client, db_session):
    _clear_13f(db_session)
    stock = _stock(db_session, "NONE")
    db_session.commit()

    response = client.get(f"/api/v1/13f/stocks/{stock.id}/holders")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"]["code"] == "NO_ACTIVE_HOLDERS"
    assert payload["direct_holder_count"] == 0
    assert payload["top_holders"] == []
    assert payload["recent_changes"] == []
    assert payload["data_caveats"] == []


def test_stock_holders_rejects_invalid_quarter(client, db_session):
    _clear_13f(db_session)
    stock = _stock(db_session, "BADQ")
    db_session.commit()

    response = client.get(f"/api/v1/13f/stocks/{stock.id}/holders?quarter=2026-Q5")

    assert response.status_code == 422
