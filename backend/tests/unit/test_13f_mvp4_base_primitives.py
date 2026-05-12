"""MVP4-02 base primitives tests.

TDD coverage for the three shared scoring primitives consumed by
MVP4-03 (signal-weighted score) and MVP4-04 (conviction score):

  - compute_portfolio_weight (plan §7.3)
  - compute_holding_streak    (plan §7.10)
  - compute_add_intensity     (plan §7.4)

D2 / D3 caveat-propagation rules are exercised here at the primitive
layer; MVP4-05 will surface them to the user-facing caution-flags
service.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from itertools import count

import pytest

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    ParseRun13F,
    QualityFinding13F,
    QualityReport13F,
)
from app.models.stocks import Stock
from app.services.oracles_lens.base_primitives import (
    HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT,
    NT_QUARTER_STREAK_BREAK_CAVEAT,
    PARTIAL_COVERAGE_CAVEAT,
    PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT,
    STALE_UNTIL_RECOMPUTE_CAVEAT,
    AddIntensityResult,
    HoldingStreakResult,
    PortfolioWeightResult,
    compute_add_intensity,
    compute_holding_streak,
    compute_portfolio_weight,
)


_CIK_SEQ = count(9990500000)
_ACC_SEQ = count(800001)
_STOCK_SEQ = count(95001)
_REPORT_SEQ = count(800001)


def _clear_13f(db_session) -> None:
    db_session.query(QualityFinding13F).delete()
    db_session.query(QualityReport13F).delete()
    db_session.query(Holding13F).delete()
    db_session.query(ParseRun13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(InstitutionManagerCikReviewEvent).delete()
    db_session.query(InstitutionManager).delete()
    db_session.flush()


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv4-02 Mgr {cik}",
        legal_name=f"Mv4-02 Mgr {cik}",
        edgar_legal_name=f"Mv4-02 Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session) -> Stock:
    seq = next(_STOCK_SEQ)
    stock = Stock(
        ticker=f"M4{seq:05d}"[-10:],
        exchange="NYSE",
        company_name=f"M4Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _quarter_end(quarter: str) -> date:
    year_str, qtr_str = quarter.split("-Q")
    period_end_month = int(qtr_str) * 3
    last_day = 31 if period_end_month in (1, 3, 5, 7, 8, 10, 12) else 30
    return date(int(year_str), period_end_month, last_day)


def _filing(
    db_session,
    manager: InstitutionManager,
    *,
    quarter: str,
    coverage_type: str = "normal",
    coverage_completeness: str = "complete",
    form_type: str = "13F-HR",
    computed_total: int | None = 1_000_000,
    reported_total: int | None = 1_000_000,
) -> Filing13F:
    accession = f"00099050-26-{next(_ACC_SEQ):06d}"
    period_end = _quarter_end(quarter)
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=period_end,
        filed_at=period_end,
        filing_date=period_end,
        accepted_at=datetime(period_end.year, period_end.month, period_end.day, 17, tzinfo=timezone.utc),
        form_type=form_type,
        report_type="notice_report" if form_type == "13F-NT" else "holdings_report",
        coverage_completeness=coverage_completeness,
        coverage_type=coverage_type,
        quarter_end_date=period_end,
        report_quarter=quarter,
        official_filing_deadline=date(period_end.year, period_end.month, 15),
        parse_status="succeeded",
        is_active_for_manager_period=True,
        is_latest_for_period=True,
        amendment_status="no_amendments_seen",
        computed_total_value_thousands=computed_total,
        reported_total_value_thousands=reported_total,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _current_parse_run(db_session, filing: Filing13F) -> ParseRun13F:
    parse_run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="test",
        fingerprint_version="v1",
        status="succeeded",
        holdings_count=0,
        is_current=True,
    )
    db_session.add(parse_run)
    db_session.flush()
    return parse_run


def _holding(
    db_session,
    filing: Filing13F,
    *,
    parse_run: ParseRun13F | None = None,
    stock: Stock | None = None,
    shares: int = 100,
    value_thousands: int = 200,
) -> Holding13F:
    pr = parse_run or _current_parse_run(db_session, filing)
    s = stock or _stock(db_session)
    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=pr.id,
        manager_id=filing.manager_id,
        accession_number=filing.accession_number,
        report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date,
        row_fingerprint=f"{filing.accession_number}-{s.id}",
        holding_row_fingerprint=f"{filing.accession_number}-{s.id}",
        cusip=f"{s.id:09d}",
        issuer_name=f"Issuer {s.id}",
        name_of_issuer=f"Issuer {s.id}",
        title_of_class="COM",
        value_thousands=value_thousands,
        value_raw=f"{value_thousands * 1000}",
        value_unit_raw="dollars",
        value_parse_rule="schema_dollars",
        value_usd=value_thousands * 1000,
        shares=shares,
        ssh_prnamt=shares,
        share_type="SH",
        ssh_prnamt_type="SH",
        investment_discretion="SOLE",
        holding_attribution_status="direct",
        voting_sole=shares,
        voting_shared=0,
        voting_none=0,
        stock_id=s.id,
        cusip_mapping_status="linked",
        source_row_index=0,
    )
    db_session.add(holding)
    db_session.flush()
    pr.holdings_count = (pr.holdings_count or 0) + 1
    return holding


def _open_finding(
    db_session,
    *,
    rule_code: str,
    manager: InstitutionManager,
    quarter: str,
) -> QualityFinding13F:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
    report = QualityReport13F(
        quarter=quarter,
        status="warning",
        error_count=0,
        warning_count=1,
        info_count=0,
        summary=f"test report for {rule_code}",
        checked_at=now,
    )
    db_session.add(report)
    db_session.flush()
    seq = next(_REPORT_SEQ)
    finding = QualityFinding13F(
        validation_run_id=report.id,
        rule_code=rule_code,
        severity="warning",
        entity_type="filing",
        entity_id=None,
        quarter=quarter,
        manager_id=manager.id,
        accession_number=f"finding-{seq}",
        detail=f"test {rule_code}",
        value_json={"rule_code": rule_code},
        status="open",
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(finding)
    db_session.flush()
    return finding


# ===========================================================================
# compute_portfolio_weight (plan §7.3)
# ===========================================================================


def test_portfolio_weight_uses_computed_total_when_present(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    filing = _filing(
        db_session, manager, quarter="2026-Q1",
        computed_total=10_000, reported_total=20_000,
    )
    holding = _holding(db_session, filing, value_thousands=500)

    result = compute_portfolio_weight(holding)

    assert isinstance(result, PortfolioWeightResult)
    assert result.value == Decimal("0.05")  # 500 / 10000
    assert result.caveats == []


def test_portfolio_weight_falls_back_to_reported_total_when_computed_null(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    filing = _filing(
        db_session, manager, quarter="2026-Q1",
        computed_total=None, reported_total=20_000,
    )
    holding = _holding(db_session, filing, value_thousands=500)

    result = compute_portfolio_weight(holding)

    assert result.value == Decimal("0.025")  # 500 / 20000


def test_portfolio_weight_returns_none_for_partial_coverage(db_session):
    """D3 rule (a): portfolio_weight_pct is mandated NULL on
    coverage_completeness=partial filings (PRD §7.2 line 588-592).
    """
    _clear_13f(db_session)
    manager = _manager(db_session)
    filing = _filing(
        db_session, manager, quarter="2026-Q1",
        coverage_completeness="partial",
        computed_total=10_000, reported_total=10_000,
    )
    holding = _holding(db_session, filing, value_thousands=500)

    result = compute_portfolio_weight(holding)

    assert result.value is None
    assert PARTIAL_COVERAGE_CAVEAT in result.caveats


def test_portfolio_weight_returns_none_when_both_totals_null(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    filing = _filing(
        db_session, manager, quarter="2026-Q1",
        computed_total=None, reported_total=None,
    )
    holding = _holding(db_session, filing, value_thousands=500)

    result = compute_portfolio_weight(holding)

    assert result.value is None


# ===========================================================================
# compute_holding_streak (plan §7.10)
# ===========================================================================


def test_holding_streak_counts_consecutive_quarters(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session)
    for q in ("2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1"):
        filing = _filing(db_session, manager, quarter=q)
        _holding(db_session, filing, stock=stock)

    result = compute_holding_streak(
        db_session,
        manager_id=manager.id,
        stock_id=stock.id,
        current_quarter="2026-Q1",
    )

    assert isinstance(result, HoldingStreakResult)
    assert result.streak_quarters == 4
    # 2025-Q2 is past the 2023-Q1 floor; no PRE_2023 caveat needed.
    assert PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT not in result.caveats


def test_holding_streak_resets_after_break(db_session):
    """A non-NT quarter without a holding terminates the streak."""
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session)
    # Manager filed every quarter, but did not hold the stock in 2025-Q3.
    for q in ("2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1"):
        filing = _filing(db_session, manager, quarter=q)
        if q != "2025-Q3":
            _holding(db_session, filing, stock=stock)
        else:
            _holding(db_session, filing, stock=_stock(db_session))  # holds something else

    result = compute_holding_streak(
        db_session,
        manager_id=manager.id,
        stock_id=stock.id,
        current_quarter="2026-Q1",
    )

    # 2026-Q1 + 2025-Q4 count; 2025-Q3 is a break.
    assert result.streak_quarters == 2


def test_holding_streak_nt_quarter_resets_and_emits_caveat(db_session):
    """D3 rule (d): NT quarter resets streak, must emit
    NT_QUARTER_STREAK_BREAK caveat, and must not classify holding as
    exit.
    """
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session)
    # Q2 and Q3 held; Q4 NT; Q1 next year held again.
    f_q2 = _filing(db_session, manager, quarter="2025-Q2")
    _holding(db_session, f_q2, stock=stock)
    f_q3 = _filing(db_session, manager, quarter="2025-Q3")
    _holding(db_session, f_q3, stock=stock)
    _filing(db_session, manager, quarter="2025-Q4", form_type="13F-NT")
    f_q1 = _filing(db_session, manager, quarter="2026-Q1")
    _holding(db_session, f_q1, stock=stock)

    result = compute_holding_streak(
        db_session,
        manager_id=manager.id,
        stock_id=stock.id,
        current_quarter="2026-Q1",
    )

    # NT quarter resets — only 2026-Q1 counts after the reset.
    assert result.streak_quarters == 1
    assert NT_QUARTER_STREAK_BREAK_CAVEAT in result.caveats


def test_holding_streak_at_data_window_floor_emits_pre_2023_caveat(db_session):
    """D2: when the walk reaches data_window_start_quarter while the
    streak is still active, the holder may have started before the
    window so we cannot say 'new'. Emit
    PRE_2023_PRE_HISTORY_UNAVAILABLE.
    """
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session)
    for q in ("2023-Q1", "2023-Q2", "2023-Q3"):
        filing = _filing(db_session, manager, quarter=q)
        _holding(db_session, filing, stock=stock)

    result = compute_holding_streak(
        db_session,
        manager_id=manager.id,
        stock_id=stock.id,
        current_quarter="2023-Q3",
        data_window_start_quarter="2023-Q1",
    )

    assert result.streak_quarters == 3
    assert PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT in result.caveats


# ===========================================================================
# compute_add_intensity (plan §7.4)
# ===========================================================================


def test_add_intensity_uses_shares_delta(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session)
    f_prev = _filing(db_session, manager, quarter="2025-Q4")
    _holding(db_session, f_prev, stock=stock, shares=100)
    f_cur = _filing(db_session, manager, quarter="2026-Q1")
    _holding(db_session, f_cur, stock=stock, shares=150)

    result = compute_add_intensity(
        db_session,
        manager_id=manager.id,
        stock_id=stock.id,
        current_quarter="2026-Q1",
    )

    assert isinstance(result, AddIntensityResult)
    # (150 - 100) / max(150, 100) = 50/150 = 0.333…
    assert result.value is not None
    assert Decimal("0.32") < result.value < Decimal("0.34")


def test_add_intensity_new_position_returns_one_after_window_floor(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session)
    # No prior holding; previous quarter (2025-Q4) is after the floor.
    f_cur = _filing(db_session, manager, quarter="2026-Q1")
    _holding(db_session, f_cur, stock=stock, shares=150)
    # A different stock in 2025-Q4 just so the manager has an active filing
    # in the previous quarter (otherwise we cannot distinguish "no prior
    # holding for this stock" from "no prior data at all").
    f_prev = _filing(db_session, manager, quarter="2025-Q4")
    _holding(db_session, f_prev, stock=_stock(db_session), shares=10)

    result = compute_add_intensity(
        db_session,
        manager_id=manager.id,
        stock_id=stock.id,
        current_quarter="2026-Q1",
    )

    assert result.value == Decimal("1.0")
    assert PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT not in result.caveats


def test_add_intensity_at_data_window_floor_returns_none_with_pre_2023_caveat(db_session):
    """D2: when the previous quarter would be before the data window,
    we cannot say 'new' vs 'pre-existing'. Return None + caveat.
    """
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session)
    f_cur = _filing(db_session, manager, quarter="2023-Q1")
    _holding(db_session, f_cur, stock=stock, shares=150)

    result = compute_add_intensity(
        db_session,
        manager_id=manager.id,
        stock_id=stock.id,
        current_quarter="2023-Q1",
        data_window_start_quarter="2023-Q1",
    )

    assert result.value is None
    assert PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT in result.caveats


def test_add_intensity_snaps_to_flat_with_recompute_caveat(db_session):
    """D3 rule (b): when an open
    OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION finding
    exists for this holder x current_quarter, snap to flat (0.0) and
    emit stale_until_recompute caveat.
    """
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session)
    f_prev = _filing(db_session, manager, quarter="2025-Q4")
    _holding(db_session, f_prev, stock=stock, shares=100)
    f_cur = _filing(db_session, manager, quarter="2026-Q1")
    _holding(db_session, f_cur, stock=stock, shares=200)
    _open_finding(
        db_session,
        rule_code="OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION",
        manager=manager,
        quarter="2026-Q1",
    )

    result = compute_add_intensity(
        db_session,
        manager_id=manager.id,
        stock_id=stock.id,
        current_quarter="2026-Q1",
    )

    assert result.value == Decimal("0.0")
    assert STALE_UNTIL_RECOMPUTE_CAVEAT in result.caveats


def test_add_intensity_snaps_to_flat_with_backfill_validation_caveat(db_session):
    """D3 rule (e): when an open HISTORICAL_BACKFILL_NEEDS_VALIDATION
    finding exists, snap to 0.0 with the canonical caveat.
    """
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session)
    f_prev = _filing(db_session, manager, quarter="2025-Q4")
    _holding(db_session, f_prev, stock=stock, shares=100)
    f_cur = _filing(db_session, manager, quarter="2026-Q1")
    _holding(db_session, f_cur, stock=stock, shares=200)
    _open_finding(
        db_session,
        rule_code="HISTORICAL_BACKFILL_NEEDS_VALIDATION",
        manager=manager,
        quarter="2026-Q1",
    )

    result = compute_add_intensity(
        db_session,
        manager_id=manager.id,
        stock_id=stock.id,
        current_quarter="2026-Q1",
    )

    assert result.value == Decimal("0.0")
    assert HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT in result.caveats
