"""MVP7-01 backend: ``POST /api/v1/stocks/13f-snapshots`` batch endpoint.

Covers the four V1 signals (Conviction percentile, Δ Holders,
Distinctiveness tier, Caveat severity), the three unavailable
branches, percentile math, and the period_filing_deadline derivation.

Test fixture is intentionally lean — direct control over per-stock
manager counts + actions, instead of reusing the 75-manager
dashboard fixture from ``test_oracles_lens.py``.

Note on manager_type: the dashboard's ``_apply_manager_signal_profiles``
**overrides** ``InstitutionManager.manager_type`` at runtime based on
behavior heuristics (concentration / holding-period / turnover). The
``crowded`` tier and ``unknown_manager_type_heavy`` caveat both require
``coverage<0.5`` end-to-end, which the behavior derivation reliably
prevents on simple fixtures. Those edges are unit-tested against the
helper functions directly (see ``test_distinctiveness_tier_*``,
``test_caveat_severity_aggregation_*``).
"""

from __future__ import annotations

from datetime import date

from app.api.v1.endpoints.stocks_13f import (
    _caveat_severity_from_flags,
    _distinctiveness_tier,
    _period_filing_deadline,
)
from app.models.institutions import Filing13F, Holding13F, InstitutionManager
from app.models.stocks import Stock


def _manager(
    db_session,
    name: str,
    *,
    cik: str,
    manager_type: str = "long_term_fundamental",
    superinvestor: bool = True,
) -> InstitutionManager:
    manager = InstitutionManager(
        cik=cik,
        legal_name=name,
        display_name=name,
        name_normalized=name.lower(),
        match_status="confirmed",
        is_superinvestor=superinvestor,
        manager_type=manager_type,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session, ticker: str, name: str) -> Stock:
    stock = Stock(ticker=ticker, exchange="NYSE", company_name=name, is_active=True)
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(
    db_session,
    manager: InstitutionManager,
    *,
    accession: str,
    period: date,
    total_value: int = 100_000,
) -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        period_of_report=period,
        filed_at=period,
        form_type="13F-HR",
        is_latest_for_period=True,
        reported_total_value_thousands=total_value,
        computed_total_value_thousands=total_value,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _holding(
    db_session,
    filing: Filing13F,
    stock: Stock,
    *,
    cusip: str,
    shares: int,
    value_thousands: int,
) -> Holding13F:
    holding = Holding13F(
        filing_id=filing.id,
        row_fingerprint=f"{filing.accession_no}-{cusip}-{stock.ticker}",
        cusip=cusip,
        issuer_name=stock.company_name,
        title_of_class="COM",
        value_thousands=value_thousands,
        shares=shares,
        share_type="SH",
        stock_id=stock.id,
    )
    db_session.add(holding)
    db_session.flush()
    return holding


