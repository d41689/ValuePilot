"""MVP4-07b admin priority surface tests."""
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
from app.services.oracles_lens.signal_weighted_score import (
    compute_signal_weighted_scores,
)
from app.services.oracles_lens.unknown_manager_priority import (
    build_unknown_manager_priority,
)


_CIK_SEQ = count(9997700000)
_ACC_SEQ = count(990001)
_STOCK_SEQ = count(97001)


_QUARTER = "2026-Q1"
_QUARTER_END = date(2026, 3, 31)

_CONFIDENCE_RANK = {
    "low_confidence": 0,
    "medium_confidence": 1,
    "high_confidence": 2,
    "unavailable": -1,
}


def _manager(db_session, *, manager_type: str) -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv4-07b Mgr {cik}",
        legal_name=f"Mv4-07b Mgr {cik}",
        edgar_legal_name=f"Mv4-07b Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type=manager_type,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session) -> Stock:
    seq = next(_STOCK_SEQ)
    stock = Stock(
        ticker=f"U7{seq:05d}"[-10:],
        exchange="NYSE",
        company_name=f"U7Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(
    db_session, manager: InstitutionManager, *, coverage_completeness: str = "complete",
) -> Filing13F:
    accession = f"00099770-26-{next(_ACC_SEQ):06d}"
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
        coverage_completeness=coverage_completeness,
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
    pr = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="test",
        fingerprint_version="v1",
        status="succeeded",
        holdings_count=0,
        is_current=True,
    )
    db_session.add(pr)
    db_session.flush()
    filing._test_parse_run = pr  # type: ignore[attr-defined]
    return filing


def _holding(db_session, filing: Filing13F, stock: Stock, *, value_thousands: int = 50_000) -> Holding13F:
    pr: ParseRun13F = filing._test_parse_run  # type: ignore[attr-defined]
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
        shares=1000,
        ssh_prnamt=1000,
        share_type="SH",
        ssh_prnamt_type="SH",
        investment_discretion="SOLE",
        holding_attribution_status="direct",
        voting_sole=1000,
        voting_shared=0,
        voting_none=0,
        stock_id=stock.id,
        cusip_mapping_status="linked",
        source_row_index=0,
    )
    db_session.add(holding)
    db_session.flush()
    return holding


def test_no_persisted_scores_returns_empty(db_session):
    """Before any backfill: no signals exist → quarter null, items
    empty, no crash."""
    payload = build_unknown_manager_priority(db_session)
    assert payload["quarter"] is None
    assert payload["items"] == []


def test_unknown_manager_appears_when_they_hold_a_scored_stock(db_session):
    stock = _stock(db_session)
    unknown_mgr = _manager(db_session, manager_type="unknown")
    _holding(db_session, _filing(db_session, unknown_mgr), stock)
    # Add 2 more managers (with a non-unknown type) so the stock is
    # eligible for scoring (>= 3 holders).
    for _ in range(2):
        mgr = _manager(db_session, manager_type="long_term_fundamental")
        _holding(db_session, _filing(db_session, mgr), stock)
    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    payload = build_unknown_manager_priority(db_session)
    assert payload["quarter"] == _QUARTER
    manager_ids = [item["manager_id"] for item in payload["items"]]
    assert unknown_mgr.id in manager_ids


def test_non_unknown_manager_excluded(db_session):
    """Typed managers must not appear in the priority list — they
    don't drag score_confidence."""
    stock = _stock(db_session)
    typed_mgr = _manager(db_session, manager_type="long_term_fundamental")
    _holding(db_session, _filing(db_session, typed_mgr), stock)
    for _ in range(2):
        mgr = _manager(db_session, manager_type="long_term_fundamental")
        _holding(db_session, _filing(db_session, mgr), stock)
    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    payload = build_unknown_manager_priority(db_session)
    manager_ids = [item["manager_id"] for item in payload["items"]]
    assert typed_mgr.id not in manager_ids


