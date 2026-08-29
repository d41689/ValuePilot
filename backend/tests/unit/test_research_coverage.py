from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.artifacts import PdfDocument
from app.models.coverage import ResearchCoverageRequirement
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.oracles_lens import OraclesLensSignal
from app.models.stocks import PoolMembership, Stock, StockPool, StockPrice
from app.services.oracles_lens.constants import SCORE_VERSION
from app.services.analysis_method_gate import register_reviewed_company_classification
from app.services.research_coverage import _method_requirement


def _stock(db_session, ticker: str) -> Stock:
    stock = Stock(
        ticker=ticker,
        exchange="NASDAQ",
        market_country="US",
        company_name=f"{ticker} Inc.",
        is_active=True,
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _watchlist(db_session, user_id: int, stock: Stock) -> None:
    pool = StockPool(user_id=user_id, name="Core Watchlist")
    db_session.add(pool)
    db_session.flush()
    db_session.add(
        PoolMembership(
            user_id=user_id,
            pool_id=pool.id,
            stock_id=stock.id,
            inclusion_type="manual",
        )
    )
    db_session.flush()


def _lens_signal(db_session, stock: Stock, *, score: str = "2.5") -> None:
    db_session.add(
        OraclesLensSignal(
            stock_id=stock.id,
            report_quarter="2026-Q1",
            quarter_end_date=date(2026, 3, 31),
            score_version=SCORE_VERSION,
            raw_consensus_count=3,
            signal_weighted_consensus_score=Decimal(score),
            distinctive_consensus_score=Decimal(score) / Decimal("2"),
            score_confidence="high_confidence",
            caution_flag_codes=[],
            score_explanation={},
            computed_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        )
    )
    db_session.flush()


def _price(db_session, stock: Stock, *, price_date: date) -> None:
    db_session.add(
        StockPrice(
            stock_id=stock.id,
            price_date=price_date,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1_000,
            currency="USD",
            source="twelvedata",
            created_at=datetime(2026, 7, 17, 22, tzinfo=timezone.utc),
        )
    )
    db_session.flush()


def _value_line_doc(
    db_session,
    user_id: int,
    stock: Stock,
    *,
    report_date: date,
    with_exact_authority: bool = True,
) -> None:
    document = PdfDocument(
        user_id=user_id,
        stock_id=stock.id,
        file_name=f"{stock.ticker}.pdf",
        source="Value Line",
        file_storage_key=f"test/{user_id}/{stock.id}.pdf",
        parse_status="parsed",
        report_date=report_date,
    )
    db_session.add(document)
    db_session.flush()
    if not with_exact_authority:
        return
    projection = {
        "metric_key": "is.sales",
        "value_numeric": 1,
        "value_text": None,
        "value_json": None,
        "unit": "USD",
        "currency": None,
        "period": None,
        "period_type": "FY",
        "period_end_date": report_date.isoformat(),
        "as_of_date": None,
    }
    extraction = MetricExtraction(
        user_id=user_id,
        document_id=document.id,
        page_number=1,
        field_key="annual_financials",
        raw_value_text="Sales 1",
        original_text_snippet="Sales 1",
        parser_version="v1",
        parse_generation=1,
        resolved_stock_id=stock.id,
        mapping_version="value-line-v2",
        canonical_projections_json=[projection],
    )
    db_session.add(extraction)
    db_session.flush()
    db_session.add(
        MetricFact(
            user_id=user_id,
            stock_id=stock.id,
            metric_key="is.sales",
            value_numeric=1,
            unit="USD",
            period_type="FY",
            period_end_date=report_date,
            source_type="parsed",
            source_document_id=document.id,
            source_ref_id=extraction.id,
            parse_generation=1,
            is_current=True,
        )
    )
    db_session.flush()


def test_coverage_priority_persists_explainable_user_scoped_requirements(
    db_session, user_factory
):
    from app.models.coverage import ResearchCoverageRequirement
    from app.services.research_coverage import evaluate_research_coverage

    user = user_factory(email="coverage-owner@example.com")
    watch = _stock(db_session, "WATCH")
    lens = _stock(db_session, "LENS")
    _watchlist(db_session, user.id, watch)
    _lens_signal(db_session, lens)
    _price(db_session, watch, price_date=date(2026, 7, 17))
    _value_line_doc(db_session, user.id, watch, report_date=date(2026, 6, 1))

    result = evaluate_research_coverage(
        db_session,
        user_id=user.id,
        as_of=date(2026, 7, 20),
        lens="consensus",
    )

    assert result["priority_policy_version"] == "research-coverage-priority-v1.0"
    assert result["value_line_freshness_policy_version"] == "value-line-120d-v1.0"
    assert result["selected_candidate_count"] == 2
    assert result["lens_eligible_count"] == 1
    assert result["lens_evaluated_count"] == 1
    assert result["lens_denominator"] == 1

    requirements = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(user_id=user.id)
        .order_by(
            ResearchCoverageRequirement.priority_rank,
            ResearchCoverageRequirement.kind,
        )
        .all()
    )
    assert len(requirements) == 6
    by_key = {(row.stock_id, row.kind): row for row in requirements}
    watch_price = by_key[(watch.id, "eod_price")]
    assert watch_price.matched_rule == "watchlist_member"
    assert watch_price.state == "ready"
    assert watch_price.freshness_policy_version == "eod-freshness-v1.0"
    assert watch_price.evidence_json["currency"] == "USD"
    assert by_key[(watch.id, "value_line_current_report")].state == "ready"
    assert by_key[(watch.id, "method_applicability")].state == "unsupported"
    assert (
        by_key[(watch.id, "method_applicability")].reason_code
        == "company_classification_missing"
    )

    lens_price = by_key[(lens.id, "eod_price")]
    assert lens_price.matched_rule == "oracles_lens_consensus_top30"
    assert lens_price.priority_rank > watch_price.priority_rank
    assert lens_price.state == "missing"
    lens_report = by_key[(lens.id, "value_line_current_report")]
    assert lens_report.state == "missing"
    assert lens_report.next_action == "upload_value_line_report"
    assert all(row.evaluated_at is not None for row in requirements)