def _seed_snapshot_fixture(db_session) -> dict[str, Stock | int]:
    """Build a focused fixture with:

    - ``target_full``: a stock with 5 ranked managers in Q4 (and Q3 history
      for ``add`` / ``new`` / ``reduce`` action variety).
    - ``target_partial``: a stock with 1 holding in Q4 (below_min_holders).
    - ``target_empty``: a stock with no 13F holdings at all.
    - ``target_distinctive``: a stock with 4 holders all
      ``manager_type=long_term_fundamental`` (high coverage, small consensus).
    - ``target_crowded``: a stock with 22 holders, mix of unknown +
      high_turnover (low coverage, large consensus).
    """
    target_full = _stock(db_session, "FULL", "Full Coverage Inc")
    target_partial = _stock(db_session, "PART", "Partial Holder Inc")
    target_empty = _stock(db_session, "EMPT", "Empty Coverage Inc")
    target_distinctive = _stock(db_session, "DIST", "Distinctive Few Inc")
    target_crowded = _stock(db_session, "CROW", "Crowded Many Inc")

    q3 = date(2031, 9, 30)
    q4 = date(2031, 12, 31)

    # target_full: 5 managers, mix of actions
    full_managers = [
        _manager(db_session, f"Full Fund {i}", cik=f"00111{i:04d}")
        for i in range(5)
    ]
    for index, manager in enumerate(full_managers):
        new_filing = _filing(
            db_session, manager, accession=f"full-new-{index}", period=q4,
        )
        # Build Q3 holdings only for 2 of 5 managers so 3 of 5 are "new" in Q4.
        if index < 2:
            old_filing = _filing(
                db_session, manager, accession=f"full-old-{index}", period=q3,
            )
            # Manager 0: reducer (shares go DOWN q3 -> q4)
            # Manager 1: adder (shares go UP q3 -> q4)
            old_shares = 1500 if index == 0 else 1000
            _holding(
                db_session,
                old_filing,
                target_full,
                cusip=f"FULL0{index}001",
                shares=old_shares,
                value_thousands=10_000,
            )
        new_shares = 1000 if index == 0 else 1500
        _holding(
            db_session,
            new_filing,
            target_full,
            cusip=f"FULL0{index}001",
            shares=new_shares,
            value_thousands=11_000,
        )

    # target_partial: 1 manager (below min_holders=3)
    partial_mgr = _manager(db_session, "Partial Mgr", cik="0011000001")
    partial_filing = _filing(
        db_session, partial_mgr, accession="part-0", period=q4,
    )
    _holding(
        db_session,
        partial_filing,
        target_partial,
        cusip="PART00001",
        shares=500,
        value_thousands=5_000,
    )

    # target_empty: no holdings at all.

    # target_distinctive: 4 long_term_fundamental managers (small consensus,
    # high coverage).
    dist_managers = [
        _manager(db_session, f"Dist Fund {i}", cik=f"00222{i:04d}",
                 manager_type="long_term_fundamental")
        for i in range(4)
    ]
    for index, manager in enumerate(dist_managers):
        f = _filing(db_session, manager, accession=f"dist-{index}", period=q4)
        _holding(
            db_session, f, target_distinctive,
            cusip=f"DIST0{index}001",
            shares=1000 + index * 100,
            value_thousands=12_000,
        )

    # target_crowded: 22 managers, mostly unknown + a few high_turnover.
    crowd_managers = [
        _manager(
            db_session,
            f"Crowd Fund {i}",
            cik=f"00333{i:04d}",
            manager_type=(
                "unknown" if i < 18
                else "long_term_fundamental"  # only 4 typed of 22
            ),
        )
        for i in range(22)
    ]
    for index, manager in enumerate(crowd_managers):
        f = _filing(db_session, manager, accession=f"crow-{index}", period=q4)
        _holding(
            db_session, f, target_crowded,
            cusip=f"CROW0{index:02d}1",
            shares=900 + index * 50,
            value_thousands=9_000,
        )

    db_session.commit()
    return {
        "target_full_id": target_full.id,
        "target_partial_id": target_partial.id,
        "target_empty_id": target_empty.id,
        "target_distinctive_id": target_distinctive.id,
        "target_crowded_id": target_crowded.id,
    }


# ----- Tests -------------------------------------------------------------


def test_snapshot_available_true_for_qualifying_stock(client, db_session):
    fixture = _seed_snapshot_fixture(db_session)
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={"stock_ids": [fixture["target_full_id"]], "period": "2031-Q4"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["period"] == "2031-Q4"
    assert payload["period_filing_deadline"] == "2032-02-14"
    assert payload["universe_size"] >= 1

    snap = payload["snapshots"][0]
    assert snap["stock_id"] == fixture["target_full_id"]
    assert snap["available"] is True
    assert isinstance(snap["conviction_score"], (int, float))
    assert 0.0 <= snap["conviction_percentile"] <= 1.0
    assert snap["consensus_count"] == 5
    assert snap["caveat_severity"] in {"ok", "caution", "high-caution"}


def test_snapshot_no_holders_unavailable_reason(client, db_session):
    fixture = _seed_snapshot_fixture(db_session)
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={"stock_ids": [fixture["target_empty_id"]], "period": "2031-Q4"},
    )
    assert response.status_code == 200
    snap = response.json()["snapshots"][0]
    assert snap["available"] is False
    assert snap["unavailable_reason"] == "no_holders"