def test_ordering_by_affected_signal_count_desc(db_session):
    """A manager who appears on 2 scored stocks ranks above one who
    only appears on 1."""
    stock_a = _stock(db_session)
    stock_b = _stock(db_session)

    # mgr_two_signals appears on both stocks
    mgr_two = _manager(db_session, manager_type="unknown")
    mgr_two_filing = _filing(db_session, mgr_two)
    _holding(db_session, mgr_two_filing, stock_a)
    _holding(db_session, mgr_two_filing, stock_b)

    # mgr_one_signal appears on only stock_a
    mgr_one = _manager(db_session, manager_type="unknown")
    _holding(db_session, _filing(db_session, mgr_one), stock_a)

    # Pad both stocks to 3 holders so they get scored.
    for _ in range(2):
        mgr = _manager(db_session, manager_type="long_term_fundamental")
        f = _filing(db_session, mgr)
        _holding(db_session, f, stock_a)
        _holding(db_session, f, stock_b)
    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    payload = build_unknown_manager_priority(db_session)
    items = payload["items"]
    # Both unknown managers should appear; the two-signal one first.
    by_manager = {item["manager_id"]: item for item in items}
    assert by_manager[mgr_two.id]["affected_signal_count"] == 2
    assert by_manager[mgr_one.id]["affected_signal_count"] == 1
    # mgr_two appears before mgr_one in the ordered list.
    mgr_two_index = next(i for i, x in enumerate(items) if x["manager_id"] == mgr_two.id)
    mgr_one_index = next(i for i, x in enumerate(items) if x["manager_id"] == mgr_one.id)
    assert mgr_two_index < mgr_one_index


def test_worst_score_confidence_observed_captures_lowest_tier(db_session):
    """When an unknown manager holds two scored stocks with
    different score_confidence values, the worst tier wins."""
    stock_high = _stock(db_session)
    stock_low = _stock(db_session)

    # Unknown manager appears on both stocks via one filing.
    unknown_mgr = _manager(db_session, manager_type="unknown")
    unknown_filing = _filing(db_session, unknown_mgr)
    _holding(db_session, unknown_filing, stock_high)
    _holding(db_session, unknown_filing, stock_low)

    # stock_high: pad with two clean (complete-coverage) holders.
    for _ in range(2):
        mgr = _manager(db_session, manager_type="long_term_fundamental")
        _holding(db_session, _filing(db_session, mgr), stock_high)

    # stock_low: pad with two partial-coverage holders so the
    # stock-level score_confidence gets demoted by MVP4-05.
    for _ in range(2):
        mgr = _manager(db_session, manager_type="long_term_fundamental")
        _holding(
            db_session,
            _filing(db_session, mgr, coverage_completeness="partial"),
            stock_low,
        )
    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    # Sanity-check: the two signals should have different tiers.
    signals = {
        row.stock_id: row.score_confidence
        for row in db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id.in_([stock_high.id, stock_low.id]))
        .filter(OraclesLensSignal.report_quarter == _QUARTER)
        .all()
    }
    assert (
        _CONFIDENCE_RANK[signals[stock_low.id]]
        < _CONFIDENCE_RANK[signals[stock_high.id]]
    ), f"setup invariant broken — signals={signals!r}"

    payload = build_unknown_manager_priority(db_session)
    by_manager = {item["manager_id"]: item for item in payload["items"]}
    assert (
        by_manager[unknown_mgr.id]["worst_score_confidence_observed"]
        == signals[stock_low.id]
    )


def test_endpoint_requires_admin(client, user_factory, auth_headers):
    """Non-admin caller is rejected before the service runs."""
    non_admin = user_factory(email="07b-non-admin@example.com", role="user")
    response = client.get(
        "/api/v1/admin/13f/oracles-lens/unknown-manager-priority",
        headers=auth_headers(non_admin),
    )
    assert response.status_code in (401, 403)


def test_endpoint_returns_payload_shape(client, db_session, user_factory, auth_headers):
    admin = user_factory(email="07b-admin@example.com", role="admin")
    stock = _stock(db_session)
    unknown_mgr = _manager(db_session, manager_type="unknown")
    _holding(db_session, _filing(db_session, unknown_mgr), stock)
    for _ in range(2):
        mgr = _manager(db_session, manager_type="long_term_fundamental")
        _holding(db_session, _filing(db_session, mgr), stock)
    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    response = client.get(
        "/api/v1/admin/13f/oracles-lens/unknown-manager-priority",
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["quarter"] == _QUARTER
    assert payload["score_version"] == SCORE_VERSION
    assert isinstance(payload["items"], list)
    if payload["items"]:
        first = payload["items"][0]
        assert {
            "manager_id",
            "canonical_name",
            "affected_signal_count",
            "worst_score_confidence_observed",
        }.issubset(first.keys())