def test_value_line_coverage_requires_exact_current_fact_authority(
    db_session,
    user_factory,
):
    from app.services.research_coverage import _value_line_requirement

    user = user_factory(email="coverage-reparse-required@example.com")
    stock = _stock(db_session, "VLRP")
    _value_line_doc(
        db_session,
        user.id,
        stock,
        report_date=date(2026, 6, 1),
        with_exact_authority=False,
    )

    result = _value_line_requirement(
        db_session,
        user_id=user.id,
        stock=stock,
        as_of=date(2026, 7, 20),
    )

    assert result["state"] == "blocked"
    assert result["reason_code"] == "value_line_reparse_required"
    assert result["evidence_json"]["canonical_fact_authority"] is False
    assert result["next_action"] == "reparse_value_line_report"


def test_method_coverage_blocks_eligible_but_unauthorized_owner_earnings(
    db_session,
) -> None:
    stock = _stock(db_session, "OEBLK")
    evaluated_at = datetime.now(timezone.utc)
    register_reviewed_company_classification(
        db_session,
        stock_id=stock.id,
        classification="ordinary_operating",
        effective_from=date(2020, 1, 1),
        known_at=evaluated_at - timedelta(seconds=1),
        review_reason="Reviewed ordinary operating company.",
    )

    requirement = _method_requirement(
        db_session,
        stock=stock,
        evaluated_at=evaluated_at,
    )

    assert requirement["state"] == "blocked"
    assert requirement["reason_code"] == "output_not_authorized"
    assert requirement["evidence_json"]["output_authorized"] is False
    assert requirement["next_action"] == "complete_owner_earnings_method_requirements"


