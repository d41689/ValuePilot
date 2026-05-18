"""MVP4-03b dashboard endpoint persisted-score integration tests.

When `use_persisted_scores=true`, the existing
`build_oracles_lens_dashboard` must serve scores from the
`oracles_lens_signals` table written by MVP4-03 instead of the
in-memory plan-§7.2-divergent compute. When the flag is absent or
false, the default in-memory behavior must be preserved unchanged.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    ParseRun13F,
)
from app.models.oracles_lens import OraclesLensSignal
from app.models.stocks import Stock
from app.services.oracles_lens.constants import SCORE_VERSION
from app.services.oracles_lens.dashboard import build_oracles_lens_dashboard
from app.services.oracles_lens.signal_weighted_score import (
    compute_signal_weighted_scores,
)


_CIK_SEQ = count(9993300000)
_ACC_SEQ = count(950001)
_STOCK_SEQ = count(93001)


_QUARTER = "2026-Q1"
_QUARTER_END = date(2026, 3, 31)


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv4-03b Mgr {cik}",
        legal_name=f"Mv4-03b Mgr {cik}",
        edgar_legal_name=f"Mv4-03b Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type="long_term_fundamental",
        is_superinvestor=True,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session) -> Stock:
    seq = next(_STOCK_SEQ)
    stock = Stock(
        ticker=f"D3{seq:05d}"[-10:],
        exchange="NYSE",
        company_name=f"D3Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(db_session, manager: InstitutionManager) -> Filing13F:
    accession = f"00099330-26-{next(_ACC_SEQ):06d}"
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=_QUARTER_END,
        filed_at=_QUARTER_END,
        filing_date=_QUARTER_END,
        accepted_at=datetime(_QUARTER_END.year, _QUARTER_END.month, _QUARTER_END.day, 17, tzinfo=timezone.utc),
        form_type="13F-HR",
        report_type="holdings_report",
        coverage_completeness="complete",
        coverage_type="normal",
        quarter_end_date=_QUARTER_END,
        report_quarter=_QUARTER,
        official_filing_deadline=date(2026, 5, 15),
        parse_status="succeeded",
        is_active_for_manager_period=True,
        is_latest_for_period=True,
        amendment_status="no_amendments_seen",
        computed_total_value_thousands=1_000_000,
        reported_total_value_thousands=1_000_000,
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
    stock: Stock,
    *,
    value_thousands: int = 50_000,
    shares: int = 1000,
) -> Holding13F:
    pr = _current_parse_run(db_session, filing)
    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=pr.id,
        manager_id=filing.manager_id,
        accession_number=filing.accession_number,
        report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date,
        row_fingerprint=f"{filing.accession_number}-{stock.id}",
        holding_row_fingerprint=f"{filing.accession_number}-{stock.id}",
        cusip=f"{stock.id:09d}",
        issuer_name=f"Issuer {stock.id}",
        name_of_issuer=f"Issuer {stock.id}",
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
        stock_id=stock.id,
        cusip_mapping_status="linked",
        source_row_index=0,
    )
    db_session.add(holding)
    db_session.flush()
    pr.holdings_count = 1
    return holding


def _three_holder_stock(db_session) -> tuple[Stock, list[InstitutionManager]]:
    stock = _stock(db_session)
    managers = []
    for _ in range(3):
        mgr = _manager(db_session)
        filing = _filing(db_session, mgr)
        _holding(db_session, filing, stock, value_thousands=50_000)
        managers.append(mgr)
    return stock, managers


# ===========================================================================
# Default mode: behavior unchanged
# ===========================================================================


def test_default_mode_uses_in_memory_compute(db_session):
    stock, _ = _three_holder_stock(db_session)
    # Backfill persisted scores so the row exists with a known
    # different value (we'll show default mode ignores it).
    compute_signal_weighted_scores(db_session, quarter=_QUARTER)
    persisted = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )
    persisted_score = persisted.signal_weighted_consensus_score

    payload = build_oracles_lens_dashboard(db_session, period=_QUARTER)

    # Find our stock in the dashboard items.
    item = next((i for i in payload["items"] if i["stock_id"] == stock.id), None)
    assert item is not None, "dashboard must return our 3-holder stock by default"
    # In default mode, score_source should NOT be 'persisted'.
    assert item.get("score_source") != "persisted"
    # The in-memory formula differs from MVP4-03's plan §7.2, so the
    # rendered score does not equal the persisted value.
    in_memory_score = item["signal_weighted_consensus_score"]
    # Both are floats / strings — compare numerically with tolerance
    # to confirm divergence (this asserts the formulas are different,
    # which is the whole reason MVP4-03b exists).
    assert abs(float(in_memory_score) - float(persisted_score)) > 0


# ===========================================================================
# Persisted mode
# ===========================================================================


def test_persisted_mode_returns_score_from_table(db_session):
    stock, _ = _three_holder_stock(db_session)
    compute_signal_weighted_scores(db_session, quarter=_QUARTER)
    persisted = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )

    payload = build_oracles_lens_dashboard(
        db_session, period=_QUARTER, use_persisted_scores=True,
    )

    item = next((i for i in payload["items"] if i["stock_id"] == stock.id), None)
    assert item is not None, "persisted mode must surface stocks with persisted rows"
    assert item["score_source"] == "persisted"
    assert float(item["signal_weighted_consensus_score"]) == float(
        persisted.signal_weighted_consensus_score
    )
    assert item["score_confidence"] == persisted.score_confidence


def test_persisted_mode_excludes_stocks_without_persisted_row(db_session):
    """A stock that meets the holder threshold but has no row in
    oracles_lens_signals must be excluded in persisted mode — no
    in-memory fallback (would mix two formulas).
    """
    stock_with, _ = _three_holder_stock(db_session)
    stock_without, _ = _three_holder_stock(db_session)
    # Only backfill stock_with's score by computing with a tight
    # min_holders filter — but compute_signal_weighted_scores will
    # write rows for BOTH eligible stocks. To get one stock without a
    # row, delete the persisted row for stock_without after compute.
    compute_signal_weighted_scores(db_session, quarter=_QUARTER)
    db_session.query(OraclesLensSignal).filter(
        OraclesLensSignal.stock_id == stock_without.id
    ).delete()
    db_session.flush()

    payload = build_oracles_lens_dashboard(
        db_session, period=_QUARTER, use_persisted_scores=True,
    )
    stock_ids = {i["stock_id"] for i in payload["items"]}
    assert stock_with.id in stock_ids
    assert stock_without.id not in stock_ids


def test_persisted_mode_empty_quarter_returns_empty_items(db_session):
    """No persisted rows for the quarter → empty list, not 500, not
    in-memory fallback.
    """
    # No backfill; no oracles_lens_signals rows for an arbitrary
    # future quarter.
    payload = build_oracles_lens_dashboard(
        db_session, period="2099-Q4", use_persisted_scores=True,
    )
    assert payload["items"] == []


def test_persisted_mode_respects_score_version(db_session):
    """Rows with a different score_version are not visible to the
    default-version persisted query.
    """
    stock, _ = _three_holder_stock(db_session)
    # Insert a row under a non-default score_version only; the
    # default version has no row for this stock.
    db_session.add(
        OraclesLensSignal(
            stock_id=stock.id,
            report_quarter=_QUARTER,
            quarter_end_date=_QUARTER_END,
            score_version="v999.0",
            raw_consensus_count=3,
            signal_weighted_consensus_score=42,
            score_confidence="high_confidence",
            computed_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    payload = build_oracles_lens_dashboard(
        db_session, period=_QUARTER, use_persisted_scores=True,
    )
    # The default SCORE_VERSION has no row → stock excluded.
    assert all(i["stock_id"] != stock.id for i in payload["items"])


def test_persisted_mode_exposes_persisted_score_count_in_coverage(db_session):
    stock, _ = _three_holder_stock(db_session)
    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    payload = build_oracles_lens_dashboard(
        db_session, period=_QUARTER, use_persisted_scores=True,
    )
    assert "persisted_score_count" in payload["coverage"]
    assert payload["coverage"]["persisted_score_count"] >= 1
