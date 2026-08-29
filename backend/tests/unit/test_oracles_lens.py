from __future__ import annotations

from datetime import date, datetime, timezone

from app.models.artifacts import PdfDocument
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.institutions import Filing13F, Holding13F, InstitutionManager, ParseRun13F
from app.models.research import ResearchCase, ResearchCaseRevision
from app.models.stocks import Stock, StockPrice
from app.models.users import User
from app.services.analysis_method_gate import register_reviewed_company_classification
from financial_truth_fixtures import authorize_parsed_facts


def _classify_ordinary(db_session, stock: Stock) -> None:
    classification = register_reviewed_company_classification(
        db_session,
        stock_id=stock.id,
        classification="ordinary_operating",
        effective_from=date(2020, 1, 1),
        known_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        review_reason="Test fixture reviewed as an ordinary operating company.",
    )
    stock._test_classification_id = classification.id


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
    quarter = f"{filing.period_of_report.year}-Q{((filing.period_of_report.month - 1) // 3) + 1}"
    filing.report_quarter = quarter
    filing.quarter_end_date = filing.period_of_report
    filing.accession_number = filing.accession_no
    filing.is_active_for_manager_period = filing.is_latest_for_period
    filing.parse_status = "succeeded"
    parse_run = (
        db_session.query(ParseRun13F)
        .filter(ParseRun13F.accession_number == filing.accession_no)
        .filter(ParseRun13F.is_current.is_(True))
        .one_or_none()
    )
    if parse_run is None:
        parse_run = ParseRun13F(
            accession_number=filing.accession_no,
            parser_version="test",
            fingerprint_version="v1",
            status="succeeded",
            is_current=True,
        )
        db_session.add(parse_run)
        db_session.flush()
    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=parse_run.id,
        manager_id=filing.manager_id,
        accession_number=filing.accession_no,
        report_quarter=quarter,
        quarter_end_date=filing.period_of_report,
        row_fingerprint=f"{filing.accession_no}-{cusip}-{stock.ticker}",
        holding_row_fingerprint=f"{filing.accession_no}-{cusip}-{stock.ticker}",
        cusip=cusip,
        issuer_name=stock.company_name,
        title_of_class="COM",
        value_thousands=value_thousands,
        shares=shares,
        share_type="SH",
        stock_id=stock.id,
        cusip_mapping_status="linked",
        holding_attribution_status="direct",
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
    db_session,
    stock: Stock,
    metric_key: str,
    value: float,
    *,
    period_end: date = date(2031, 12, 31),
    source_type: str | None = None,
    source_document_id: int | None = None,
) -> MetricFact:
    analysis_method = None
    if metric_key.startswith("owners_earnings"):
        analysis_method = {
            "policy_version": "analysis-method-gate-v1",
            "classification_id": getattr(stock, "_test_classification_id", None),
            "method_id": "ordinary-owner-economics-v1",
            "evidence_complete": True,
        }
    elif metric_key == "bs.return_on_total_capital":
        analysis_method = {
            "policy_version": "analysis-method-gate-v1",
            "classification_id": getattr(stock, "_test_classification_id", None),
            "method_id": "ordinary-roic-v1",
            "evidence_complete": True,
        }
    effective_source_type = source_type or (
        "parsed" if source_document_id is not None else "manual"
    )
    fact = MetricFact(
        user_id=stock._test_user_id,
        stock_id=stock.id,
        metric_key=metric_key,
        value_numeric=value,
        value_json={
            "fact_nature": "actual",
            **({"analysis_method": analysis_method} if analysis_method else {}),
        },
        unit="ratio",
        period_type="FY",
        period_end_date=period_end,
        source_document_id=source_document_id,
        source_ref_id=(
            getattr(stock, "_test_extraction_by_document_id", {}).get(
                source_document_id
            )
            if effective_source_type in {"parsed", "manual"}
            and source_document_id is not None
            else None
        ),
        parse_generation=(
            1
            if effective_source_type == "parsed" and source_document_id is not None
            else None
        ),
        source_type=effective_source_type,
        is_current=True,
    )
    if effective_source_type == "parsed":
        document = db_session.get(PdfDocument, source_document_id)
        assert document is not None
        authorize_parsed_facts(db_session, document=document, facts=[fact])
    return fact