def test_snapshot_below_min_holders_unavailable_reason(client, db_session):
    fixture = _seed_snapshot_fixture(db_session)
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={"stock_ids": [fixture["target_partial_id"]], "period": "2031-Q4"},
    )
    assert response.status_code == 200
    snap = response.json()["snapshots"][0]
    assert snap["available"] is False
    assert snap["unavailable_reason"] == "below_min_holders"


def test_snapshot_delta_holders_signed_integer(client, db_session):
    fixture = _seed_snapshot_fixture(db_session)
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={"stock_ids": [fixture["target_full_id"]], "period": "2031-Q4"},
    )
    snap = response.json()["snapshots"][0]
    # Fixture: 3 managers are "new" in Q4 (no Q3 history), 1 is "add"
    # (shares went up), 1 is "reduce" (shares went down).
    # adders_count = new + add = 4; reducers_count = reduce = 1; delta = 3.
    assert snap["adders_count"] == 4
    assert snap["reducers_count"] == 1
    assert snap["delta_holders"] == 3


def test_snapshot_distinctive_tier(client, db_session):
    fixture = _seed_snapshot_fixture(db_session)
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={"stock_ids": [fixture["target_distinctive_id"]], "period": "2031-Q4"},
    )
    snap = response.json()["snapshots"][0]
    assert snap["available"] is True
    # 4 holders all typed long_term_fundamental ->
    # consensus_count=4 <= 8, coverage=1.0 >= 0.7 -> distinctive.
    assert snap["consensus_count"] == 4
    assert snap["distinctiveness_tier"] == "distinctive"


def test_snapshot_caveat_severity_high_caution_on_warning_flag(client, db_session):
    fixture = _seed_snapshot_fixture(db_session)
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={"stock_ids": [fixture["target_crowded_id"]], "period": "2031-Q4"},
    )
    snap = response.json()["snapshots"][0]
    # target_crowded has 22 managers all without Q3 history -> turnover_proxy
    # is high for all -> ``high_turnover_holders`` flag fires at
    # severity="warning", which aggregates to ``high-caution``.
    assert snap["caveat_severity"] == "high-caution"
    assert len(snap["caveat_codes"]) > 0


# ----- Helper unit tests ---------------------------------------------------
#
# The ``crowded`` and ``unknown_manager_type_heavy`` paths require
# ``manager_signal_quality_coverage < 0.5``, which the dashboard's
# behavior-derivation classifier reliably prevents on simple fixtures
# (it tags managers as ``value_concentrated`` whenever they hold one
# stock at weight ~1.0). Unit-test the helpers directly to cover those
# branches without forcing the integration fixture into pathological
# shapes.


def test_distinctiveness_tier_distinctive_threshold():
    assert _distinctiveness_tier(consensus_count=8, coverage=0.7) == "distinctive"
    assert _distinctiveness_tier(consensus_count=4, coverage=1.0) == "distinctive"


def test_distinctiveness_tier_crowded_threshold():
    assert _distinctiveness_tier(consensus_count=20, coverage=0.49) == "crowded"
    assert _distinctiveness_tier(consensus_count=30, coverage=0.1) == "crowded"


