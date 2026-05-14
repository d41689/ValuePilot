from __future__ import annotations

from datetime import date

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.models.institutions import Filing13F, Holding13F, InstitutionManager
from app.models.stocks import Stock, StockPrice
from app.models.users import User


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
    user = User(email="oracles-lens-fixture@example.com")
    db_session.add(user)
    db_session.flush()

    target = _stock(db_session, "LENS", "Lens Corp")
    target._test_user_id = user.id
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
    target._test_user_id = user.id
    return target


def _metric_fact(
    stock: Stock,
    metric_key: str,
    value: float,
    *,
    period_end: date = date(2031, 12, 31),
    source_type: str = "parsed",
    source_document_id: int | None = None,
) -> MetricFact:
    return MetricFact(
        user_id=stock._test_user_id,
        stock_id=stock.id,
        metric_key=metric_key,
        value_numeric=value,
        value_json={"fact_nature": "actual"},
        unit="ratio",
        period_type="FY",
        period_end_date=period_end,
        source_document_id=source_document_id,
        source_type=source_type,
        is_current=True,
    )


def _pdf_document(db_session, stock: Stock, *, report_date: date = date(2032, 1, 31)) -> PdfDocument:
    user = User(email=f"oracles-lens-doc-{stock.id}@example.com")
    db_session.add(user)
    db_session.flush()
    document = PdfDocument(
        user_id=user.id,
        file_name=f"{stock.ticker}-{report_date.isoformat()}.pdf",
        source="value_line",
        report_date=report_date,
        file_storage_key=f"tests/{stock.ticker}-{report_date.isoformat()}.pdf",
        parse_status="parsed",
        parser_version="v1",
        stock_id=stock.id,
    )
    db_session.add(document)
    db_session.flush()
    return document


def test_oracles_lens_defaults_to_latest_complete_period_and_signal_rows(client, db_session):
    target = _seed_oracles_lens_fixture(db_session)

    response = client.get("/api/v1/13f/oracles-lens?use_persisted_scores=false")
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
    assert item["manager_signal_summary"]["high_signal_holder_count"] > 0
    assert item["manager_signal_summary"]["unknown_manager_type_count"] < 75
    assert item["manager_signal_summary"]["manager_signal_quality_coverage"] > 0
    top_holder = item["top_holders"][0]
    assert top_holder["current_shares"] == 8800
    assert top_holder["previous_shares"] == 8400
    assert top_holder["share_delta_pct"] == 0.047619
    assert top_holder["current_value_thousands"] == 88000
    assert top_holder["holder_price_estimate"] == 10000.0
    assert top_holder["filing_date"] == "2031-12-31"
    assert top_holder["accession_no"] == "new-74"
    assert top_holder["manager_type"] == "value_concentrated"
    assert top_holder["manager_signal_weight"] == 1.0
    assert top_holder["portfolio_concentration"] > 0.8
    assert top_holder["portfolio_holding_count"] == 2
    assert top_holder["average_holding_period_quarters"] == 1.5
    assert top_holder["manager_profile_source"] == "derived_13f_behavior"
    assert top_holder["turnover_proxy"] == 0.5
    assert top_holder["high_turnover"] is False
    assert item["score_explanation"]["primary_reasons"]
    assert "conviction_components" in item["score_explanation"]
    assert all(flag["key"] != "stale_filing" for flag in item["caution_flags"])
    assert all(flag["key"] != "unknown_manager_type_heavy" for flag in item["caution_flags"])


def test_oracles_lens_uses_latest_effective_amendment_and_excludes_superseded_holdings(client, db_session):
    manager = _manager(db_session, "Amendment Fund", cik="0000888888")
    old_stock = _stock(db_session, "OLDAM", "Old Amendment Holding")
    new_stock = _stock(db_session, "NEWAM", "New Amendment Holding")
    period = date(2033, 12, 31)
    original = _filing(
        db_session,
        manager,
        accession="amend-original",
        period=period,
        total_value=100_000,
    )
    original.is_latest_for_period = False
    amendment = Filing13F(
        manager_id=manager.id,
        accession_no="amend-latest",
        period_of_report=period,
        filed_at=period,
        form_type="13F-HR/A",
        amends_accession_no=original.accession_no,
        version_rank=2,
        is_latest_for_period=True,
        reported_total_value_thousands=100_000,
        computed_total_value_thousands=100_000,
    )
    db_session.add(amendment)
    db_session.flush()
    _holding(
        db_session,
        original,
        old_stock,
        cusip="111111111",
        shares=100,
        value_thousands=10_000,
    )
    _holding(
        db_session,
        amendment,
        new_stock,
        cusip="222222222",
        shares=200,
        value_thousands=20_000,
    )
    db_session.commit()

    response = client.get("/api/v1/13f/oracles-lens?period=2033-Q4&min_holders=1&use_persisted_scores=false")

    assert response.status_code == 200
    tickers = {item["ticker"] for item in response.json()["items"]}
    assert "NEWAM" in tickers
    assert "OLDAM" not in tickers


