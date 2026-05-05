from __future__ import annotations

from datetime import date

from app.models.facts import MetricFact
from app.models.institutions import Filing13F, Holding13F, InstitutionManager
from app.models.stocks import Stock, StockPrice


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


def _metric_fact(
    stock: Stock,
    metric_key: str,
    value: float,
    *,
    period_end: date = date(2031, 12, 31),
    source_type: str = "parsed",
) -> MetricFact:
    return MetricFact(
        user_id=1,
        stock_id=stock.id,
        metric_key=metric_key,
        value_numeric=value,
        value_json={"fact_nature": "actual"},
        unit="ratio",
        period_type="FY",
        period_end_date=period_end,
        source_type=source_type,
        is_current=True,
    )


def test_oracles_lens_defaults_to_latest_complete_period_and_signal_rows(client, db_session):
    target = _seed_oracles_lens_fixture(db_session)

    response = client.get("/api/v1/13f/oracles-lens")
    assert response.status_code == 200

    payload = response.json()
    assert payload["period"] == "2031-Q4"
    assert payload["period_end_date"] == "2031-12-31"
    assert payload["baseline_notice"].startswith("13F filings are delayed snapshots")
    assert payload["periods"][:3] == [
        {
            "label": "2032-Q1",
            "period_end_date": "2032-03-31",
            "manager_count": 1,
            "is_selected": False,
            "is_latest_complete": False,
        },
        {
            "label": "2031-Q4",
            "period_end_date": "2031-12-31",
            "manager_count": 75,
            "is_selected": True,
            "is_latest_complete": True,
        },
        {
            "label": "2031-Q3",
            "period_end_date": "2031-09-30",
            "manager_count": 75,
            "is_selected": False,
            "is_latest_complete": False,
        },
    ]
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


def test_oracles_lens_adds_value_line_quality_overlay(client, db_session):
    target = _seed_oracles_lens_fixture(db_session)
    db_session.add_all(
        [
            _metric_fact(target, "score.piotroski.total", 8, source_type="calculated"),
            _metric_fact(target, "bs.return_on_total_capital", 0.24),
            _metric_fact(target, "bs.return_on_equity", 0.31),
            _metric_fact(target, "is.net_profit_margin", 0.22),
            _metric_fact(target, "leverage.long_term_debt_to_capital", 0.18),
            _metric_fact(target, "owners_earnings_per_share_normalized", 5.0),
        ]
    )
    db_session.add(
        StockPrice(
            stock_id=target.id,
            price_date=date(2032, 1, 2),
            open=99.0,
            high=101.0,
            low=98.0,
            close=100.0,
            adj_close=None,
            volume=1000,
            source="test",
        )
    )
    db_session.commit()

    response = client.get("/api/v1/13f/oracles-lens")
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    assert item["quality_overlay"] == {
        "piotroski_total": 8.0,
        "return_on_total_capital": 0.24,
        "return_on_equity": 0.31,
        "net_profit_margin": 0.22,
        "debt_to_capital": 0.18,
        "owner_earnings_yield": 0.05,
        "latest_price": 100.0,
        "coverage": {
            "value_line": True,
            "price": True,
            "owner_earnings": True,
            "available_metrics": 6,
            "expected_metrics": 6,
        },
        "unavailable_reasons": [],
    }
    assert response.json()["coverage"]["value_line_coverage_count"] >= 1


def test_oracles_lens_adds_conservative_valuation_reference(client, db_session):
    target = _seed_oracles_lens_fixture(db_session)
    db_session.add_all(
        [
            _metric_fact(target, "target.price_18m.mid", 150.0, period_end=date(2032, 1, 1)),
            _metric_fact(
                target,
                "val.fair_value",
                175.0,
                period_end=date(2032, 1, 2),
                source_type="manual",
            ),
        ]
    )
    db_session.add(
        StockPrice(
            stock_id=target.id,
            price_date=date(2032, 1, 2),
            open=99.0,
            high=101.0,
            low=98.0,
            close=100.0,
            adj_close=None,
            volume=1000,
            source="test",
        )
    )
    db_session.commit()

    response = client.get("/api/v1/13f/oracles-lens")
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    assert item["holder_price_estimate_low"] == 10000.0
    assert item["holder_price_estimate_high"] == 10000.0
    assert item["current_price"] == 100.0
    assert item["valuation_reference"] == 175.0
    assert item["valuation_reference_label"] == "User-entered valuation reference"
    assert item["valuation_reference_type"] == "manual_intrinsic_value"
    assert item["valuation_reference_confidence"] == "user_supplied"
    assert item["discount_to_reference"] == 0.428571
    assert item["valuation_state"] == {
        "below_holder_estimate": True,
        "below_selected_valuation_reference": True,
    }
    assert item["valuation_unavailable_reasons"] == []
    assert response.json()["coverage"]["valuation_reference_coverage_count"] >= 1


def test_oracles_lens_labels_value_line_target_as_reference_not_intrinsic_value(client, db_session):
    target = _seed_oracles_lens_fixture(db_session)
    db_session.add(_metric_fact(target, "target.price_18m.mid", 150.0, period_end=date(2032, 1, 1)))
    db_session.add(
        StockPrice(
            stock_id=target.id,
            price_date=date(2032, 1, 2),
            open=99.0,
            high=101.0,
            low=98.0,
            close=100.0,
            adj_close=None,
            volume=1000,
            source="test",
        )
    )
    db_session.commit()

    response = client.get("/api/v1/13f/oracles-lens")
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    assert item["valuation_reference"] == 150.0
    assert item["valuation_reference_label"] == "Value Line 18-month target midpoint"
    assert item["valuation_reference_type"] == "analyst_target_reference"
    assert item["valuation_reference_confidence"] == "medium"
    assert item["valuation_unavailable_reasons"] == []


def test_oracles_lens_marks_old_selected_period(client, db_session):
    _seed_oracles_lens_fixture(db_session)

    response = client.get("/api/v1/13f/oracles-lens?period=2031-Q3")
    assert response.status_code == 200

    payload = response.json()
    assert payload["period"] == "2031-Q3"
    assert payload["latest_complete_period"] == "2031-Q4"
    selected_period = next(period for period in payload["periods"] if period["label"] == "2031-Q3")
    assert selected_period["is_selected"] is True
    latest_complete = next(period for period in payload["periods"] if period["label"] == "2031-Q4")
    assert latest_complete["is_latest_complete"] is True
    assert payload["items"]
    assert any(
        flag["key"] == "old_period_selected"
        for item in payload["items"]
        for flag in item["caution_flags"]
    )