def test_distinctiveness_tier_mixed_fallback():
    # Just below distinctive coverage threshold.
    assert _distinctiveness_tier(consensus_count=5, coverage=0.69) == "mixed"
    # Just below crowded consensus threshold.
    assert _distinctiveness_tier(consensus_count=19, coverage=0.4) == "mixed"
    # Distinctive consensus but crowded coverage — falls through to mixed.
    assert _distinctiveness_tier(consensus_count=6, coverage=0.4) == "mixed"


def test_caveat_severity_aggregation_ok_on_empty():
    assert _caveat_severity_from_flags([]) == "ok"


def test_caveat_severity_aggregation_caution_on_info_only():
    flags = [{"key": "short_holding_streak", "severity": "info"}]
    assert _caveat_severity_from_flags(flags) == "caution"


def test_caveat_severity_aggregation_high_caution_on_any_warning():
    flags = [
        {"key": "short_holding_streak", "severity": "info"},
        {"key": "unknown_manager_type_heavy", "severity": "warning"},
    ]
    assert _caveat_severity_from_flags(flags) == "high-caution"


def test_period_filing_deadline_is_period_end_plus_45_days():
    assert _period_filing_deadline("2031-12-31") == "2032-02-14"
    assert _period_filing_deadline("2025-09-30") == "2025-11-14"


def test_period_filing_deadline_handles_invalid_input():
    assert _period_filing_deadline(None) is None
    assert _period_filing_deadline("not-a-date") is None


def test_snapshot_percentile_top_ranked_is_one(client, db_session):
    fixture = _seed_snapshot_fixture(db_session)
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={
            "stock_ids": [
                fixture["target_full_id"],
                fixture["target_distinctive_id"],
                fixture["target_crowded_id"],
            ],
            "period": "2031-Q4",
        },
    )
    payload = response.json()
    available = [s for s in payload["snapshots"] if s["available"]]
    assert available
    top = max(available, key=lambda s: s["conviction_score"])
    assert top["conviction_percentile"] == 1.0


def test_snapshot_mixed_batch_preserves_input_order(client, db_session):
    fixture = _seed_snapshot_fixture(db_session)
    requested = [
        fixture["target_full_id"],
        fixture["target_empty_id"],
        fixture["target_partial_id"],
        fixture["target_distinctive_id"],
    ]
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={"stock_ids": requested, "period": "2031-Q4"},
    )
    payload = response.json()
    assert [s["stock_id"] for s in payload["snapshots"]] == requested
    reasons = {s["stock_id"]: s for s in payload["snapshots"]}
    assert reasons[fixture["target_full_id"]]["available"] is True
    assert reasons[fixture["target_empty_id"]]["unavailable_reason"] == "no_holders"
    assert reasons[fixture["target_partial_id"]]["unavailable_reason"] == "below_min_holders"
    assert reasons[fixture["target_distinctive_id"]]["available"] is True


def test_snapshot_specific_period_override(client, db_session):
    fixture = _seed_snapshot_fixture(db_session)
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={"stock_ids": [fixture["target_full_id"]], "period": "2031-Q4"},
    )
    payload = response.json()
    assert payload["period"] == "2031-Q4"
    assert payload["period_filing_deadline"] == "2032-02-14"


def test_snapshot_no_qualifying_period_returns_universe_size_zero(client, db_session):
    """If the requested period has zero qualifying ranked stocks, every
    requested stock returns ``no_qualifying_period`` and universe_size == 0.
    Use a far-future period to bypass any pre-existing DB data."""
    stock = _stock(db_session, "VOID", "Void Inc")
    db_session.commit()
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={"stock_ids": [stock.id], "period": "2050-Q1"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["universe_size"] == 0
    snap = payload["snapshots"][0]
    assert snap["available"] is False
    assert snap["unavailable_reason"] == "no_qualifying_period"


def test_snapshot_rejects_empty_stock_ids(client, db_session):
    response = client.post(
        "/api/v1/stocks/13f-snapshots",
        json={"stock_ids": [], "period": "2031-Q4"},
    )
    assert response.status_code == 422  # pydantic min_length=1
