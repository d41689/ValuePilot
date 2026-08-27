from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

from app.models.institutions import Filing13F, InstitutionManager, OwnershipChange13F
from app.models.stocks import Stock
from app.services.oracles_lens.new_buys_clusters import build_new_buys_clusters
from scripts.seed_13f_dev_fixture import (
    _run_ownership_changes,
    _seed_filings_and_holdings,
    _seed_managers,
    _seed_stocks,
)


_CIKS = count(9700000000)


def _manager(
    db_session,
    name: str,
    *,
    manager_type: str = "value_concentrated",
    style_primary: str = "value_concentrated",
    is_superinvestor: bool = True,
) -> InstitutionManager:
    manager = InstitutionManager(
        canonical_name=name,
        legal_name=name,
        display_name=name,
        cik=str(next(_CIKS)),
        status="active",
        match_status="confirmed",
        manager_type=manager_type,
        style_primary=style_primary,
        capital_structure="standard_lp",
        historical_turnover="low",
        is_superinvestor=is_superinvestor,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session, ticker: str) -> Stock:
    stock = Stock(
        ticker=ticker,
        exchange="NASDAQ",
        company_name=f"{ticker} Holdings",
        is_active=True,
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(
    db_session,
    manager: InstitutionManager,
    suffix: int,
    *,
    form_type: str = "13F-HR",
    active: bool = True,
) -> Filing13F:
    accession = f"0009700000-26-{suffix:06d}"
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=date(2026, 3, 31),
        quarter_end_date=date(2026, 3, 31),
        report_quarter="2026-Q1",
        filed_at=date(2026, 5, 10),
        filing_date=date(2026, 5, 10),
        accepted_at=datetime(2026, 5, 10, 17, tzinfo=timezone.utc),
        official_filing_deadline=date(2026, 5, 15),
        form_type=form_type,
        report_type="holdings_report" if form_type.startswith("13F-HR") else "notice_report",
        coverage_completeness="complete",
        coverage_type="normal",
        parse_status="succeeded",
        is_active_for_manager_period=active,
        is_latest_for_period=active,
        total_13f_common_value_usd=1_000_000,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _new_buy(
    db_session,
    manager: InstitutionManager,
    stock: Stock,
    filing: Filing13F,
    suffix: int,
    *,
    confidence: str = "high_confidence",
    primary: bool = True,
    caveats: list[str] | None = None,
    current_value_usd: int = 100_000,
) -> OwnershipChange13F:
    change = OwnershipChange13F(
        manager_id=manager.id,
        stock_id=stock.id,
        report_quarter="2026-Q1",
        quarter_end_date=date(2026, 3, 31),
        previous_report_quarter="2025-Q4",
        previous_quarter_end_date=date(2025, 12, 31),
        current_filing_id=filing.id,
        security_key=f"stock:{stock.id}:{suffix}",
        current_cusip=f"{suffix:09d}",
        ssh_prnamt_type="SH",
        position_type="common",
        change_status="new_position",
        confidence_level=confidence,
        is_primary_signal_eligible=primary,
        caveat_codes=caveats or [],
        current_value_usd=current_value_usd,
        value_delta_usd=current_value_usd,
        current_shares=1_000,
        share_delta=1_000,
    )
    db_session.add(change)
    db_session.flush()
    return change


def test_cluster_score_excludes_caveated_buyer_but_keeps_visible_evidence(db_session):
    alphabet = _stock(db_session, "GOOG")
    solo = _stock(db_session, "SOLO")
    berkshire = _manager(db_session, "Berkshire")
    baupost = _manager(db_session, "Baupost")
    cautious = _manager(db_session, "Cautious Value")

    berkshire_filing = _filing(db_session, berkshire, 1)
    baupost_filing = _filing(db_session, baupost, 2)
    cautious_filing = _filing(db_session, cautious, 3)
    _new_buy(db_session, berkshire, alphabet, berkshire_filing, 1, current_value_usd=150_000)
    _new_buy(db_session, baupost, alphabet, baupost_filing, 2, current_value_usd=250_000)
    _new_buy(
        db_session,
        cautious,
        alphabet,
        cautious_filing,
        3,
        confidence="low_confidence",
        primary=False,
        caveats=["PENDING_AMENDMENT"],
    )
    _new_buy(db_session, berkshire, solo, berkshire_filing, 4)

    payload = build_new_buys_clusters(
        db_session,
        quarter="2026-Q1",
        min_cluster_size=2,
        as_of_date=date(2026, 5, 12),
    )

    assert payload["quarter"] == "2026-Q1"
    assert payload["filing_window_open"] is True
    assert len(payload["items"]) == 1
    cluster = payload["items"][0]
    assert cluster["stock"]["ticker"] == "GOOG"
    assert cluster["cluster_size"] == 2
    assert cluster["visible_buyer_count"] == 3
    assert cluster["quality_weighted_cluster_score"] == 2.0
    assert [buyer["included_in_score"] for buyer in cluster["buyers"]] == [True, True, False]
    by_manager = {
        buyer["manager"]["display_name"]: buyer for buyer in cluster["buyers"]
    }
    assert by_manager["Berkshire"]["portfolio_weight_pct"] == 15.0
    assert cluster["buyers"][2]["score_exclusion_reasons"] == [
        "LOW_CONFIDENCE",
        "NOT_PRIMARY_SIGNAL_ELIGIBLE",
        "PENDING_AMENDMENT",
    ]


def test_default_value_scope_excludes_quant_and_non_superinvestors(db_session):
    stock = _stock(db_session, "VALUE")
    value = _manager(db_session, "Value Manager")
    quant = _manager(
        db_session,
        "Quant Manager",
        manager_type="quant",
        style_primary="multi_strategy_macro",
    )
    uncurated = _manager(db_session, "Uncurated Manager", is_superinvestor=False)
    for suffix, manager in enumerate((value, quant, uncurated), start=11):
        _new_buy(db_session, manager, stock, _filing(db_session, manager, suffix), suffix)

    default_payload = build_new_buys_clusters(
        db_session,
        quarter="2026-Q1",
        min_cluster_size=1,
    )
    assert default_payload["items"][0]["cluster_size"] == 1
    assert [buyer["manager"]["display_name"] for buyer in default_payload["items"][0]["buyers"]] == [
        "Value Manager"
    ]

    all_payload = build_new_buys_clusters(
        db_session,
        quarter="2026-Q1",
        min_cluster_size=1,
        manager_scope="all",
        superinvestors_only=False,
    )
    assert all_payload["items"][0]["cluster_size"] == 3


def test_cluster_requires_current_active_hr_filing(db_session):
    stock = _stock(db_session, "STALE")
    active_manager = _manager(db_session, "Active Manager")
    nt_manager = _manager(db_session, "Notice Manager")
    stale_manager = _manager(db_session, "Stale Manager")
    _new_buy(db_session, active_manager, stock, _filing(db_session, active_manager, 21), 21)
    _new_buy(
        db_session,
        nt_manager,
        stock,
        _filing(db_session, nt_manager, 22, form_type="13F-NT"),
        22,
    )
    _new_buy(
        db_session,
        stale_manager,
        stock,
        _filing(db_session, stale_manager, 23, active=False),
        23,
    )

    payload = build_new_buys_clusters(
        db_session,
        quarter="2026-Q1",
        min_cluster_size=1,
        manager_scope="all",
    )
    assert payload["items"][0]["cluster_size"] == 1
    assert payload["items"][0]["buyers"][0]["manager"]["display_name"] == "Active Manager"


def test_dev_fixture_produces_value_manager_cluster_for_visual_acceptance(db_session):
    stocks = _seed_stocks(db_session)
    managers = _seed_managers(db_session)
    _seed_filings_and_holdings(db_session, stocks=stocks, managers=managers)
    summary = _run_ownership_changes(db_session)

    payload = build_new_buys_clusters(
        db_session,
        quarter="2026-Q1",
        min_cluster_size=2,
    )

    assert summary["managers_processed"] == 32
    assert any(
        item["stock"]["ticker"] == "DEVSEED3" and item["cluster_size"] >= 2
        for item in payload["items"]
    )
