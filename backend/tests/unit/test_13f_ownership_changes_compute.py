from datetime import date

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    OwnershipChange13F,
    ParseRun13F,
)
from app.models.stocks import Stock
from app.services.thirteenf_ownership_changes import compute_ownership_changes_for_manager_quarter


def _manager(db_session, name: str = "MVP2 Compute Manager") -> InstitutionManager:
    manager = InstitutionManager(
        canonical_name=name,
        legal_name=name,
        cik="0009100001",
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session, ticker: str) -> Stock:
    stock = Stock(ticker=ticker, exchange="NASDAQ", company_name=f"{ticker} Inc.")
    db_session.add(stock)
    db_session.flush()
    return stock


def _quarter_end(quarter: str) -> date:
    year = int(quarter[:4])
    q = int(quarter[-1])
    return {
        1: date(year, 3, 31),
        2: date(year, 6, 30),
        3: date(year, 9, 30),
        4: date(year, 12, 31),
    }[q]


def _filing(
    db_session,
    manager: InstitutionManager,
    *,
    quarter: str,
    accession: str,
    form_type: str = "13F-HR",
    report_type: str = "holdings_report",
    coverage_completeness: str = "complete",
    coverage_type: str = "normal",
    amendment_status: str = "no_amendments_seen",
    has_confidential_treatment: bool = False,
    confidential_treatment_status: str = "none",
) -> Filing13F:
    qend = _quarter_end(quarter)
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=qend,
        filed_at=qend,
        filing_date=qend,
        form_type=form_type,
        report_type=report_type,
        coverage_completeness=coverage_completeness,
        coverage_type=coverage_type,
        has_confidential_treatment=has_confidential_treatment,
        confidential_treatment_status=confidential_treatment_status,
        report_quarter=quarter,
        quarter_end_date=qend,
        official_filing_deadline=qend,
        is_active_for_manager_period=True,
        parse_status="succeeded" if form_type != "13F-NT" else "pending",
        amendment_status=amendment_status,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _parse_run(db_session, filing: Filing13F) -> ParseRun13F:
    run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="mvp2-test",
        status="succeeded",
        is_current=True,
    )
    db_session.add(run)
    db_session.flush()
    return run


def _holding(
    db_session,
    filing: Filing13F,
    run: ParseRun13F,
    stock: Stock | None,
    *,
    cusip: str,
    shares: int,
    value_usd: int,
    row: str,
    put_call: str | None = None,
    ssh_prnamt_type: str = "SH",
    attribution_status: str = "direct",
) -> Holding13F:
    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=run.id,
        manager_id=filing.manager_id,
        accession_number=filing.accession_number,
        report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date,
        row_fingerprint=f"{filing.accession_number}:{row}",
        holding_row_fingerprint=f"{filing.accession_number}:{row}:v1",
        cusip=cusip,
        issuer_name=stock.company_name if stock else f"Unlinked {cusip}",
        value_thousands=value_usd // 1000,
        value_usd=value_usd,
        shares=shares,
        ssh_prnamt=shares,
        ssh_prnamt_type=ssh_prnamt_type,
        put_call=put_call,
        holding_attribution_status=attribution_status,
        stock_id=stock.id if stock else None,
        cusip_mapping_status="linked" if stock else "unresolved",
        portfolio_weight_pct=0.1,
    )
    db_session.add(holding)
    db_session.flush()
    return holding


def _rows(db_session) -> list[OwnershipChange13F]:
    return db_session.query(OwnershipChange13F).order_by(OwnershipChange13F.security_key).all()


