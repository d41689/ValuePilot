from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from itertools import count

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    OwnershipChange13F,
    ParseRun13F,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.models.stocks import Stock, StockPrice


_CIK_COUNTER = count(9200000000)


def _clear_13f(db_session) -> None:
    # Pre-MVP8-01: persisted Oracle's Lens rows FK-reference
    # InstitutionManager, so they must clear first.
    db_session.query(OraclesLensScoreComponent).delete()
    db_session.query(OraclesLensSignal).delete()
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
    manager_type: str = "long_term_fundamental",
    style_primary: str = "quality_compounder",
    capital_structure: str = "standard_lp",
    historical_turnover: str = "low",
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
        style_primary=style_primary,
        capital_structure=capital_structure,
        historical_turnover=historical_turnover,
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
        # Relative to today so the filing window stays open regardless of
        # when the test runs — the absolute date(2026, 5, 15) silently
        # expired on 2026-05-16 and FILING_WINDOW_OPEN caveat stopped
        # firing. Surfaced by PR #33 N4 D1 round-trip.
        official_filing_deadline=date.today() + timedelta(days=10),
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


def _ensure_active_hr_filing(db_session, manager, report_quarter, quarter_end_date):
    """Series-review P1: the changes API now withholds rows for a quarter with
    no active HR filing, so materialized-row fixtures must carry the filing
    that makes them current (production rows always do)."""
    existing = (
        db_session.query(Filing13F)
        .filter_by(manager_id=manager.id, report_quarter=report_quarter)
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .first()
    )
    if existing:
        return existing
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=f"CHG-{manager.id}-{report_quarter}",
        accession_number=f"CHG-{manager.id}-{report_quarter}",
        cik=manager.cik,
        form_type="13F-HR",
        period_of_report=quarter_end_date,
        filed_at=quarter_end_date,
        filing_date=quarter_end_date,
        report_quarter=report_quarter,
        quarter_end_date=quarter_end_date,
        is_active_for_manager_period=True,
        parse_status="succeeded",
        is_latest_for_period=False,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _ownership_change(
    db_session,
    manager: InstitutionManager,
    stock: Stock | None,
    *,
    report_quarter: str = "2026-Q1",
    quarter_end_date: date = date(2026, 3, 31),
    change_status: str = "increased",
    confidence_level: str = "high_confidence",
    primary: bool = True,
    caveat_codes: list[str] | None = None,
    unavailable_reason: str | None = None,
) -> OwnershipChange13F:
    _ensure_active_hr_filing(db_session, manager, report_quarter, quarter_end_date)
    change = OwnershipChange13F(
        manager_id=manager.id,
        stock_id=stock.id if stock else None,
        report_quarter=report_quarter,
        quarter_end_date=quarter_end_date,
        previous_report_quarter="2025-Q4",
        previous_quarter_end_date=date(2025, 12, 31),
        security_key=f"stock:{stock.id}" if stock else "cusip:000000001",
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
    assert payload["quarter_end_date"] == "2026-03-31"
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


def test_holdings_changes_clean_rows_return_available_and_latest_quarter(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    old_stock = _stock(db_session, "OLD")
    current_stock = _stock(db_session, "CUR")
    _ownership_change(
        db_session,
        manager,
        old_stock,
        report_quarter="2025-Q4",
        quarter_end_date=date(2025, 12, 31),
    )
    _ownership_change(db_session, manager, current_stock)
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings/changes")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available"
    assert payload["quarter"] == "2026-Q1"
    assert payload["quarter_end_date"] == "2026-03-31"
    assert [item["stock"]["ticker"] for item in payload["items"]] == ["CUR"]


def test_holdings_changes_computes_missing_portfolio_weights_from_filing_denominators(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session, "WGHT")
    _filing(db_session, manager, "0000000090-25-000001", report_quarter="2025-Q4", quarter_end_date=date(2025, 12, 31))
    _filing(db_session, manager, "0000000090-26-000001")
    change = _ownership_change(db_session, manager, stock, change_status="increased")
    change.current_portfolio_weight_pct = None
    change.previous_portfolio_weight_pct = None
    change.current_value_usd = 200000
    change.previous_value_usd = 100000
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings/changes?quarter=2026-Q1")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["current_portfolio_weight_pct"] == 20.0
    assert item["previous_portfolio_weight_pct"] == 10.0
    assert item["portfolio_weight_delta_pct"] == 10.0


def test_holdings_changes_rejects_invalid_quarter(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings/changes?quarter=2026-Q5")

    assert response.status_code == 422


def test_holdings_changes_handles_unresolved_stock_identity(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    _ownership_change(db_session, manager, None, change_status="unresolvable", confidence_level="unavailable", primary=False)
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings/changes?quarter=2026-Q1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available_with_caveat"
    assert payload["items"][0]["stock"] == {
        "id": None,
        "ticker": None,
        "exchange": None,
        "company_name": None,
    }
    assert payload["items"][0]["change_status"] == "unresolvable"


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


def test_managers_endpoint_exposes_value_dna_and_latest_filing_summary(client, db_session):
    _clear_13f(db_session)
    manager = _manager(
        db_session,
        "Warren Buffett - Berkshire Hathaway",
        manager_type="value_concentrated",
        style_primary="value_concentrated",
        capital_structure="permanent_capital",
        historical_turnover="low",
        is_featured=False,
    )
    # The curated rationale is keyed by the confirmed seed CIK, not by display
    # name, so a renamed label cannot attach another manager's profile.
    manager.cik = "0001067983"
    _filing(db_session, manager, "0001067983-26-000001")
    db_session.commit()

    response = client.get("/api/v1/13f/managers")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["style_primary"] == "value_concentrated"
    assert item["capital_structure"] == "permanent_capital"
    assert item["historical_turnover"] == "low"
    assert item["classification_rationale"].startswith("Top 10 positions")
    assert item["latest_filing"] == {
        "quarter": "2026-Q1",
        "quarter_end_date": "2026-03-31",
        "form_type": "13F-HR",
        "status": "available",
        "accepted_at": "2026-05-14T12:00:00+00:00",
    }


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


def test_manager_holdings_returns_position_view_with_computed_common_weights(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0000000006-26-000001")
    parse_run = _parse_run(db_session, filing)
    alphabet = _stock(db_session, "GOOG")
    other = _stock(db_session, "BRK")
    # Two raw rows map to one economic stock position. The consumer view must
    # sum them while retaining constituent count/CUSIPs; the raw audit rows stay
    # untouched in holdings_13f.
    first = _holding(db_session, filing, parse_run, index=1, stock=alphabet)
    second = _holding(db_session, filing, parse_run, index=2, stock=alphabet)
    third = _holding(db_session, filing, parse_run, index=3, stock=other)
    first.cusip = "02079K107"
    second.cusip = "02079K305"
    third.cusip = "084670702"
    first.portfolio_weight_pct = None
    second.portfolio_weight_pct = None
    third.portfolio_weight_pct = None
    filing.total_13f_common_value_usd = None
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings?quarter=2026-Q1")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["common_holdings"]) == 2
    assert db_session.query(Holding13F).filter(Holding13F.filing_id == filing.id).count() == 3
    by_ticker = {item["stock"]["ticker"]: item for item in payload["common_holdings"]}
    assert by_ticker["GOOG"]["constituent_row_count"] == 2
    assert by_ticker["GOOG"]["cusips"] == ["02079K107", "02079K305"]
    assert by_ticker["GOOG"]["value_usd"] == 200000
    assert by_ticker["GOOG"]["portfolio_weight_pct"]["value"] == 66.666667
    assert by_ticker["GOOG"]["position_rank"] == 1
    assert by_ticker["BRK"]["portfolio_weight_pct"]["value"] == 33.333333
    assert by_ticker["BRK"]["position_rank"] == 2


def test_manager_holdings_exposes_portfolio_summary_and_local_market_context(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(
        "app.services.thirteenf_user_api.compute_target_date",
        lambda _now: date(2026, 6, 30),
    )
    _clear_13f(db_session)
    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0000000007-26-000001")
    parse_run = _parse_run(db_session, filing)
    stock = _stock(db_session, "PRICE")
    holding = _holding(db_session, filing, parse_run, index=1, stock=stock)
    holding.value_usd = 300_000
    holding.ssh_prnamt = 3_000
    holding.shares = 3_000
    holding.portfolio_weight_pct = 30.0
    filing.total_13f_common_value_usd = 1_000_000
    db_session.add_all(
        [
            StockPrice(
                stock_id=stock.id,
                price_date=date(2025, 9, 30),
                open=75.0,
                high=80.0,
                low=70.0,
                close=78.0,
                source="test",
                currency="USD",
            ),
            StockPrice(
                stock_id=stock.id,
                price_date=date(2026, 6, 30),
                open=118.0,
                high=125.0,
                low=115.0,
                close=120.0,
                source="test",
                currency="USD",
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings?quarter=2026-Q1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "common_position_count": 1,
        "reported_common_value_usd": 1_000_000,
    }
    position = payload["common_holdings"][0]
    assert position["implied_report_price"] == 100.0
    assert position["implied_report_price_currency"] == "USD"
    assert position["market_context"] == {
        "latest_price": 120.0,
        "latest_price_date": "2026-06-30",
        "latest_price_currency": "USD",
        "latest_price_source": "test",
        "latest_price_freshness": "fresh",
        "latest_price_reason": None,
        "change_since_report_pct": 20.0,
        "change_since_report_reason": None,
        "week_52_low": 70.0,
        "week_52_high": 125.0,
        "week_52_reason": None,
        "source": "test",
    }


def test_manager_holdings_does_not_compare_usd_report_value_with_other_currency(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(
        "app.services.thirteenf_user_api.compute_target_date",
        lambda _now: date(2026, 6, 30),
    )
    _clear_13f(db_session)
    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0000000007-26-000002")
    parse_run = _parse_run(db_session, filing)
    stock = _stock(db_session, "CADPX")
    holding = _holding(db_session, filing, parse_run, index=1, stock=stock)
    holding.value_usd = 10_000
    holding.ssh_prnamt = 100
    holding.shares = 100
    db_session.add_all(
        [
            StockPrice(
                stock_id=stock.id,
                price_date=date(2025, 9, 30),
                open=85.0,
                high=90.0,
                low=80.0,
                close=88.0,
                source="test",
                currency="EUR",
            ),
            StockPrice(
                stock_id=stock.id,
                price_date=date(2026, 6, 30),
                open=145.0,
                high=160.0,
                low=140.0,
                close=150.0,
                source="test",
                currency="CAD",
            ),
        ]
    )
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/holdings?quarter=2026-Q1")

    assert response.status_code == 200
    position = response.json()["common_holdings"][0]
    assert position["implied_report_price"] == 100.0
    assert position["implied_report_price_currency"] == "USD"
    assert position["market_context"]["latest_price_currency"] == "CAD"
    assert position["market_context"]["change_since_report_pct"] is None
    assert position["market_context"]["change_since_report_reason"] == "currency_mismatch"
    assert position["market_context"]["week_52_low"] == 140.0
    assert position["market_context"]["week_52_high"] == 160.0


def test_manager_history_returns_quarter_summaries_concentration_and_all_activity(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    apple = _stock(db_session, "AAPL")
    berkshire = _stock(db_session, "BRKB")

    q4 = _filing(
        db_session,
        manager,
        "0000000008-25-000001",
        report_quarter="2025-Q4",
        quarter_end_date=date(2025, 12, 31),
    )
    q4.total_13f_common_value_usd = 200_000
    q4_run = _parse_run(db_session, q4)
    q4_apple = _holding(db_session, q4, q4_run, index=1, stock=apple)
    q4_apple.value_usd = 200_000
    q4_apple.portfolio_weight_pct = 100.0

    q1 = _filing(db_session, manager, "0000000008-26-000001")
    q1.total_13f_common_value_usd = 400_000
    q1_run = _parse_run(db_session, q1)
    q1_apple = _holding(db_session, q1, q1_run, index=1, stock=apple)
    q1_apple.value_usd = 300_000
    q1_apple.portfolio_weight_pct = 75.0
    q1_berkshire = _holding(db_session, q1, q1_run, index=2, stock=berkshire)
    q1_berkshire.value_usd = 100_000
    q1_berkshire.portfolio_weight_pct = 25.0

    _ownership_change(db_session, manager, apple, report_quarter="2025-Q4", quarter_end_date=date(2025, 12, 31))
    new_position = _ownership_change(db_session, manager, berkshire, change_status="new_position")
    new_position.previous_value_usd = None
    new_position.previous_shares = None
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/history")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available"
    assert [item["quarter"] for item in payload["quarters"]] == ["2026-Q1", "2025-Q4"]
    latest = payload["quarters"][0]
    assert latest["reported_common_value_usd"] == 400_000
    assert latest["common_position_count"] == 2
    assert [item["stock"]["ticker"] for item in latest["top_holdings"]] == ["AAPL", "BRKB"]
    assert latest["concentration"] == {"top_1_pct": 75.0, "top_5_pct": 100.0, "top_10_pct": 100.0}
    assert [(item["report_quarter"], item["stock"]["ticker"]) for item in payload["activity"]] == [
        ("2026-Q1", "BRKB"),
        ("2025-Q4", "AAPL"),
    ]
    assert payload["activity"][0]["change_status"] == "new_position"


def test_manager_position_history_returns_quarter_holdings_and_activity(client, db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session, "LONG")

    q4 = _filing(
        db_session,
        manager,
        "0000000009-25-000001",
        report_quarter="2025-Q4",
        quarter_end_date=date(2025, 12, 31),
    )
    q4.total_13f_common_value_usd = 1_000_000
    q4_run = _parse_run(db_session, q4)
    q4_holding = _holding(db_session, q4, q4_run, index=1, stock=stock)
    q4_holding.value_usd = 100_000
    q4_holding.ssh_prnamt = 1_000
    q4_holding.shares = 1_000
    q4_holding.portfolio_weight_pct = 10.0

    q1 = _filing(db_session, manager, "0000000009-26-000001")
    q1.total_13f_common_value_usd = 1_000_000
    q1_run = _parse_run(db_session, q1)
    q1_holding = _holding(db_session, q1, q1_run, index=1, stock=stock)
    q1_holding.value_usd = 150_000
    q1_holding.ssh_prnamt = 1_500
    q1_holding.shares = 1_500
    q1_holding.portfolio_weight_pct = 15.0
    change = _ownership_change(db_session, manager, stock, change_status="increased")
    change.current_shares = 1_500
    change.previous_shares = 1_000
    change.share_delta = 500
    change.share_change_pct = 0.5
    change.current_value_usd = 150_000
    change.previous_value_usd = 100_000
    db_session.commit()

    response = client.get(f"/api/v1/13f/managers/{manager.id}/stocks/{stock.id}/history")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available"
    assert payload["stock"]["ticker"] == "LONG"
    assert [item["quarter"] for item in payload["items"]] == ["2026-Q1", "2025-Q4"]
    assert payload["items"][0]["shares"] == 1_500
    assert payload["items"][0]["portfolio_weight_pct"] == 15.0
    assert payload["items"][0]["implied_report_price"] == 100.0
    assert payload["items"][0]["activity"]["change_status"] == "increased"
    assert payload["items"][1]["activity"] is None


def test_stock_holders_aggregation_counts_only_direct_common_holders(client, db_session):
    _clear_13f(db_session)
    stock = _stock(db_session, "AGG")
    featured = _manager(db_session, "Featured Fundamental", manager_type="long_term_fundamental", is_featured=True)
    activist = _manager(
        db_session,
        "Activist Holder",
        manager_type="activist",
        style_primary="activist",
        is_featured=False,
    )
    quant = _manager(
        db_session,
        "Quant Holder",
        manager_type="quant",
        style_primary="growth_long_short",
        historical_turnover="high",
        is_featured=False,
    )
    shared = _manager(db_session, "Shared Attribution", manager_type="long_term_fundamental", is_featured=True)
    unresolved = _manager(db_session, "Unresolved Attribution", manager_type="long_term_fundamental", is_featured=True)

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
    new_position = _ownership_change(db_session, featured, stock, change_status="new_position")
    new_position.previous_value_usd = None
    new_position.value_delta_usd = None
    new_position.previous_shares = None
    new_position.share_delta = None
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
    assert payload["manager_scope"] == "value"
    assert payload["direct_holder_count"] == 1
    assert payload["value_manager_direct_count"] == 1
    assert payload["featured_holder_count"] == 1
    assert payload["attribution_caveat_count"] == 2
    assert [item["manager"]["id"] for item in payload["top_holders"]] == [featured.id]
    assert payload["top_holders"][0]["portfolio_weight_pct"] == 12.5
    assert {item["change_status"] for item in payload["recent_changes"]} == {"new_position"}
    assert {item["manager"]["id"] for item in payload["recent_changes"]} == {featured.id}
    assert payload["recent_changes"][0]["value_delta_usd"] == 200000
    assert payload["recent_changes"][0]["share_delta"] == 200

    all_response = client.get(f"/api/v1/13f/stocks/{stock.id}/holders?manager_scope=all")
    assert all_response.status_code == 200
    all_payload = all_response.json()
    assert all_payload["manager_scope"] == "all"
    assert all_payload["direct_holder_count"] == 3
    assert [item["manager"]["id"] for item in all_payload["top_holders"]] == [activist.id, featured.id, quant.id]
    assert {item["manager"]["id"] for item in all_payload["recent_changes"]} == {
        featured.id,
        activist.id,
    }


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


def test_filing_caveats_surfaces_shared_discretion_on_complete_holdings_report(db_session):
    """Review #3: a COMPLETE holdings_report that lists cover-page included
    managers (Berkshire-style) surfaces a SHARED_DISCRETION caveat even though
    report_type != combination_report — so its holdings are not shown as
    uncaveated independent sole-manager positions."""
    from app.services.thirteenf_user_api import _filing_caveats

    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0001193125-26-990001")
    filing.other_managers_included = [{"cik": "0000000004", "name": "GEICO CORP"}]
    db_session.flush()

    codes = {c["code"] for c in _filing_caveats(filing)}
    assert "SHARED_DISCRETION" in codes
    assert "COMBINATION_REPORT" not in codes  # not gated on report_type/coverage


def test_manager_holdings_returns_verified_empty_portfolio_as_available(db_session):
    from app.services.thirteenf_user_api import build_user_manager_holdings

    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0001540866-26-000002")
    filing.total_13f_common_value_usd = 0
    _parse_run(db_session, filing)
    db_session.flush()

    result = build_user_manager_holdings(
        db_session,
        manager.id,
        quarter="2026-Q1",
        include_market_context=False,
    )

    assert result["status"] == "available"
    assert result["summary"] == {
        "common_position_count": 0,
        "reported_common_value_usd": 0,
    }
    assert result["common_holdings"] == []
    assert result["options"] == []


def test_filing_caveats_no_shared_discretion_without_included_managers(db_session):
    from app.services.thirteenf_user_api import _filing_caveats

    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0001193125-26-990002")
    db_session.flush()
    codes = {c["code"] for c in _filing_caveats(filing)}
    assert "SHARED_DISCRETION" not in codes


def test_manager_holdings_shared_discretion_from_dfnd_without_included_managers(db_session):
    """Review re-check #3.1: a COMPLETE holdings_report with DFND holdings but no
    cover-page included-managers list (sub-threshold shared discretion, no
    Column 7) still surfaces the SHARED_DISCRETION caveat on the manager-holdings
    display — derived from the holdings' discretion, not just filing metadata."""
    from app.services.thirteenf_user_api import build_user_manager_holdings

    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0001279936-26-000004")  # complete/normal, no other_managers_included
    run = _parse_run(db_session, filing)
    holding = _holding(db_session, filing, run, index=1)
    holding.investment_discretion = "DFND"
    db_session.flush()

    result = build_user_manager_holdings(db_session, manager.id, quarter="2026-Q1")
    codes = {c["code"] for c in result.get("caveats", [])}
    assert "SHARED_DISCRETION" in codes
    assert result["status"] == "available_with_caveat"


def test_shared_discretion_caveat_copy_is_neutral():
    """Re-review #2: the caveat must not claim 'included managers (e.g.
    subsidiaries)' — the sub-threshold (no Column 7) case need not involve an
    included manager or a subsidiary."""
    from app.services.thirteenf_user_api import SHARED_DISCRETION_CAVEAT

    assert "other managers" in SHARED_DISCRETION_CAVEAT
    assert "included managers (e.g. subsidiaries)" not in SHARED_DISCRETION_CAVEAT
