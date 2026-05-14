"""MVP7-05 backend: ``GET /api/v1/stocks/{stock_id}/13f-detail`` endpoint.

Covers the available-true payload with ``top_holders`` + ``caveat_flags``
projections, the three unavailable branches, the unknown-stock 404, and
the period override. Reuses the lean ``_seed_snapshot_fixture`` pattern
from ``test_mvp7_01_stocks_13f_snapshots.py``.
"""

from __future__ import annotations

from datetime import date

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


def _seed_detail_fixture(db_session) -> dict[str, int]:
    """Mirror the MVP7-01 fixture pattern with the minimum shape the
    detail endpoint needs."""
    target = _stock(db_session, "DETA", "Detail Coverage Inc")
    partial_stock = _stock(db_session, "PART", "Partial Holder Inc")
    empty_stock = _stock(db_session, "EMPT", "Empty Coverage Inc")

    q3 = date(2031, 9, 30)
    q4 = date(2031, 12, 31)

    managers = [
        _manager(db_session, f"Detail Fund {i}", cik=f"00555{i:04d}")
        for i in range(5)
    ]
    for index, manager in enumerate(managers):
        new_filing = _filing(
            db_session, manager, accession=f"deta-new-{index}", period=q4,
        )
        if index < 2:
            old_filing = _filing(
                db_session, manager, accession=f"deta-old-{index}", period=q3,
            )
            old_shares = 1500 if index == 0 else 1000
            _holding(
                db_session, old_filing, target,
                cusip=f"DETA0{index}001",
                shares=old_shares,
                value_thousands=10_000,
            )
        new_shares = 1000 if index == 0 else 1500
        _holding(
            db_session, new_filing, target,
            cusip=f"DETA0{index}001",
            shares=new_shares,
            value_thousands=11_000,
        )

    partial_mgr = _manager(db_session, "Partial Mgr Detail", cik="0055500001")
    partial_filing = _filing(
        db_session, partial_mgr, accession="part-detail-0", period=q4,
    )
    _holding(
        db_session, partial_filing, partial_stock,
        cusip="PART50001",
        shares=500,
        value_thousands=5_000,
    )

    db_session.commit()
    return {
        "target_id": target.id,
        "partial_id": partial_stock.id,
        "empty_id": empty_stock.id,
    }


# ----- Tests -------------------------------------------------------------


def test_detail_available_includes_top_holders_and_caveat_flags(client, db_session):
    fixture = _seed_detail_fixture(db_session)
    response = client.get(
        f"/api/v1/stocks/{fixture['target_id']}/13f-detail",
        params={"period": "2031-Q4", "use_persisted_scores": "false"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["period"] == "2031-Q4"
    assert payload["period_filing_deadline"] == "2032-02-14"
    assert payload["universe_size"] >= 1

    detail = payload["detail"]
    assert detail["stock_id"] == fixture["target_id"]
    assert detail["available"] is True
    assert detail["ticker"] == "DETA"
    assert detail["company_name"] == "Detail Coverage Inc"

    # Column-summary fields present.
    assert isinstance(detail["conviction_score"], (int, float))
    assert 0.0 <= detail["conviction_percentile"] <= 1.0
    assert detail["consensus_count"] == 5

    # Top holders projected: at most 3, ordered by position_weight desc.
    assert isinstance(detail["top_holders"], list)
    assert 1 <= len(detail["top_holders"]) <= 3
    first_holder = detail["top_holders"][0]
    assert {"manager_id", "manager_name", "manager_type", "position_weight",
            "action", "holding_streak_quarters"} <= set(first_holder.keys())

    # Caveat flags are structured (not just codes).
    assert isinstance(detail["caveat_flags"], list)
    for flag in detail["caveat_flags"]:
        assert {"key", "group", "severity", "label"} <= set(flag.keys())
        assert flag["severity"] in {"warning", "info"}


def test_detail_404_for_unknown_stock(client, db_session):
    response = client.get(
        "/api/v1/stocks/999999/13f-detail",
        params={"period": "2031-Q4", "use_persisted_scores": "false"},
    )
    assert response.status_code == 404


def test_detail_no_holders_unavailable_branch(client, db_session):
    fixture = _seed_detail_fixture(db_session)
    response = client.get(
        f"/api/v1/stocks/{fixture['empty_id']}/13f-detail",
        params={"period": "2031-Q4", "use_persisted_scores": "false"},
    )
    assert response.status_code == 200
    payload = response.json()
    detail = payload["detail"]
    assert detail["available"] is False
    assert detail["unavailable_reason"] == "no_holders"
    assert detail["ticker"] == "EMPT"


def test_detail_below_min_holders_unavailable_branch(client, db_session):
    fixture = _seed_detail_fixture(db_session)
    response = client.get(
        f"/api/v1/stocks/{fixture['partial_id']}/13f-detail",
        params={"period": "2031-Q4", "use_persisted_scores": "false"},
    )
    assert response.status_code == 200
    detail = response.json()["detail"]
    assert detail["available"] is False
    assert detail["unavailable_reason"] == "below_min_holders"


def test_detail_no_qualifying_period_branch(client, db_session):
    stock = _stock(db_session, "VOID2", "Void2 Inc")
    db_session.commit()
    response = client.get(
        f"/api/v1/stocks/{stock.id}/13f-detail",
        params={"period": "2050-Q1"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["universe_size"] == 0
    assert payload["detail"]["available"] is False
    assert payload["detail"]["unavailable_reason"] == "no_qualifying_period"


def test_detail_top_holder_action_field_uses_dashboard_vocabulary(client, db_session):
    """Validate that top_holders[].action uses the dashboard vocabulary
    (``new`` / ``add`` / ``reduce`` / ``exit`` / ``flat``) — the
    frontend topHolderActionLabel helper depends on this."""
    fixture = _seed_detail_fixture(db_session)
    response = client.get(
        f"/api/v1/stocks/{fixture['target_id']}/13f-detail",
        params={"period": "2031-Q4", "use_persisted_scores": "false"},
    )
    detail = response.json()["detail"]
    actions = {h["action"] for h in detail["top_holders"]}
    assert actions <= {"new", "add", "reduce", "exit", "flat"}