def test_compute_changes_classifies_strong_labels_and_cusip_changed(db_session):
    manager = _manager(db_session)
    inc = _stock(db_session, "INC")
    new = _stock(db_session, "NEW")
    exited = _stock(db_session, "EXT")
    changed = _stock(db_session, "CHG")
    previous = _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000001-25-000001",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000001-26-000001",
    )
    previous_run = _parse_run(db_session, previous)
    current_run = _parse_run(db_session, current)

    _holding(db_session, previous, previous_run, inc, cusip="111111111", shares=100, value_usd=1000, row="inc")
    _holding(db_session, current, current_run, inc, cusip="111111111", shares=150, value_usd=1800, row="inc")
    _holding(db_session, current, current_run, new, cusip="222222222", shares=10, value_usd=500, row="new")
    _holding(db_session, previous, previous_run, exited, cusip="333333333", shares=25, value_usd=700, row="exit")
    _holding(db_session, previous, previous_run, changed, cusip="444444444", shares=40, value_usd=900, row="chg")
    _holding(db_session, current, current_run, changed, cusip="555555555", shares=40, value_usd=950, row="chg")

    result = compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    assert result == {"created": 4, "deleted": 0, "status": "succeeded"}
    by_stock = {row.stock_id: row for row in _rows(db_session)}
    assert by_stock[inc.id].change_status == "increased"
    assert by_stock[inc.id].confidence_level == "high_confidence"
    assert by_stock[inc.id].is_primary_signal_eligible is True
    assert by_stock[inc.id].share_delta == 50
    assert float(by_stock[inc.id].share_change_pct) == 0.5
    assert by_stock[new.id].change_status == "new_position"
    assert by_stock[exited.id].change_status == "exited_position"
    assert by_stock[changed.id].change_status == "cusip_changed"
    assert by_stock[changed.id].current_cusip == "555555555"
    assert by_stock[changed.id].previous_cusip == "444444444"
    assert by_stock[changed.id].caveat_codes == ["cusip_changed"]


def test_stock_mapping_added_between_quarters_matches_by_cusip_not_exit_and_new(db_session):
    manager = _manager(db_session)
    stock = _stock(db_session, "MAP")
    previous = _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000007-25-000001",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000007-26-000001",
    )
    previous_run = _parse_run(db_session, previous)
    current_run = _parse_run(db_session, current)
    _holding(db_session, previous, previous_run, None, cusip="123456789", shares=10, value_usd=100, row="prev")
    _holding(db_session, current, current_run, stock, cusip="123456789", shares=15, value_usd=150, row="curr")

    result = compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    assert result["created"] == 1
    row = _rows(db_session)[0]
    assert row.change_status == "increased"
    assert row.stock_id == stock.id
    assert row.security_key == "cusip:123456789"
    assert row.current_holding_id is not None
    assert row.previous_holding_id is not None
    assert row.share_delta == 5


def test_reduced_and_unchanged_statuses_are_emitted(db_session):
    manager = _manager(db_session)
    reduced = _stock(db_session, "RED")
    unchanged = _stock(db_session, "SAME")
    previous = _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000008-25-000001",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000008-26-000001",
    )
    previous_run = _parse_run(db_session, previous)
    current_run = _parse_run(db_session, current)
    _holding(db_session, previous, previous_run, reduced, cusip="123456781", shares=20, value_usd=200, row="red")
    _holding(db_session, current, current_run, reduced, cusip="123456781", shares=5, value_usd=50, row="red")
    _holding(db_session, previous, previous_run, unchanged, cusip="123456782", shares=7, value_usd=70, row="same")
    _holding(db_session, current, current_run, unchanged, cusip="123456782", shares=7, value_usd=80, row="same")

    compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    by_stock = {row.stock_id: row for row in _rows(db_session)}
    assert by_stock[reduced.id].change_status == "reduced"
    assert by_stock[reduced.id].share_delta == -15
    assert by_stock[unchanged.id].change_status == "unchanged"
    assert by_stock[unchanged.id].share_delta == 0


