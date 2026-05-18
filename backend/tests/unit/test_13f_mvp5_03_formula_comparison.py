"""MVP5-03 Phase 1 formula-comparison utility tests.

Two layers:

1. Pure-function tests for ``compute_formula_comparison`` — divergence
   detection logic (TOP10_RANK_SWAP / MAGNITUDE_DIFF_25_PCT) without
   any DB dependency.
2. Admin-endpoint integration test that seeds an
   ``oracles_lens_signals`` row plus the underlying holdings the
   legacy formula needs, calls the endpoint, and asserts the
   response shape.
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
    ParseRun13F,
)
from app.models.oracles_lens import OraclesLensSignal
from app.models.stocks import Stock
from app.services.oracles_lens.formula_comparison import (
    DIVERGENCE_MAGNITUDE_25_PCT,
    DIVERGENCE_TOP10_RANK_SWAP,
    compute_formula_comparison,
)


# ===========================================================================
# Pure-function divergence detection
# ===========================================================================


def test_no_divergence_when_scores_match_exactly():
    legacy = {1: 1.00, 2: 0.50, 3: 0.25}
    persisted = {1: 1.00, 2: 0.50, 3: 0.25}
    report = compute_formula_comparison(legacy, persisted)
    assert report["total_stocks_compared"] == 3
    assert report["top10_swap_count"] == 0
    assert report["magnitude_diff_count"] == 0
    for item in report["items"]:
        assert item["divergence_flags"] == []


def test_magnitude_25pct_threshold_inclusive_above_exclusive_below():
    # legacy=1.0, persisted=0.74 → diff = 0.26 / 1.0 = 0.26 > 0.25 → FLAG
    # legacy=1.0, persisted=0.75 → diff = 0.25 / 1.0 = 0.25 → exactly at
    #                              threshold; spec says "> 0.25" so NO flag
    # legacy=1.0, persisted=0.76 → diff = 0.24 / 1.0 = 0.24 → NO flag
    legacy = {10: 1.0, 11: 1.0, 12: 1.0}
    persisted = {10: 0.74, 11: 0.75, 12: 0.76}
    report = compute_formula_comparison(legacy, persisted)
    flags_by_stock = {it["stock_id"]: it["divergence_flags"] for it in report["items"]}
    assert DIVERGENCE_MAGNITUDE_25_PCT in flags_by_stock[10]
    assert DIVERGENCE_MAGNITUDE_25_PCT not in flags_by_stock[11]
    assert DIVERGENCE_MAGNITUDE_25_PCT not in flags_by_stock[12]
    assert report["magnitude_diff_count"] == 1


def test_zero_scores_do_not_trigger_magnitude_flag():
    """Division-by-zero guard: both scores zero → no flag."""
    legacy = {1: 0.0}
    persisted = {1: 0.0}
    report = compute_formula_comparison(legacy, persisted)
    assert report["items"][0]["divergence_flags"] == []


def test_top10_rank_swap_detected_when_top10_in_one_below20_in_other():
    """Stock #1 ranks 5 under legacy but 25 under persisted → SWAP.
    Stock #2 ranks 12 under both → no swap. Stock #3 ranks 1 under
    both → no swap (top 10 on both)."""
    legacy: dict[int, float] = {}
    persisted: dict[int, float] = {}
    # 30 stocks total. Place stock #1 at rank 5 in legacy, rank 25 in
    # persisted. #2 at rank 12 in both. #3 at rank 1 in both.
    for stock_id in range(1, 31):
        legacy[stock_id] = 1.0 - stock_id * 0.01  # rank 1 → 0.99, rank 30 → 0.70
        persisted[stock_id] = 1.0 - stock_id * 0.01
    # Override #1 to flip ranks.
    legacy[1] = 0.96  # ties for rank 5 in legacy
    persisted[1] = 0.76  # ties for rank 25 in persisted

    report = compute_formula_comparison(legacy, persisted)
    flags_by_stock = {it["stock_id"]: it["divergence_flags"] for it in report["items"]}
    assert DIVERGENCE_TOP10_RANK_SWAP in flags_by_stock[1]
    assert DIVERGENCE_TOP10_RANK_SWAP not in flags_by_stock[2]
    assert DIVERGENCE_TOP10_RANK_SWAP not in flags_by_stock[3]


def test_unintersected_stocks_counted_separately():
    """Stocks present only in legacy or only in persisted go into the
    counters, not the items array. The items array is the
    intersection."""
    legacy = {1: 0.5, 2: 0.5, 3: 0.5}
    persisted = {2: 0.5, 3: 0.5, 4: 0.5}
    report = compute_formula_comparison(legacy, persisted)
    assert report["total_stocks_compared"] == 2  # stocks 2 and 3
    stock_ids = {it["stock_id"] for it in report["items"]}
    assert stock_ids == {2, 3}
    assert report["legacy_only_count"] == 1  # stock 1
    assert report["persisted_only_count"] == 1  # stock 4


def test_score_delta_is_persisted_minus_legacy():
    legacy = {1: 0.5}
    persisted = {1: 0.8}
    report = compute_formula_comparison(legacy, persisted)
    item = report["items"][0]
    assert item["legacy_score"] == 0.5
    assert item["persisted_score"] == 0.8
    assert abs(item["score_delta"] - 0.3) < 1e-9


# ===========================================================================
# Admin endpoint integration
# ===========================================================================


_CIK_SEQ = count(9970300000)
_ACC_SEQ = count(730001)
_STOCK_SEQ = count(73001)


_QUARTER = "2026-Q1"
_QUARTER_END = date(2026, 3, 31)


def _manager(db_session, *, superinvestor: bool = True) -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv5-03 Mgr {cik}",
        legal_name=f"Mv5-03 Mgr {cik}",
        edgar_legal_name=f"Mv5-03 Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type="long_term_fundamental",
        is_superinvestor=superinvestor,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session) -> Stock:
    seq = next(_STOCK_SEQ)
    stock = Stock(
        ticker=f"M53{seq:04d}"[-10:],
        exchange="NYSE",
        company_name=f"M53Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(db_session, manager: InstitutionManager) -> Filing13F:
    accession = f"00099703-26-{next(_ACC_SEQ):06d}"
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


def _holding(db_session, filing: Filing13F, stock: Stock) -> Holding13F:
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
        value_thousands=50_000,
        value_raw="50000000",
        value_unit_raw="dollars",
        value_parse_rule="schema_dollars",
        value_usd=50_000_000,
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


def test_endpoint_requires_admin(client, user_factory, auth_headers):
    non_admin = user_factory(email="mvp5-03-non-admin@example.com", role="user")
    response = client.get(
        "/api/v1/admin/13f/oracles-lens/formula-comparison",
        headers=auth_headers(non_admin),
    )
    assert response.status_code in (401, 403)


def test_endpoint_returns_comparison_payload_shape(
    client, db_session, user_factory, auth_headers
):
    """Seed one stock with both a legacy-computable holdings shape and
    a persisted score row, then call the endpoint. The response should
    include the stock with both scores populated."""
    admin = user_factory(email="mvp5-03-admin@example.com", role="admin")

    stock = _stock(db_session)
    # 3 superinvestor holders so the legacy dashboard path scores
    # the stock (the default ``superinvestor_only=True`` filters
    # everyone else out).
    for _ in range(3):
        mgr = _manager(db_session, superinvestor=True)
        _holding(db_session, _filing(db_session, mgr), stock)

    # Seed a persisted score for the same stock + quarter.
    seeded_persisted_score = Decimal("0.4567")
    signal = OraclesLensSignal(
        stock_id=stock.id,
        report_quarter=_QUARTER,
        quarter_end_date=_QUARTER_END,
        score_version="v1.0",
        signal_weighted_consensus_score=seeded_persisted_score,
        raw_consensus_count=3,
        score_confidence="high_confidence",
        caution_flag_codes=[],
        score_explanation={},
        computed_at=datetime.now(timezone.utc),
    )
    db_session.add(signal)
    db_session.flush()

    response = client.get(
        f"/api/v1/admin/13f/oracles-lens/formula-comparison?quarter={_QUARTER}",
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["quarter"] == _QUARTER
    assert payload["score_version"] == "v1.0"
    assert payload["total_stocks_compared"] >= 1
    assert "items" in payload
    assert "top10_swap_count" in payload
    assert "magnitude_diff_count" in payload

    match = next(
        (it for it in payload["items"] if it["stock_id"] == stock.id), None,
    )
    assert match is not None, (
        f"seeded stock {stock.id} missing from comparison payload"
    )
    assert match["persisted_score"] == pytest.approx(float(seeded_persisted_score))
    assert isinstance(match["legacy_score"], (int, float))
    assert isinstance(match["score_delta"], (int, float))
    assert "legacy_rank" in match
    assert "persisted_rank" in match
    assert isinstance(match["divergence_flags"], list)