def _pdf_document(db_session, stock: Stock, *, report_date: date = date(2032, 1, 31)) -> PdfDocument:
    document = PdfDocument(
        user_id=stock._test_user_id,
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
    extraction = MetricExtraction(
        user_id=stock._test_user_id,
        document_id=document.id,
        page_number=1,
        field_key="quality_fixture",
        raw_value_text="quality fixture",
        original_text_snippet="quality fixture",
        parsed_value_json={"fixture": True},
        parser_version="test",
        parse_generation=document.current_parse_generation,
    )
    db_session.add(extraction)
    db_session.flush()
    lineage = dict(
        getattr(stock, "_test_extraction_by_document_id", {})
    )
    lineage[document.id] = extraction.id
    stock._test_extraction_by_document_id = lineage
    return document


def _manual_valuation_fact(
    db_session,
    stock: Stock,
    value: float,
    *,
    period_end: date,
) -> MetricFact:
    case = (
        db_session.query(ResearchCase)
        .filter_by(user_id=stock._test_user_id, stock_id=stock.id)
        .one_or_none()
    )
    if case is None:
        case = ResearchCase(
            user_id=stock._test_user_id,
            stock_id=stock.id,
            state="researching",
        )
        db_session.add(case)
        db_session.flush()
    revision_number = case.head_revision_number + 1
    revision = ResearchCaseRevision(
        case_id=case.id,
        revision_number=revision_number,
        case_state=case.state,
        valuation_low=value,
        valuation_base=value,
        valuation_high=value,
        valuation_currency="USD",
        valuation_as_of_date=period_end,
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=stock._test_user_id,
    )
    db_session.add(revision)
    db_session.flush()
    case.head_revision_number = revision_number
    db_session.flush()
    return MetricFact(
        user_id=stock._test_user_id,
        stock_id=stock.id,
        metric_key="val.fair_value",
        value_numeric=value,
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=period_end,
        source_type="manual",
        source_ref_id=revision.id,
        is_current=True,
    )


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
    # PR #97 (holder $ estimate unit fix): the fixture's period_of_report is
    # 2031-12-31 (post-TRANSITION_ACCEPTED_DATE), so value_thousands stores
    # raw DOLLARS per the post-2023 SEC rule. Per-share = 88000 / 8800 = $10.
    # Pre-fix this returned $10,000 (the 1000× bug from the legacy
    # value_thousands * 1000 / shares formula).
    assert top_holder["holder_price_estimate"] == 10.0
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


def test_oracles_lens_adds_value_line_quality_overlay(
    client, db_session, auth_headers, monkeypatch,
):
    monkeypatch.setattr(
        "app.services.oracles_lens.dashboard.compute_target_date",
        lambda _now: date(2032, 1, 2),
    )
    target = _seed_oracles_lens_fixture(db_session)
    _classify_ordinary(db_session, target)
    document = _pdf_document(db_session, target)
    db_session.add_all(
        [
            _metric_fact(
                db_session,
                target,
                "score.piotroski.total",
                8,
                source_type="calculated",
                source_document_id=document.id,
            ),
            _metric_fact(db_session, target, "bs.return_on_total_capital", 0.24, source_document_id=document.id),
            _metric_fact(db_session, target, "bs.return_on_equity", 0.31, source_document_id=document.id),
            _metric_fact(db_session, target, "is.net_profit_margin", 0.22, source_document_id=document.id),
            _metric_fact(
                db_session,
                target,
                "leverage.long_term_debt_to_capital",
                0.18,
                source_document_id=document.id,
            ),
            _metric_fact(
                db_session,
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
            currency="USD",
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/13f/oracles-lens?use_persisted_scores=false",
        headers=auth_headers(db_session.get(User, target._test_user_id)),
    )
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    assert item["quality_overlay"] == {
        "piotroski_total": None,
        "return_on_total_capital": 0.24,
        "return_on_equity": 0.31,
        "net_profit_margin": 0.22,
        "debt_to_capital": 0.18,
        "owner_earnings_yield": None,
            "latest_price": 100.0,
            "price_date": "2032-01-02",
            "price_currency": "USD",
            "price_source": "test",
            "price_freshness": "fresh",
            "price_reason": None,
            "price_context": "latest",
            "analysis_methods": {
                "owner_earnings": {
                    "state": "eligible",
                    "reason": None,
                    "policy_version": "analysis-method-gate-v1",
                        "classification": "ordinary_operating",
                        "method_id": "ordinary-owner-economics-v1",
                        "output_authorized": False,
                },
                "roic": {
                    "state": "eligible",
                    "reason": None,
                    "policy_version": "analysis-method-gate-v1",
                        "classification": "ordinary_operating",
                        "method_id": "ordinary-roic-v1",
                        "output_authorized": True,
                },
            },
        "coverage": {
            "value_line": True,
            "price": True,
            "owner_earnings": False,
            "available_metrics": 4,
            "expected_metrics": 6,
        },
        "unavailable_reasons": ["owner earnings output not authorized"],
        "provenance": {
            "primary_source_document_id": document.id,
            "source_document_ids": [document.id],
            "facts": [
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
            ],
        },
    }
    assert response.json()["coverage"]["value_line_coverage_count"] >= 1


def test_oracles_lens_quarantines_legacy_piotroski_json_score(
    client, db_session, auth_headers,
):
    """Caller-authored legacy JSON is not sufficient publication authority."""
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

    response = client.get(
        "/api/v1/13f/oracles-lens?use_persisted_scores=false",
        headers=auth_headers(db_session.get(User, target._test_user_id)),
    )
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    overlay = item["quality_overlay"]
    assert overlay["piotroski_total"] is None
    assert overlay["coverage"]["value_line"] is False


def test_oracles_lens_quarantines_legacy_piotroski_numeric_score(
    client, db_session, auth_headers,
):
    """A forged numeric column cannot bypass missing exact run lineage."""
    target = _seed_oracles_lens_fixture(db_session)
    document = _pdf_document(db_session, target)
    db_session.add(
        MetricFact(
            user_id=target._test_user_id,
            stock_id=target.id,
            metric_key="score.piotroski.total",
            value_numeric=8.0,  # canonical column — should win
            value_json={
                "partial_score": 3,  # divergent fallback — should NOT win
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

    response = client.get(
        "/api/v1/13f/oracles-lens?use_persisted_scores=false",
        headers=auth_headers(db_session.get(User, target._test_user_id)),
    )
    assert response.status_code == 200
    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    assert item["quality_overlay"]["piotroski_total"] is None


def test_oracles_lens_adds_conservative_valuation_reference(
    client, db_session, auth_headers, monkeypatch,
):
    monkeypatch.setattr(
        "app.services.oracles_lens.dashboard.compute_target_date",
        lambda _now: date(2032, 1, 2),
    )
    target = _seed_oracles_lens_fixture(db_session)
    target_document = _pdf_document(
        db_session, target, report_date=date(2032, 1, 1)
    )
    db_session.add_all(
        [
            _metric_fact(
                db_session,
                target,
                "target.price_18m.mid",
                150.0,
                period_end=date(2032, 1, 1),
                source_document_id=target_document.id,
            ),
            _manual_valuation_fact(
                db_session,
                target,
                175.0,
                period_end=date(2032, 1, 2),
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
            currency="USD",
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/13f/oracles-lens?use_persisted_scores=false",
        headers=auth_headers(db_session.get(User, target._test_user_id)),
    )
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    # PR #97: fixture period 2031-12-31 → post-transition dollars rule, so
    # value_thousands / shares directly. The fixture's value/share ratio is
    # constant across holders (each +$1,000 of value comes with +100 shares),
    # so low == high == 10.0.
    assert item["holder_price_estimate_low"] == 10.0
    assert item["holder_price_estimate_high"] == 10.0
    assert item["current_price"] == 100.0
    assert item["current_price_date"] == "2032-01-02"
    assert item["price_context"] == "latest"
    assert item["valuation_reference"] == 175.0
    assert item["valuation_reference_label"] == "User-entered valuation reference"
    assert item["valuation_reference_type"] == "manual_intrinsic_value"
    assert item["valuation_reference_confidence"] == "user_supplied"
    assert item["discount_to_reference"] == 0.428571
    # PR #97: with the holder estimate corrected to $10/share (was $10,000/share
    # under the buggy formula), the current price of $100 is ABOVE the holder
    # estimate, not below. ``below_selected_valuation_reference`` is unaffected
    # — that's price ($100) vs manual valuation reference ($175).
    assert item["valuation_state"] == {
        "below_holder_estimate": False,
        "below_selected_valuation_reference": True,
    }
    assert item["valuation_unavailable_reasons"] == []
    assert response.json()["coverage"]["valuation_reference_coverage_count"] >= 1


def test_oracles_lens_labels_value_line_target_as_reference_not_intrinsic_value(
    client, db_session, auth_headers, monkeypatch,
):
    monkeypatch.setattr(
        "app.services.oracles_lens.dashboard.compute_target_date",
        lambda _now: date(2032, 1, 2),
    )
    target = _seed_oracles_lens_fixture(db_session)
    target_document = _pdf_document(
        db_session, target, report_date=date(2032, 1, 1)
    )
    db_session.add(
        _metric_fact(
            db_session,
            target,
            "target.price_18m.mid",
            150.0,
            period_end=date(2032, 1, 1),
            source_document_id=target_document.id,
        )
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
            currency="USD",
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/13f/oracles-lens?use_persisted_scores=false",
        headers=auth_headers(db_session.get(User, target._test_user_id)),
    )
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    assert item["valuation_reference"] == 150.0
    assert item["valuation_reference_label"] == "Value Line 18-month target midpoint"
    assert item["valuation_reference_type"] == "analyst_target_reference"
    assert item["valuation_reference_confidence"] == "medium"
    assert item["valuation_unavailable_reasons"] == []


def test_oracles_lens_uses_period_price_for_historical_snapshot(
    client, db_session, auth_headers,
):
    target = _seed_oracles_lens_fixture(db_session)
    _classify_ordinary(db_session, target)
    target_document = _pdf_document(
        db_session, target, report_date=date(2031, 9, 30)
    )
    db_session.add_all(
        [
            _metric_fact(
                db_session,
                target,
                "target.price_18m.mid",
                120.0,
                period_end=date(2031, 9, 30),
                source_document_id=target_document.id,
            ),
            _metric_fact(
                db_session,
                target,
                "owners_earnings_per_share_normalized",
                4.0,
                source_document_id=target_document.id,
            ),
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
                currency="USD",
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

    response = client.get(
        "/api/v1/13f/oracles-lens?period=2031-Q3&use_persisted_scores=false",
        headers=auth_headers(db_session.get(User, target._test_user_id)),
    )
    assert response.status_code == 200

    item = next(row for row in response.json()["items"] if row["stock_id"] == target.id)
    assert item["current_price"] == 80.0
    assert item["current_price_date"] == "2031-09-30"
    assert item["price_context"] == "historical_snapshot"
    assert item["discount_to_reference"] == 0.333333
    assert item["quality_overlay"]["owner_earnings_yield"] is None
    assert "owner earnings output not authorized" in item["quality_overlay"][
        "unavailable_reasons"
    ]
    assert item["quality_overlay"]["price_context"] == "historical_snapshot"
    assert response.json()["coverage"]["price_context"] == "historical_snapshot"
    assert response.json()["coverage"]["price_target_date"] == "2031-09-30"
    assert response.json()["coverage"]["candidate_count"] == 1
    assert response.json()["coverage"]["price_coverage_count"] == 1
    assert response.json()["coverage"]["price_missing_count"] == 0
    assert response.json()["coverage"]["price_coverage_ratio"] == 1.0
    assert response.json()["coverage"]["price_backfill_required"] is False


def test_oracles_lens_never_leaks_another_users_valuation(
    client, db_session, user_factory, auth_headers,
):
    target = _seed_oracles_lens_fixture(db_session)
    owner = db_session.get(User, target._test_user_id)
    viewer = user_factory(email="oracles-viewer@example.com")
    quality_document = _pdf_document(
        db_session, target, report_date=date(2032, 1, 2)
    )
    db_session.add(
        _manual_valuation_fact(
            db_session,
            target,
            987.0,
            period_end=date(2032, 1, 2),
        )
    )
    db_session.add(
        _metric_fact(
            db_session,
            target,
            "bs.return_on_equity",
            0.42,
            period_end=date(2032, 1, 2),
            source_document_id=quality_document.id,
        )
    )
    db_session.commit()

    owner_response = client.get(
        "/api/v1/13f/oracles-lens?use_persisted_scores=false",
        headers=auth_headers(owner),
    )
    viewer_response = client.get(
        "/api/v1/13f/oracles-lens?use_persisted_scores=false",
        headers=auth_headers(viewer),
    )

    owner_item = next(
        row for row in owner_response.json()["items"] if row["stock_id"] == target.id
    )
    viewer_item = next(
        row for row in viewer_response.json()["items"] if row["stock_id"] == target.id
    )
    assert owner_item["valuation_reference"] == 987.0
    assert viewer_item["valuation_reference"] is None
    assert viewer_item["valuation_reference_type"] == "missing"
    assert owner_item["quality_overlay"]["return_on_equity"] == 0.42
    assert viewer_item["quality_overlay"]["return_on_equity"] is None
    assert viewer_item["quality_overlay"]["coverage"]["value_line"] is False


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