def test_prior_nt_yields_no_prior_data_not_new_position(db_session):
    manager = _manager(db_session)
    stock = _stock(db_session, "NTQ")
    _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000002-25-000001",
        form_type="13F-NT",
        report_type="notice_report",
        coverage_completeness="unknown",
        coverage_type="notice_reported_elsewhere",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000002-26-000001",
    )
    current_run = _parse_run(db_session, current)
    _holding(db_session, current, current_run, stock, cusip="666666666", shares=10, value_usd=1000, row="nt")

    result = compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    assert result["created"] == 1
    row = _rows(db_session)[0]
    assert row.change_status == "no_prior_data"
    assert row.confidence_level == "unavailable"
    assert row.is_primary_signal_eligible is False
    assert row.unavailable_reason == "prior_quarter_13f_nt"
    assert row.caveat_codes == ["prior_quarter_13f_nt"]


def test_missing_prior_filing_yields_no_prior_data(db_session):
    manager = _manager(db_session)
    stock = _stock(db_session, "MIS")
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000009-26-000001",
    )
    current_run = _parse_run(db_session, current)
    _holding(db_session, current, current_run, stock, cusip="223456789", shares=10, value_usd=1000, row="missing")

    compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    row = _rows(db_session)[0]
    assert row.change_status == "no_prior_data"
    assert row.unavailable_reason == "missing_prior_quarter"
    assert row.is_primary_signal_eligible is False


def test_confidential_treatment_downgrades_primary_signal(db_session):
    manager = _manager(db_session)
    stock = _stock(db_session, "CNF")
    previous = _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000010-25-000001",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000010-26-000001",
        has_confidential_treatment=True,
        confidential_treatment_status="requested",
    )
    previous_run = _parse_run(db_session, previous)
    current_run = _parse_run(db_session, current)
    _holding(db_session, previous, previous_run, stock, cusip="323456789", shares=10, value_usd=1000, row="conf")
    _holding(db_session, current, current_run, stock, cusip="323456789", shares=20, value_usd=2000, row="conf")

    compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    row = _rows(db_session)[0]
    assert row.change_status == "increased"
    assert row.confidence_level == "medium_confidence"
    assert row.is_primary_signal_eligible is False
    assert row.has_confidential_treatment_caveat is True
    assert row.caveat_codes == ["confidential_treatment"]


def test_combination_report_downgrades_primary_signal(db_session):
    manager = _manager(db_session)
    stock = _stock(db_session, "COMB")
    previous = _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000011-25-000001",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000011-26-000001",
        report_type="combination_report",
    )
    previous_run = _parse_run(db_session, previous)
    current_run = _parse_run(db_session, current)
    _holding(db_session, previous, previous_run, stock, cusip="423456789", shares=10, value_usd=1000, row="comb")
    _holding(db_session, current, current_run, stock, cusip="423456789", shares=20, value_usd=2000, row="comb")

    compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    row = _rows(db_session)[0]
    assert row.change_status == "increased"
    assert row.confidence_level == "low_confidence"
    assert row.is_primary_signal_eligible is False
    assert row.has_combination_report_caveat is True
    assert row.caveat_codes == ["combination_report"]


def test_pending_amendment_downgrades_primary_signal(db_session):
    manager = _manager(db_session)
    stock = _stock(db_session, "AMD")
    previous = _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000012-25-000001",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000012-26-000001",
        amendment_status="amendments_pending",
    )
    previous_run = _parse_run(db_session, previous)
    current_run = _parse_run(db_session, current)
    _holding(db_session, previous, previous_run, stock, cusip="523456789", shares=10, value_usd=1000, row="amend")
    _holding(db_session, current, current_run, stock, cusip="523456789", shares=20, value_usd=2000, row="amend")

    compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    row = _rows(db_session)[0]
    assert row.change_status == "increased"
    assert row.confidence_level == "low_confidence"
    assert row.is_primary_signal_eligible is False
    assert row.has_pending_amendment_caveat is True
    assert row.caveat_codes == ["pending_amendment"]


