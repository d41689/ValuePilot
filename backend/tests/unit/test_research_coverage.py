from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.artifacts import PdfDocument
from app.models.coverage import ResearchCoverageRequirement
from app.models.oracles_lens import OraclesLensSignal
from app.models.stocks import PoolMembership, Stock, StockPool, StockPrice
from app.services.market_data_service import ET, compute_target_date, expected_session_on_or_before
from app.services.oracles_lens.constants import SCORE_VERSION


@pytest.fixture(autouse=True)
def _authorized_twelvedata(monkeypatch):
    from app.services import market_data_service

    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_PRIMARY", "twelvedata")
    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_SECONDARY", "none")
    monkeypatch.setattr(market_data_service.settings, "TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_COMMERCIAL_ENABLED", True)


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


def _value_line_doc(db_session, user_id: int, stock: Stock, *, report_date: date) -> None:
    db_session.add(
        PdfDocument(
            user_id=user_id,
            stock_id=stock.id,
            file_name=f"{stock.ticker}.pdf",
            source="Value Line",
            file_storage_key=f"test/{user_id}/{stock.id}.pdf",
            parse_status="parsed",
            report_date=report_date,
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
    assert len(requirements) == 4
    by_key = {(row.stock_id, row.kind): row for row in requirements}
    watch_price = by_key[(watch.id, "eod_price")]
    assert watch_price.matched_rule == "watchlist_member"
    assert watch_price.state == "ready"
    assert watch_price.freshness_policy_version == "eod-freshness-v1.0"
    assert watch_price.evidence_json["currency"] == "USD"
    assert by_key[(watch.id, "value_line_current_report")].state == "ready"

    lens_price = by_key[(lens.id, "eod_price")]
    assert lens_price.matched_rule == "oracles_lens_consensus_top30"
    assert lens_price.priority_rank > watch_price.priority_rank
    assert lens_price.state == "missing"
    lens_report = by_key[(lens.id, "value_line_current_report")]
    assert lens_report.state == "missing"
    assert lens_report.next_action == "upload_value_line_report"
    assert all(row.evaluated_at is not None for row in requirements)


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


def test_unauthorized_price_is_redacted_in_coverage_storage_list_and_workspace(
    client, db_session, user_factory, auth_headers, monkeypatch
):
    from app.services import market_data_service
    from app.services.research_coverage import evaluate_research_coverage

    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_PRIMARY", "none")
    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_SECONDARY", "none")
    user = user_factory(email="coverage-redaction@example.com")
    stock = _stock(db_session, "REDACT")
    _watchlist(db_session, user.id, stock)
    coverage_day = expected_session_on_or_before(
        stock.listing_exchange or stock.exchange,
        date.today() - timedelta(days=1),
    ).session_date
    current_day = compute_target_date(datetime.now(timezone.utc).astimezone(ET))
    assert coverage_day is not None
    for price_day in {coverage_day, current_day}:
        db_session.add(
            StockPrice(
                stock_id=stock.id,
                price_date=price_day,
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1_000,
                currency="USD",
                source="unapproved-feed",
            )
        )
    db_session.commit()

    evaluate_research_coverage(db_session, user_id=user.id, as_of=date.today())
    stored = db_session.query(ResearchCoverageRequirement).filter_by(
        user_id=user.id,
        stock_id=stock.id,
        kind="eod_price",
        is_current=True,
    ).one()
    assert stored.reason_code == "source_unavailable"
    assert stored.evidence_json["close"] is None

    headers = auth_headers(user)
    listed = client.get("/api/v1/coverage/requirements", headers=headers)
    assert listed.status_code == 200, listed.text
    listed_price = next(
        item for item in listed.json()["items"] if item["kind"] == "eod_price"
    )
    assert listed_price["evidence"]["close"] is None

    created = client.post(
        "/api/v1/research/cases",
        headers=headers,
        json={
            "stock_id": stock.id,
            "origin": {
                "origin_type": "manual",
                "origin_key": f"coverage-redaction:{stock.id}",
                "source_version": "coverage-redaction-v1",
                "source_ref": {"test": True},
            },
        },
    )
    assert created.status_code == 201, created.text
    workspace = client.get(
        f"/api/v1/research/cases/{created.json()['case']['id']}/workspace",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    workspace_price = next(
        item for item in workspace.json()["coverage"] if item["kind"] == "eod_price"
    )
    assert workspace_price["evidence"]["close"] is None


def test_legacy_price_requirement_without_recorded_authorization_is_redacted_on_every_read(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="coverage-legacy-redaction@example.com")
    stock = _stock(db_session, "LEGACY")
    _watchlist(db_session, user.id, stock)
    price_day = compute_target_date(datetime.now(timezone.utc).astimezone(ET))
    price = StockPrice(
        stock_id=stock.id,
        price_date=price_day,
        open=88,
        high=89,
        low=87,
        close=88,
        volume=1_000,
        currency="USD",
        source="twelvedata",
    )
    db_session.add(price)
    db_session.flush()
    db_session.add(
        ResearchCoverageRequirement(
            user_id=user.id,
            stock_id=stock.id,
            kind="eod_price",
            priority_policy_version="research-coverage-priority-v1.0",
            matched_rule="watchlist_member",
            priority_rank=10,
            rank_components={"tier": 5},
            state="ready",
            reason_code=None,
            reason="Legacy ready snapshot.",
            source_type="stock_price",
            source_ref_id=price.id,
            evidence_json={
                "close": "88.0",
                "source": "twelvedata",
                "price_date": price_day.isoformat(),
                # Legacy rows did not prove authorization at persistence time.
            },
            observed_at=price.created_at,
            freshness_policy_version="eod-freshness-v1.0",
            evaluated_at=datetime.now(timezone.utc),
            next_action=None,
            is_current=True,
        )
    )
    db_session.commit()

    headers = auth_headers(user)
    listed = client.get("/api/v1/coverage/requirements", headers=headers)
    assert listed.status_code == 200, listed.text
    listed_price = listed.json()["items"][0]
    assert listed_price["state"] == "blocked"
    assert listed_price["reason_code"] == "source_unavailable"
    assert listed_price["evidence"]["close"] is None
    assert listed_price["evidence"]["source_authorization_state"] == "unavailable"

    created = client.post(
        "/api/v1/research/cases",
        headers=headers,
        json={
            "stock_id": stock.id,
            "origin": {
                "origin_type": "manual",
                "origin_key": f"coverage-legacy:{stock.id}",
                "source_version": "coverage-legacy-v1",
                "source_ref": {"test": True},
            },
        },
    )
    assert created.status_code == 201, created.text
    workspace = client.get(
        f"/api/v1/research/cases/{created.json()['case']['id']}/workspace",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    workspace_price = next(
        item for item in workspace.json()["coverage"] if item["kind"] == "eod_price"
    )
    assert workspace_price["state"] == "blocked"
    assert workspace_price["evidence"]["close"] is None


def test_persisted_authorized_price_is_redacted_after_provider_revocation(
    client, db_session, user_factory, auth_headers, monkeypatch
):
    from app.services import market_data_service
    from app.services.research_coverage import evaluate_research_coverage

    user = user_factory(email="coverage-revoked-redaction@example.com")
    stock = _stock(db_session, "REVOKED")
    _watchlist(db_session, user.id, stock)
    coverage_day = expected_session_on_or_before(
        stock.listing_exchange or stock.exchange,
        date.today() - timedelta(days=1),
    ).session_date
    assert coverage_day is not None
    _price(db_session, stock, price_date=coverage_day)
    evaluate_research_coverage(db_session, user_id=user.id, as_of=date.today())

    stored = db_session.query(ResearchCoverageRequirement).filter_by(
        user_id=user.id, stock_id=stock.id, kind="eod_price", is_current=True
    ).one()
    assert stored.state == "ready"
    assert stored.evidence_json["close"] == "100.0"
    assert stored.evidence_json["source_authorization_state"] == "authorized"

    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_PRIMARY", "none")
    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_SECONDARY", "none")
    monkeypatch.setattr(
        market_data_service.settings, "MARKET_DATA_COMMERCIAL_ENABLED", False
    )
    headers = auth_headers(user)
    listed = client.get("/api/v1/coverage/requirements", headers=headers)
    assert listed.status_code == 200, listed.text
    listed_price = next(
        item for item in listed.json()["items"] if item["kind"] == "eod_price"
    )
    assert listed_price["state"] == "blocked"
    assert listed_price["reason_code"] == "source_unavailable"
    assert listed_price["evidence"]["close"] is None
    assert listed_price["evidence"]["source_authorization_state"] == "unauthorized"

    created = client.post(
        "/api/v1/research/cases",
        headers=headers,
        json={
            "stock_id": stock.id,
            "origin": {
                "origin_type": "manual",
                "origin_key": f"coverage-revoked:{stock.id}",
                "source_version": "coverage-revoked-v1",
                "source_ref": {"test": True},
            },
        },
    )
    assert created.status_code == 201, created.text
    workspace = client.get(
        f"/api/v1/research/cases/{created.json()['case']['id']}/workspace",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    workspace_price = next(
        item for item in workspace.json()["coverage"] if item["kind"] == "eod_price"
    )
    assert workspace_price["state"] == "blocked"
    assert workspace_price["reason_code"] == "source_unavailable"
    assert workspace_price["evidence"]["close"] is None


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
    assert first.json()["requirements_evaluated"] == 2
    assert second.json()["requirements_evaluated"] == 2
    listing = client.get(
        "/api/v1/coverage/requirements", headers=auth_headers(user)
    ).json()
    assert len(listing["items"]) == 2


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
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["by_state"] == {"missing": 2}
    assert payload["summary"]["by_kind"] == {
        "eod_price": 1,
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
        name = "twelvedata"

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