def test_value_line_freshness_is_user_scoped_and_stale_is_not_ready(
    db_session, user_factory
):
    from app.models.coverage import ResearchCoverageRequirement
    from app.services.research_coverage import evaluate_research_coverage

    owner = user_factory(email="coverage-doc-owner@example.com")
    other = user_factory(email="coverage-other@example.com")
    stock = _stock(db_session, "VLST")
    _watchlist(db_session, other.id, stock)
    # A fresh report owned by somebody else must not cover this user's queue.
    _value_line_doc(db_session, owner.id, stock, report_date=date(2026, 7, 1))
    _value_line_doc(db_session, other.id, stock, report_date=date(2026, 1, 1))

    evaluate_research_coverage(
        db_session, user_id=other.id, as_of=date(2026, 7, 20)
    )

    requirement = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(
            user_id=other.id,
            stock_id=stock.id,
            kind="value_line_current_report",
        )
        .one()
    )
    assert requirement.state == "stale"
    assert requirement.evidence_json["report_date"] == "2026-01-01"
    assert requirement.source_ref_id is not None


def test_coverage_api_never_returns_another_users_projection(
    client, db_session, user_factory, auth_headers
):
    from app.services.research_coverage import evaluate_research_coverage

    owner = user_factory(email="coverage-api-owner@example.com")
    other = user_factory(email="coverage-api-other@example.com")
    stock = _stock(db_session, "PRIV")
    _watchlist(db_session, owner.id, stock)
    evaluate_research_coverage(
        db_session, user_id=owner.id, as_of=date(2026, 7, 20)
    )

    owner_response = client.get(
        "/api/v1/coverage/requirements", headers=auth_headers(owner)
    )
    other_response = client.get(
        "/api/v1/coverage/requirements", headers=auth_headers(other)
    )

    assert owner_response.status_code == 200, owner_response.text
    assert {row["stock_id"] for row in owner_response.json()["items"]} == {stock.id}
    assert other_response.status_code == 200, other_response.text
    assert other_response.json()["items"] == []