def test_oracles_lens_adds_value_line_quality_overlay(client, db_session):
    target = _seed_oracles_lens_fixture(db_session)
    document = _pdf_document(db_session, target)
    db_session.add_all(
        [
            _metric_fact(
                target,
                "score.piotroski.total",
                8,
                source_type="calculated",
                source_document_id=document.id,
            ),
            _metric_fact(target, "bs.return_on_total_capital", 0.24, source_document_id=document.id),
            _metric_fact(target, "bs.return_on_equity", 0.31, source_document_id=document.id),
            _metric_fact(target, "is.net_profit_margin", 0.22, source_document_id=document.id),
            _metric_fact(
                target,
                "leverage.long_term_debt_to_capital",
                0.18,
                source_document_id=document.id,
            ),
            _metric_fact(
                target,
                "owners_earnings_per_share_normalized",
                5.0,
                source_document_id=document.id,
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

    response = client.get("/api/v1/13f/oracles-lens?use_persisted_scores=false")
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
        "price_date": "2032-01-02",
        "price_context": "latest",
        "coverage": {
            "value_line": True,
            "price": True,
            "owner_earnings": True,
            "available_metrics": 6,
            "expected_metrics": 6,
        },
        "unavailable_reasons": [],
        "provenance": {
            "primary_source_document_id": document.id,
            "source_document_ids": [document.id],
            "facts": [
                {
                    "label": "piotroski_total",
                    "metric_key": "score.piotroski.total",
                    "source_document_id": document.id,
                    "source_type": "calculated",
                    "period_type": "FY",
                    "period_end_date": "2031-12-31",
                },
                {
                    "label": "return_on_total_capital",
                    "metric_key": "bs.return_on_total_capital",
                    "source_document_id": document.id,
                    "source_type": "parsed",
                    "period_type": "FY",
                    "period_end_date": "2031-12-31",
                },
                {
                    "label": "return_on_equity",
                    "metric_key": "bs.return_on_equity",
                    "source_document_id": document.id,
                    "source_type": "parsed",
                    "period_type": "FY",
                    "period_end_date": "2031-12-31",
                },
                {
                    "label": "net_profit_margin",
                    "metric_key": "is.net_profit_margin",
                    "source_document_id": document.id,
                    "source_type": "parsed",
                    "period_type": "FY",
                    "period_end_date": "2031-12-31",
                },
                {
                    "label": "debt_to_capital",
                    "metric_key": "leverage.long_term_debt_to_capital",
                    "source_document_id": document.id,
                    "source_type": "parsed",
                    "period_type": "FY",
                    "period_end_date": "2031-12-31",
                },
                {
                    "label": "owners_earnings",
                    "metric_key": "owners_earnings_per_share_normalized",
                    "source_document_id": document.id,
                    "source_type": "parsed",
                    "period_type": "FY",
                    "period_end_date": "2031-12-31",
                },
            ],
        },
    }
    assert response.json()["coverage"]["value_line_coverage_count"] >= 1


def test_oracles_lens_reads_piotroski_from_value_json_when_value_numeric_null(
    client, db_session,
):
    """D2 regression: ``score.piotroski.total`` stores the composite score in
    ``value_json['partial_score']`` with ``value_numeric=NULL`` (269/272 dev
    rows). The pre-D2 ``_quality_overlay_by_stock`` filtered
    ``value_numeric.isnot(None)`` and silently dropped these rows. After D2
    the legacy dashboard must surface Piotroski for stocks whose score lives
    only in ``value_json``.
    """
    target = _seed_oracles_lens_fixture(db_session)
    document = _pdf_document(db_session, target)
    # Piotroski fact: value_numeric=None, value_json carries partial_score.
    db_session.add(
        MetricFact(
            user_id=target._test_user_id,
            stock_id=target.id,
            metric_key="score.piotroski.total",
            value_numeric=None,
            value_json={
                "partial_score": 6,
                "max_available_score": 8,
                "status": "partial",
                "fact_nature": "actual",
            },
            unit=None,
            period_type="FY",
            period_end_date=date(2031, 12, 31),
            source_document_id=document.id,
            source_type="calculated",
            is_current=True,
        )
    )
    db_session.commit()

    response = client.get("/api/v1/13f/oracles-lens?use_persisted_scores=false")
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    overlay = item["quality_overlay"]
    assert overlay["piotroski_total"] == 6.0
    assert overlay["coverage"]["value_line"] is True


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

    response = client.get("/api/v1/13f/oracles-lens?use_persisted_scores=false")
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    assert item["holder_price_estimate_low"] == 10000.0
    assert item["holder_price_estimate_high"] == 10000.0
    assert item["current_price"] == 100.0
    assert item["current_price_date"] == "2032-01-02"
    assert item["price_context"] == "latest"
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

    response = client.get("/api/v1/13f/oracles-lens?use_persisted_scores=false")
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    assert item["valuation_reference"] == 150.0
    assert item["valuation_reference_label"] == "Value Line 18-month target midpoint"
    assert item["valuation_reference_type"] == "analyst_target_reference"
    assert item["valuation_reference_confidence"] == "medium"
    assert item["valuation_unavailable_reasons"] == []


def test_oracles_lens_uses_period_price_for_historical_snapshot(client, db_session):
    target = _seed_oracles_lens_fixture(db_session)
    db_session.add_all(
        [
            _metric_fact(target, "target.price_18m.mid", 120.0, period_end=date(2031, 9, 30)),
            _metric_fact(target, "owners_earnings_per_share_normalized", 4.0),
        ]
    )
    db_session.add_all(
        [
            StockPrice(
                stock_id=target.id,
                price_date=date(2031, 9, 30),
                open=78.0,
                high=82.0,
                low=77.0,
                close=80.0,
                adj_close=None,
                volume=1000,
                source="test",
            ),
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
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/13f/oracles-lens?period=2031-Q3&use_persisted_scores=false")
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    assert item["current_price"] == 80.0
    assert item["current_price_date"] == "2031-09-30"
    assert item["price_context"] == "historical_snapshot"
    assert item["discount_to_reference"] == 0.333333
    assert item["quality_overlay"]["owner_earnings_yield"] == 0.05
    assert item["quality_overlay"]["price_context"] == "historical_snapshot"
    assert response.json()["coverage"]["price_context"] == "historical_snapshot"
    assert response.json()["coverage"]["price_target_date"] == "2031-09-30"
    assert response.json()["coverage"]["candidate_count"] == 1
    assert response.json()["coverage"]["price_coverage_count"] == 1
    assert response.json()["coverage"]["price_missing_count"] == 0
    assert response.json()["coverage"]["price_coverage_ratio"] == 1.0
    assert response.json()["coverage"]["price_backfill_required"] is False


def test_oracles_lens_marks_old_selected_period(client, db_session):
    _seed_oracles_lens_fixture(db_session)

    response = client.get("/api/v1/13f/oracles-lens?period=2031-Q3&use_persisted_scores=false")
    assert response.status_code == 200

    payload = response.json()
    assert payload["period"] == "2031-Q3"
    assert payload["latest_complete_period"] == "2031-Q4"
    assert payload["coverage"]["price_context"] == "historical_snapshot"
    assert payload["coverage"]["price_target_date"] == "2031-09-30"
    assert payload["coverage"]["candidate_count"] == len(payload["items"])
    assert payload["coverage"]["price_coverage_count"] == 0
    assert payload["coverage"]["price_missing_count"] == len(payload["items"])
    assert payload["coverage"]["price_coverage_ratio"] == 0
    assert payload["coverage"]["price_backfill_required"] is True
    assert payload["coverage"]["price_backfill_hint"].startswith(
        "docker compose exec api python -m scripts.backfill_13f_period_prices"
    )
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
