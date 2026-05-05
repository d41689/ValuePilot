from __future__ import annotations

from datetime import date

from app.models.institutions import Filing13F, Holding13F, InstitutionManager
from app.models.stocks import Stock


def _manager(db_session, name: str, *, cik: str, superinvestor: bool = True) -> InstitutionManager:
    manager = InstitutionManager(
        cik=cik,
        legal_name=name,
        display_name=name,
        name_normalized=name.lower(),
        match_status="confirmed",
        is_superinvestor=superinvestor,
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


def _seed_oracles_lens_fixture(db_session):
    target = _stock(db_session, "LENS", "Lens Corp")
    other = _stock(db_session, "TAIL", "Tail Position Inc")
    managers = [
        _manager(db_session, f"Long Fund {index}", cik=f"00009{index:05d}")
        for index in range(75)
    ]
    partial_manager = _manager(db_session, "Partial Fund", cik="0000999999")

    q3 = date(2031, 9, 30)
    q4 = date(2031, 12, 31)
    q1_partial = date(2032, 3, 31)

    for index, manager in enumerate(managers):
        old_filing = _filing(
            db_session,
            manager,
            accession=f"old-{index}",
            period=q3,
            total_value=100_000,
        )
        new_filing = _filing(
            db_session,
            manager,
            accession=f"new-{index}",
            period=q4,
            total_value=100_000,
        )
        _holding(
            db_session,
            old_filing,
            target,
            cusip=f"12345{index}00",
            shares=1_000 + index * 100,
            value_thousands=9_000 + index * 1_000,
        )
        _holding(
            db_session,
            new_filing,
            target,
            cusip=f"12345{index}00",
            shares=1_400 + index * 100,
            value_thousands=14_000 + index * 1_000,
        )
        _holding(
            db_session,
            new_filing,
            other,
            cusip=f"99999{index}00",
            shares=10,
            value_thousands=100,
        )

    partial_filing = _filing(
        db_session,
        partial_manager,
        accession="partial-0",
        period=q1_partial,
        total_value=100_000,
    )
    _holding(
        db_session,
        partial_filing,
        target,
        cusip="123456789",
        shares=1_500,
        value_thousands=15_000,
    )
    db_session.commit()
    return target


def test_oracles_lens_defaults_to_latest_complete_period_and_signal_rows(client, db_session):
    target = _seed_oracles_lens_fixture(db_session)

    response = client.get("/api/v1/13f/oracles-lens")
    assert response.status_code == 200

    payload = response.json()
    assert payload["period"] == "2031-Q4"
    assert payload["period_end_date"] == "2031-12-31"
    assert payload["baseline_notice"].startswith("13F filings are delayed snapshots")
    assert payload["coverage"]["manager_count"] == 75
    assert payload["coverage"]["linked_holding_count"] >= 3

    item = next(row for row in payload["items"] if row["stock_id"] == target.id)
    assert item["ticker"] == "LENS"
    assert item["consensus_count"] == 75
    assert item["signal_weighted_consensus_score"] > 0
    assert item["conviction_score"] > 0
    assert item["score_confidence"] in {"medium", "low"}
    assert item["median_holding_streak_quarters"] == 2
    assert item["manager_signal_summary"]["unknown_manager_type_count"] == 75
    assert item["manager_signal_summary"]["manager_signal_quality_coverage"] == 0
    assert item["score_explanation"]["primary_reasons"]
    assert "conviction_components" in item["score_explanation"]
    assert all(flag["key"] != "stale_filing" for flag in item["caution_flags"])
    assert any(flag["key"] == "unknown_manager_type_heavy" for flag in item["caution_flags"])


def test_oracles_lens_marks_old_selected_period(client, db_session):
    _seed_oracles_lens_fixture(db_session)

    response = client.get("/api/v1/13f/oracles-lens?period=2031-Q3")
    assert response.status_code == 200

    payload = response.json()
    assert payload["period"] == "2031-Q3"
    assert payload["latest_complete_period"] == "2031-Q4"
    assert payload["items"]
    assert any(
        flag["key"] == "old_period_selected"
        for item in payload["items"]
        for flag in item["caution_flags"]
    )