def test_coverage_evaluate_endpoint_is_idempotent(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="coverage-eval@example.com")
    stock = _stock(db_session, "IDEM")
    _watchlist(db_session, user.id, stock)

    first = client.post(
        "/api/v1/coverage/evaluate?lens=consensus",
        headers=auth_headers(user),
    )
    second = client.post(
        "/api/v1/coverage/evaluate?lens=consensus",
        headers=auth_headers(user),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["requirements_evaluated"] == 3
    assert second.json()["requirements_evaluated"] == 3
    listing = client.get(
        "/api/v1/coverage/requirements", headers=auth_headers(user)
    ).json()
    assert len(listing["items"]) == 3


def test_coverage_projection_endpoints_reject_historical_as_of(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory(email="coverage-no-false-pit@example.com")
    admin = user_factory(email="coverage-no-false-pit-admin@example.com", role="admin")
    stock = _stock(db_session, "CPIT")
    _watchlist(db_session, owner.id, stock)
    historical_day = date.today() - timedelta(days=1)

    user_response = client.post(
        f"/api/v1/coverage/evaluate?as_of={historical_day.isoformat()}",
        headers=auth_headers(owner),
    )
    admin_response = client.post(
        f"/api/v1/coverage/admin/evaluate-all?as_of={historical_day.isoformat()}",
        headers=auth_headers(admin),
    )

    assert user_response.status_code == 422, user_response.text
    assert admin_response.status_code == 422, admin_response.text
    assert user_response.json()["detail"]["code"] == "historical_as_of_not_supported"
    assert admin_response.json()["detail"]["code"] == "historical_as_of_not_supported"
    assert db_session.query(ResearchCoverageRequirement).count() == 0


def test_admin_coverage_queue_summarizes_all_users_and_rejects_non_admin(
    client, db_session, user_factory, auth_headers
):
    from app.services.research_coverage import evaluate_research_coverage

    owner = user_factory(email="coverage-queue-owner@example.com")
    admin = user_factory(email="coverage-admin@example.com", role="admin")
    stock = _stock(db_session, "QUEUE")
    _watchlist(db_session, owner.id, stock)
    evaluate_research_coverage(
        db_session, user_id=owner.id, as_of=date(2026, 7, 20)
    )

    forbidden = client.get(
        "/api/v1/coverage/admin/requirements", headers=auth_headers(owner)
    )
    response = client.get(
        "/api/v1/coverage/admin/requirements", headers=auth_headers(admin)
    )

    assert forbidden.status_code == 403
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["total"] == 3
    assert payload["summary"]["by_state"] == {"missing": 2, "unsupported": 1}
    assert payload["summary"]["by_kind"] == {
        "eod_price": 1,
        "method_applicability": 1,
        "value_line_current_report": 1,
    }
    assert "items" not in payload
    assert owner.email not in response.text
    assert stock.ticker not in response.text


def test_coverage_price_refresh_is_batched_observable_and_re_evaluates(
    client, db_session, user_factory, auth_headers, monkeypatch
):
    from app.models.institutions import JobRun
    from app.services import market_data_service
    from app.services.research_coverage import evaluate_research_coverage

    class Provider:
        name = "licensed_fixture"

        def __init__(self):
            self.calls = []

        def fetch_daily(self, symbols, target_date):
            self.calls.append((symbols, target_date))
            return {
                symbol: {
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100,
                    "volume": 100,
                    "currency": "USD",
                    "source": self.name,
                }
                for symbol in symbols
            }

    user = user_factory(email="coverage-refresh@example.com")
    first_stock = _stock(db_session, "BAT1")
    second_stock = _stock(db_session, "BAT2")
    _watchlist(db_session, user.id, first_stock)
    # Same user's second pool/stock remains a separate coverage candidate.
    _watchlist(db_session, user.id, second_stock)
    evaluate_research_coverage(
        db_session, user_id=user.id, as_of=date(2026, 7, 20)
    )
    provider = Provider()
    monkeypatch.setattr(market_data_service, "get_default_provider", lambda: provider)

    response = client.post(
        "/api/v1/coverage/refresh-prices?as_of=2026-07-20",
        headers=auth_headers(user),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["target_count"] == 2
    assert provider.calls == [(["BAT1", "BAT2"], date(2026, 7, 20))]
    job = db_session.get(JobRun, payload["job_id"])
    assert job.job_type == "coverage_eod_refresh"
    assert job.status == "succeeded"
    listing = client.get(
        "/api/v1/coverage/requirements", headers=auth_headers(user)
    ).json()
    price_rows = [item for item in listing["items"] if item["kind"] == "eod_price"]
    assert {item["state"] for item in price_rows} == {"stale"}
    assert {item["evidence"]["price_date"] for item in price_rows} == {
        "2026-07-20"
    }


def test_open_research_cases_outrank_watchlist_and_lens_candidates(
    db_session, user_factory
):
    from app.models.coverage import ResearchCoverageRequirement
    from app.models.research import ResearchCase
    from app.services.research_coverage import evaluate_research_coverage

    user = user_factory(email="coverage-case-priority@example.com")
    owned = _stock(db_session, "OWND")
    watched = _stock(db_session, "WATC")
    researching = _stock(db_session, "RSCH")
    queued = _stock(db_session, "QUEU")
    watchlist_only = _stock(db_session, "LIST")
    lens_only = _stock(db_session, "LENS2")
    db_session.add_all(
        [
            ResearchCase(
                user_id=user.id,
                stock_id=owned.id,
                state="monitoring",
                decision="own",
                next_review_on=date(2026, 7, 1),
            ),
            ResearchCase(
                user_id=user.id,
                stock_id=watched.id,
                state="monitoring",
                decision="watch",
                next_review_on=date(2026, 7, 1),
            ),
            ResearchCase(user_id=user.id, stock_id=researching.id, state="researching"),
            ResearchCase(user_id=user.id, stock_id=queued.id, state="queued"),
        ]
    )
    _watchlist(db_session, user.id, watchlist_only)
    _lens_signal(db_session, lens_only)
    db_session.commit()

    evaluate_research_coverage(
        db_session, user_id=user.id, as_of=date(2026, 7, 20)
    )

    rows = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(user_id=user.id, kind="eod_price", is_current=True)
        .order_by(ResearchCoverageRequirement.priority_rank)
        .all()
    )
    assert [row.stock_id for row in rows] == [
        owned.id,
        watched.id,
        researching.id,
        queued.id,
        watchlist_only.id,
        lens_only.id,
    ]
    assert [row.matched_rule for row in rows] == [
        "open_case_own_overdue",
        "open_case_watch_overdue",
        "open_case_researching",
        "open_case_queued",
        "watchlist_member",
        "oracles_lens_consensus_top30",
    ]