def test_compute_changes_separates_put_and_call_position_types(db_session):
    manager = _manager(db_session)
    stock = _stock(db_session, "OPT")
    previous = _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000003-25-000001",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000003-26-000001",
    )
    previous_run = _parse_run(db_session, previous)
    current_run = _parse_run(db_session, current)

    for put_call in ("PUT", "CALL"):
        _holding(
            db_session,
            previous,
            previous_run,
            stock,
            cusip="777777777",
            shares=10,
            value_usd=100,
            row=f"prev-{put_call}",
            put_call=put_call,
        )
        _holding(
            db_session,
            current,
            current_run,
            stock,
            cusip="777777777",
            shares=12,
            value_usd=120,
            row=f"curr-{put_call}",
            put_call=put_call,
        )

    compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    rows = _rows(db_session)
    assert {row.position_type for row in rows} == {"put_option", "call_option"}
    assert {row.put_call for row in rows} == {"PUT", "CALL"}
    assert {row.change_status for row in rows} == {"increased"}


def test_mapping_ratio_between_50_and_70_caps_primary_signal_labels(db_session):
    manager = _manager(db_session)
    linked = _stock(db_session, "LNK")
    previous = _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000005-25-000001",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000005-26-000001",
    )
    previous_run = _parse_run(db_session, previous)
    current_run = _parse_run(db_session, current)
    _holding(db_session, previous, previous_run, linked, cusip="999999991", shares=10, value_usd=100, row="linked")
    _holding(db_session, current, current_run, linked, cusip="999999991", shares=20, value_usd=200, row="linked")
    _holding(db_session, previous, previous_run, None, cusip="999999992", shares=5, value_usd=50, row="unlinked")
    _holding(db_session, current, current_run, None, cusip="999999992", shares=5, value_usd=50, row="unlinked")

    result = compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    assert result["created"] == 2
    linked_row = next(row for row in _rows(db_session) if row.stock_id == linked.id)
    assert linked_row.change_status == "increased"
    assert linked_row.confidence_level == "low_confidence"
    assert linked_row.is_primary_signal_eligible is False
    assert linked_row.caveat_codes == ["mapping_below_ready_threshold"]


def test_mapping_ratio_below_50_blocks_change_analysis(db_session):
    manager = _manager(db_session)
    previous = _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000006-25-000001",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000006-26-000001",
    )
    previous_run = _parse_run(db_session, previous)
    current_run = _parse_run(db_session, current)
    _holding(db_session, previous, previous_run, None, cusip="999999993", shares=5, value_usd=50, row="unlinked")
    _holding(db_session, current, current_run, None, cusip="999999993", shares=10, value_usd=100, row="unlinked")

    result = compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    assert result["created"] == 1
    row = _rows(db_session)[0]
    assert row.change_status == "unresolvable"
    assert row.confidence_level == "unavailable"
    assert row.is_primary_signal_eligible is False
    assert row.unavailable_reason == "mapping_threshold_failed"
    assert row.caveat_codes == ["mapping_threshold_failed"]


def test_compute_changes_is_idempotent_for_manager_quarter(db_session):
    manager = _manager(db_session)
    stock = _stock(db_session, "IDM")
    previous = _filing(
        db_session,
        manager,
        quarter="2025-Q4",
        accession="0000000004-25-000001",
    )
    current = _filing(
        db_session,
        manager,
        quarter="2026-Q1",
        accession="0000000004-26-000001",
    )
    previous_run = _parse_run(db_session, previous)
    current_run = _parse_run(db_session, current)
    _holding(db_session, previous, previous_run, stock, cusip="888888888", shares=20, value_usd=200, row="prev")
    _holding(db_session, current, current_run, stock, cusip="888888888", shares=30, value_usd=300, row="curr")

    first = compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )
    second = compute_ownership_changes_for_manager_quarter(
        db_session,
        manager_id=manager.id,
        report_quarter="2026-Q1",
    )

    assert first == {"created": 1, "deleted": 0, "status": "succeeded"}
    assert second == {"created": 1, "deleted": 1, "status": "succeeded"}
    assert db_session.query(OwnershipChange13F).count() == 1
