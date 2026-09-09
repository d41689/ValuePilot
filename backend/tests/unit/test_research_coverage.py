from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.models.artifacts import PdfDocument
from app.models.coverage import ResearchCoverageRequirement
from app.models.oracles_lens import OraclesLensSignal
from app.models.research import ResearchCase
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


def _value_line_doc(db_session, user_id: int, stock: Stock, *, report_date: date) -> PdfDocument:
    document = PdfDocument(
        user_id=user_id,
        stock_id=stock.id,
        file_name=f"{stock.ticker}.pdf",
        # This is the persisted source used by the normal upload endpoint.
        source="upload",
        file_storage_key=f"test/{user_id}/{stock.id}.pdf",
        parse_status="parsed",
        report_date=report_date,
    )
    db_session.add(document)
    db_session.flush()
    return document


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "unknown_provider"),
        ("parse_status", "unsupported_template"),
        ("identity_needs_review", True),
    ],
)
def test_noncanonical_value_line_document_never_satisfies_coverage(
    db_session, user_factory, field, value
):
    from app.services.research_coverage import evaluate_research_coverage

    user = user_factory(email=f"coverage-noncanonical-{field}@example.com")
    stock = _stock(db_session, f"NC{field[:4].upper()}")
    _watchlist(db_session, user.id, stock)
    document = _value_line_doc(
        db_session, user.id, stock, report_date=date(2026, 7, 1)
    )
    setattr(document, field, value)
    db_session.commit()

    evaluate_research_coverage(
        db_session, user_id=user.id, as_of=date(2026, 7, 20)
    )
    requirement = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(
            user_id=user.id,
            stock_id=stock.id,
            kind="value_line_current_report",
        )
        .one()
    )
    assert requirement.state == "missing"
    assert requirement.reason_code == "value_line_report_missing"


@pytest.mark.parametrize(
    ("lifecycle_field", "expected_state", "expected_reason"),
    [
        ("archived_at", "missing", "value_line_report_missing"),
        ("source_unavailable_at", "blocked", "source_unavailable"),
    ],
)
def test_retired_value_line_document_does_not_satisfy_current_coverage(
    db_session, user_factory, lifecycle_field, expected_state, expected_reason
):
    from app.services.research_coverage import evaluate_research_coverage

    user = user_factory(email=f"coverage-{lifecycle_field}@example.com")
    stock = _stock(db_session, f"RET{lifecycle_field[0].upper()}")
    _watchlist(db_session, user.id, stock)
    document = _value_line_doc(
        db_session, user.id, stock, report_date=date(2026, 7, 1)
    )
    setattr(document, lifecycle_field, datetime.now(timezone.utc))
    db_session.commit()

    evaluate_research_coverage(
        db_session, user_id=user.id, as_of=date(2026, 7, 20)
    )

    requirement = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(
            user_id=user.id,
            stock_id=stock.id,
            kind="value_line_current_report",
        )
        .one()
    )
    assert requirement.state == expected_state
    assert requirement.reason_code == expected_reason
    assert requirement.source_ref_id == document.id


@pytest.mark.parametrize(
    (
        "lifecycle_field",
        "expected_state",
        "expected_reason",
        "expected_text",
        "expected_action",
    ),
    [
        (
            "archived_at",
            "missing",
            "value_line_report_missing",
            "No parsed Value Line report owned by this user covers the stock.",
            "upload_value_line_report",
        ),
        (
            "source_unavailable_at",
            "inaccessible",
            "source_unavailable",
            "The retained Value Line source is no longer readable.",
            "review_source_authorization",
        ),
    ],
)
def test_retired_value_line_ready_projection_fails_closed_without_reevaluation(
    client,
    db_session,
    user_factory,
    auth_headers,
    lifecycle_field,
    expected_state,
    expected_reason,
    expected_text,
    expected_action,
):
    from app.models.research import ResearchInboxAction
    from app.services.research_coverage import evaluate_research_coverage

    user = user_factory(email=f"coverage-projected-{lifecycle_field}@example.com")
    stock = _stock(db_session, f"PRJ{lifecycle_field[0].upper()}")
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    document = _value_line_doc(
        db_session, user.id, stock, report_date=date.today()
    )
    db_session.flush()
    evaluate_research_coverage(
        db_session, user_id=user.id, as_of=date.today(), commit=False
    )
    requirement = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(
            user_id=user.id,
            stock_id=stock.id,
            kind="value_line_current_report",
        )
        .one()
    )
    assert requirement.state == "ready"
    setattr(document, lifecycle_field, datetime.now(timezone.utc))
    db_session.commit()

    listed = client.get(
        "/api/v1/coverage/requirements", headers=auth_headers(user)
    )
    workspace = client.get(
        f"/api/v1/research/cases/{case.id}/workspace", headers=auth_headers(user)
    )
    assert listed.status_code == 200, listed.text
    assert workspace.status_code == 200, workspace.text
    listed_requirement = next(
        item for item in listed.json()["items"] if item["id"] == requirement.id
    )
    workspace_requirement = next(
        item
        for item in workspace.json()["coverage"]
        if item["kind"] == "value_line_current_report"
    )
    for projected in (listed_requirement, workspace_requirement):
        assert projected["state"] == expected_state
        assert projected["reason_code"] == expected_reason
        assert projected["reason"] == expected_text
        assert projected["next_action"] == expected_action
        assert projected["source_ref_id"] == document.id

    regenerated = client.post(
        "/api/v1/research/inbox/regenerate", headers=auth_headers(user)
    )
    assert regenerated.status_code == 200, regenerated.text
    action = (
        db_session.query(ResearchInboxAction)
        .filter_by(
            user_id=user.id,
            logical_key=f"case-coverage:{case.id}:value_line_current_report",
            state="open",
        )
        .one()
    )
    assert action.evidence_json["state"] == expected_state
    assert action.evidence_json["reason_code"] == expected_reason
    assert action.evidence_json["reason"] == expected_text
    assert action.evidence_json["next_action"] == expected_action
    assert action.evidence_json["source_ref_id"] == document.id


def test_value_line_ready_projection_becomes_stale_at_day_121_everywhere(
    client, db_session, user_factory, auth_headers
):
    from app.models.research import ResearchInboxAction
    from app.services.research_coverage import evaluate_research_coverage

    user = user_factory(email="coverage-value-line-rollover@example.com")
    stock = _stock(db_session, "VLROLL")
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    projection_day = date.today()
    report_day = projection_day - timedelta(days=121)
    document = _value_line_doc(db_session, user.id, stock, report_date=report_day)
    db_session.flush()
    evaluate_research_coverage(
        db_session,
        user_id=user.id,
        as_of=report_day + timedelta(days=120),
        commit=False,
    )
    requirement = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(
            user_id=user.id,
            stock_id=stock.id,
            kind="value_line_current_report",
        )
        .one()
    )
    assert requirement.state == "ready"
    db_session.commit()

    listed = client.get(
        "/api/v1/coverage/requirements", headers=auth_headers(user)
    )
    workspace = client.get(
        f"/api/v1/research/cases/{case.id}/workspace", headers=auth_headers(user)
    )
    regenerated = client.post(
        "/api/v1/research/inbox/regenerate", headers=auth_headers(user)
    )
    assert listed.status_code == workspace.status_code == regenerated.status_code == 200
    projected_rows = [
        next(item for item in listed.json()["items"] if item["id"] == requirement.id),
        next(
            item
            for item in workspace.json()["coverage"]
            if item["kind"] == "value_line_current_report"
        ),
    ]
    for projected in projected_rows:
        assert projected["state"] == "stale"
        assert projected["reason_code"] == "value_line_report_older_than_policy"
        assert projected["reason"] == (
            "The latest user-owned Value Line report exceeds the 120-day policy."
        )
        assert projected["next_action"] == "upload_value_line_report"
        assert projected["source_ref_id"] == document.id

    action = (
        db_session.query(ResearchInboxAction)
        .filter_by(
            user_id=user.id,
            logical_key=f"case-coverage:{case.id}:value_line_current_report",
            state="open",
        )
        .one()
    )
    assert action.evidence_json["state"] == "stale"
    assert action.evidence_json["reason_code"] == "value_line_report_older_than_policy"
    assert action.evidence_json["next_action"] == "upload_value_line_report"
    assert action.evidence_json["source_ref_id"] == document.id


@pytest.mark.parametrize(
    ("field", "value", "reason_code", "reason"),
    [
        (
            "source",
            "unknown_provider",
            "value_line_report_missing",
            "No parsed Value Line report owned by this user covers the stock.",
        ),
        (
            "parse_status",
            "unsupported_template",
            "value_line_report_missing",
            "No parsed Value Line report owned by this user covers the stock.",
        ),
        (
            "identity_needs_review",
            True,
            "value_line_report_missing",
            "No parsed Value Line report owned by this user covers the stock.",
        ),
        (
            "report_date",
            None,
            "value_line_report_date_missing",
            "The parsed report has no source-backed report date.",
        ),
        (
            "report_date",
            date.today() + timedelta(days=1),
            "value_line_report_date_in_future",
            "The report date is later than the coverage evaluation date.",
        ),
    ],
)
def test_value_line_projection_and_regeneration_share_failure_vocabulary(
    client, db_session, user_factory, auth_headers, field, value, reason_code, reason
):
    from app.models.research import ResearchInboxAction
    from app.services.research_coverage import evaluate_research_coverage

    user = user_factory(email=f"coverage-vocabulary-{field}-{reason_code}@example.com")
    stock = _stock(db_session, f"MX{reason_code[-4:].upper()}")
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    document = _value_line_doc(db_session, user.id, stock, report_date=date.today())
    db_session.flush()
    evaluate_research_coverage(
        db_session, user_id=user.id, as_of=date.today(), commit=False
    )
    requirement = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(
            user_id=user.id,
            stock_id=stock.id,
            kind="value_line_current_report",
        )
        .one()
    )
    assert requirement.state == "ready"
    setattr(document, field, value)
    db_session.commit()

    listed = client.get("/api/v1/coverage/requirements", headers=auth_headers(user))
    workspace = client.get(
        f"/api/v1/research/cases/{case.id}/workspace", headers=auth_headers(user)
    )
    for projected in (
        next(item for item in listed.json()["items"] if item["id"] == requirement.id),
        next(
            item
            for item in workspace.json()["coverage"]
            if item["kind"] == "value_line_current_report"
        ),
    ):
        assert projected["reason_code"] == reason_code
        assert projected["reason"] == reason
        assert projected["next_action"] == "upload_value_line_report"

    regenerated = client.post(
        "/api/v1/research/inbox/regenerate", headers=auth_headers(user)
    )
    assert regenerated.status_code == 200, regenerated.text
    action = (
        db_session.query(ResearchInboxAction)
        .filter_by(
            user_id=user.id,
            logical_key=f"case-coverage:{case.id}:value_line_current_report",
            state="open",
        )
        .one()
    )
    assert action.evidence_json["reason_code"] == reason_code
    assert action.evidence_json["reason"] == reason
    assert action.evidence_json["next_action"] == "upload_value_line_report"


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
    assert listed_price["state"] == "inaccessible"
    assert listed_price["reason_code"] == "source_unavailable"
    assert listed_price["reason"] == (
        "The persisted price source is not currently authorized for display."
    )
    assert listed_price["evidence"]["close"] is None
    assert listed_price["evidence"]["source_authorization_state"] == "unavailable"

    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    db_session.commit()
    workspace = client.get(
        f"/api/v1/research/cases/{case.id}/workspace",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    workspace_price = next(
        item for item in workspace.json()["coverage"] if item["kind"] == "eod_price"
    )
    assert workspace_price["state"] == "inaccessible"
    assert workspace_price["reason"] == (
        "The persisted price source is not currently authorized for display."
    )
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
    assert listed_price["state"] == "inaccessible"
    assert listed_price["reason_code"] == "source_unavailable"
    assert listed_price["evidence"]["close"] is None
    assert listed_price["evidence"]["source_authorization_state"] == "unauthorized"

    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    db_session.commit()
    workspace = client.get(
        f"/api/v1/research/cases/{case.id}/workspace",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    workspace_price = next(
        item for item in workspace.json()["coverage"] if item["kind"] == "eod_price"
    )
    assert workspace_price["state"] == "inaccessible"
    assert workspace_price["reason_code"] == "source_unavailable"
    assert workspace_price["evidence"]["close"] is None


def test_legacy_ready_price_with_non_iso_currency_is_blocked_on_every_projection(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="coverage-invalid-currency@example.com")
    stock = _stock(db_session, "BADCCOV")
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
        currency="ZZZ",
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
                "currency": "ZZZ",
                "source": "twelvedata",
                "source_authorization_state": "authorized",
                "price_date": price_day.isoformat(),
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
    assert listed_price["reason_code"] == "price_currency_unavailable"
    assert listed_price["evidence"]["close"] is None
    assert listed_price["evidence"]["currency"] is None
    assert listed_price["evidence"]["source_authorization_state"] == "authorized"

    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    db_session.commit()
    workspace = client.get(
        f"/api/v1/research/cases/{case.id}/workspace",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    workspace_price = next(
        item for item in workspace.json()["coverage"] if item["kind"] == "eod_price"
    )
    missing_price = next(
        item
        for item in workspace.json()["missing_items"]
        if item["kind"] == "eod_price"
    )
    assert workspace_price == missing_price
    assert workspace_price["state"] == "blocked"
    assert workspace_price["reason_code"] == "price_currency_unavailable"
    assert workspace_price["evidence"]["close"] is None
    assert workspace_price["evidence"]["currency"] is None


@pytest.mark.parametrize(
    ("stored_source", "evidence_source", "configured_source"),
    [
        ("yahoo", "yfinance", "yfinance"),
        ("yfinance", "yahoo", "yfinance"),
        ("twelve_data", "12data", "twelvedata"),
        ("12data", "twelvedata", "twelvedata"),
        ("twelvedata", "twelve_data", "twelvedata"),
    ],
)
def test_ready_price_source_aliases_match_across_every_projection(
    client,
    db_session,
    user_factory,
    auth_headers,
    monkeypatch,
    stored_source,
    evidence_source,
    configured_source,
):
    from app.models.notifications import LogicalNotification
    from app.services import market_data_service
    from app.services.research_notifications import materialize_research_coverage_changes

    monkeypatch.setattr(
        market_data_service.settings, "MARKET_DATA_PRIMARY", configured_source
    )
    if configured_source == "yfinance":
        monkeypatch.setattr(
            market_data_service.settings,
            "MARKET_DATA_ALLOW_DEVELOPMENT_PROVIDER",
            True,
        )

    user = user_factory(
        email=f"coverage-source-alias-{stored_source}-{evidence_source}@example.com"
    )
    stock = _stock(db_session, "ALIAS")
    _watchlist(db_session, user.id, stock)
    expected_day = compute_target_date(datetime.now(timezone.utc).astimezone(ET))
    price = StockPrice(
        stock_id=stock.id,
        price_date=expected_day,
        open=88,
        high=89,
        low=87,
        close=88,
        volume=1_000,
        currency="USD",
        source=stored_source,
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
            state="ready",
            reason="The aliased source is authorized.",
            source_type="stock_price",
            source_ref_id=price.id,
            evidence_json={
                "close": "88.0",
                "currency": "USD",
                "source": evidence_source,
                "source_authorization_state": "authorized",
                "price_date": expected_day.isoformat(),
            },
            observed_at=price.created_at,
            freshness_policy_version="eod-freshness-v1.0",
            evaluated_at=datetime.now(timezone.utc),
            is_current=True,
        )
    )
    db_session.commit()

    headers = auth_headers(user)
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    db_session.commit()

    listed = client.get(
        "/api/v1/coverage/requirements", headers=headers
    ).json()["items"][0]
    workspace = client.get(
        f"/api/v1/research/cases/{case.id}/workspace",
        headers=headers,
    ).json()
    workspace_price = next(
        item for item in workspace["coverage"] if item["kind"] == "eod_price"
    )

    assert listed["state"] == "ready"
    assert workspace_price["state"] == "ready"
    assert listed["evidence"]["source"] == evidence_source
    assert workspace_price["evidence"]["source"] == evidence_source
    assert not any(item["kind"] == "eod_price" for item in workspace["missing_items"])
    assert materialize_research_coverage_changes(db_session) == 1
    notification = db_session.query(LogicalNotification).one()
    assert notification.event_family == "research_coverage_changed"
    assert notification.payload_json["state"] == "ready"


def test_ready_price_coverage_becomes_stale_after_session_rolls_without_reevaluation(
    client, db_session, user_factory, auth_headers
):
    from app.models.notifications import LogicalNotification
    from app.services.research_notifications import materialize_research_coverage_changes

    user = user_factory(email="coverage-session-roll@example.com")
    stock = _stock(db_session, "ROLL")
    _watchlist(db_session, user.id, stock)
    expected_day = compute_target_date(datetime.now(timezone.utc).astimezone(ET))
    stale_day = expected_session_on_or_before(
        stock.listing_exchange or stock.exchange,
        expected_day - timedelta(days=1),
    ).session_date
    assert stale_day is not None
    stale_price = StockPrice(
        stock_id=stock.id,
        price_date=stale_day,
        open=88,
        high=89,
        low=87,
        close=88,
        volume=1_000,
        currency="USD",
        source="twelvedata",
    )
    db_session.add(stale_price)
    db_session.flush()
    db_session.add(
        ResearchCoverageRequirement(
            user_id=user.id,
            stock_id=stock.id,
            kind="eod_price",
            priority_policy_version="research-coverage-priority-v1.0",
            matched_rule="watchlist_member",
            priority_rank=10,
            state="ready",
            reason="The prior evaluation marked this ready.",
            source_type="stock_price",
            source_ref_id=stale_price.id,
            evidence_json={
                "close": "88.0",
                "currency": "USD",
                "source": "twelvedata",
                "source_authorization_state": "authorized",
                "price_date": stale_day.isoformat(),
            },
            observed_at=stale_price.created_at,
            freshness_policy_version="eod-freshness-v1.0",
            evaluated_at=datetime.now(timezone.utc) - timedelta(days=1),
            is_current=True,
        )
    )
    db_session.commit()

    headers = auth_headers(user)
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    db_session.commit()

    listed = client.get(
        "/api/v1/coverage/requirements", headers=headers
    ).json()["items"][0]
    workspace = client.get(
        f"/api/v1/research/cases/{case.id}/workspace",
        headers=headers,
    ).json()
    missing = next(
        item for item in workspace["missing_items"] if item["kind"] == "eod_price"
    )
    assert listed["state"] == "stale"
    assert listed["reason_code"] == "price_older_than_expected_session"
    assert listed["evidence"]["close"] is None
    assert missing["state"] == "stale"
    assert missing["reason_code"] == "price_older_than_expected_session"
    assert materialize_research_coverage_changes(db_session) == 0
    assert db_session.query(LogicalNotification).count() == 0


def test_ready_price_coverage_blocks_reference_date_and_canonical_id_mismatch(
    client, db_session, user_factory, auth_headers
):
    from app.models.notifications import LogicalNotification
    from app.services.research_notifications import materialize_research_coverage_changes

    user = user_factory(email="coverage-reference-mismatch@example.com")
    stock = _stock(db_session, "REFMISS")
    _watchlist(db_session, user.id, stock)
    expected_day = compute_target_date(datetime.now(timezone.utc).astimezone(ET))
    prior_day = expected_session_on_or_before(
        stock.listing_exchange or stock.exchange,
        expected_day - timedelta(days=1),
    ).session_date
    assert prior_day is not None
    referenced = StockPrice(
        stock_id=stock.id,
        price_date=prior_day,
        open=90,
        high=91,
        low=89,
        close=90,
        volume=1_000,
        currency="USD",
        source="twelvedata",
    )
    canonical = StockPrice(
        stock_id=stock.id,
        price_date=expected_day,
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1_000,
        currency="USD",
        source="twelvedata",
    )
    db_session.add_all([referenced, canonical])
    db_session.flush()
    db_session.add(
        ResearchCoverageRequirement(
            user_id=user.id,
            stock_id=stock.id,
            kind="eod_price",
            priority_policy_version="research-coverage-priority-v1.0",
            matched_rule="watchlist_member",
            priority_rank=10,
            state="ready",
            reason="The prior evaluation cited the wrong observation.",
            source_type="stock_price",
            source_ref_id=referenced.id,
            evidence_json={
                "close": "90.0",
                "currency": "USD",
                "source": "twelvedata",
                "source_authorization_state": "authorized",
                "price_date": expected_day.isoformat(),
            },
            observed_at=referenced.created_at,
            freshness_policy_version="eod-freshness-v1.0",
            evaluated_at=datetime.now(timezone.utc),
            is_current=True,
        )
    )
    db_session.commit()

    headers = auth_headers(user)
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    db_session.commit()

    listed = client.get(
        "/api/v1/coverage/requirements", headers=headers
    ).json()["items"][0]
    workspace = client.get(
        f"/api/v1/research/cases/{case.id}/workspace",
        headers=headers,
    ).json()
    missing = next(
        item for item in workspace["missing_items"] if item["kind"] == "eod_price"
    )
    assert listed["state"] == "blocked"
    assert listed["reason_code"] == "price_reference_mismatch"
    assert listed["evidence"]["close"] is None
    assert missing["state"] == "blocked"
    assert missing["reason_code"] == "price_reference_mismatch"
    assert materialize_research_coverage_changes(db_session) == 0
    assert db_session.query(LogicalNotification).count() == 0


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
    from app.services.canonical_financials import (
        database_evaluation_cutoff,
        evaluation_business_date,
    )

    historical_day = (
        evaluation_business_date(database_evaluation_cutoff(db_session))
        - timedelta(days=1)
    )

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


def test_case_create_and_repeat_open_materialize_current_coverage_once(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="coverage-case-create@example.com")
    stock = _stock(db_session, "CASEAUTO")
    payload = {
        "stock_id": stock.id,
        "origin": {
            "origin_type": "manual",
            "origin_key": "case-auto",
            "source_version": "case-auto-v1",
            "source_ref": {"entry_point": "test"},
        },
    }

    first = client.post(
        "/api/v1/research/cases", headers=auth_headers(user), json=payload
    )
    second = client.post(
        "/api/v1/research/cases", headers=auth_headers(user), json=payload
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json()["case"]["id"] == second.json()["case"]["id"]
    requirements = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(user_id=user.id, stock_id=stock.id, is_current=True)
        .order_by(ResearchCoverageRequirement.kind)
        .all()
    )
    assert [row.kind for row in requirements] == [
        "eod_price",
        "valuation_input",
        "value_line_current_report",
    ]
    assert len({(row.kind, row.priority_policy_version) for row in requirements}) == 3


def test_case_coverage_projects_source_loss_and_method_denial_without_new_storage_states(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="coverage-projection-states@example.com")
    stock = _stock(db_session, "TYPED")
    created = client.post(
        "/api/v1/research/cases",
        headers=auth_headers(user),
        json={
            "stock_id": stock.id,
            "origin": {
                "origin_type": "manual",
                "origin_key": "typed-states",
                "source_version": "typed-states-v1",
            },
        },
    )
    assert created.status_code == 201, created.text
    price = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(user_id=user.id, stock_id=stock.id, kind="eod_price")
        .one()
    )
    price.state = "blocked"
    price.reason_code = "source_unavailable"
    price.reason = "The canonical source is no longer readable."
    price.next_action = "review_source_authorization"
    db_session.commit()

    workspace = client.get(
        f"/api/v1/research/cases/{created.json()['case']['id']}/workspace",
        headers=auth_headers(user),
    )

    assert workspace.status_code == 200, workspace.text
    by_kind = {item["kind"]: item for item in workspace.json()["coverage"]}
    assert by_kind["eod_price"]["state"] == "inaccessible"
    assert by_kind["eod_price"]["reason_code"] == "source_unavailable"
    assert by_kind["valuation_input"]["state"] == "unsupported"
    assert by_kind["valuation_input"]["reason_code"]
    assert by_kind["valuation_input"]["evidence"]["method_gate"]["status"] == "unsupported"


def test_inbox_regeneration_materializes_coverage_and_keeps_unchanged_source_version(
    client, db_session, user_factory, auth_headers
):
    from app.models.research import ResearchCase, ResearchInboxAction

    user = user_factory(email="coverage-inbox-auto@example.com")
    stock = _stock(db_session, "IBAUTO")
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    db_session.commit()

    first = client.post(
        "/api/v1/research/inbox/regenerate", headers=auth_headers(user)
    )
    first_actions = (
        db_session.query(ResearchInboxAction)
        .filter_by(user_id=user.id, action_family="coverage_gap")
        .order_by(ResearchInboxAction.id)
        .all()
    )
    first_ids = [row.id for row in first_actions]
    second = client.post(
        "/api/v1/research/inbox/regenerate", headers=auth_headers(user)
    )
    second_actions = (
        db_session.query(ResearchInboxAction)
        .filter_by(user_id=user.id, action_family="coverage_gap")
        .order_by(ResearchInboxAction.id)
        .all()
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first_ids
    assert [row.id for row in second_actions] == first_ids
    assert all(row.state == "open" for row in second_actions)
    evidence = second_actions[0].evidence_json
    assert {
        "kind",
        "state",
        "reason",
        "source_type",
        "source_ref_id",
        "freshness_policy_version",
        "as_of",
        "evaluated_at",
        "next_action",
    } <= set(evidence)


def test_coverage_endpoint_uses_database_business_date_at_utc_boundary(
    client, db_session, user_factory, auth_headers, monkeypatch
):
    from app.api.v1.endpoints import coverage as coverage_endpoint

    user = user_factory(email="coverage-db-clock@example.com")
    stock = _stock(db_session, "DBCLOCK")
    _watchlist(db_session, user.id, stock)
    evaluated_at = datetime(2026, 9, 7, 0, 30, tzinfo=timezone.utc)
    expected_date = evaluated_at.astimezone(ZoneInfo("America/New_York")).date()
    monkeypatch.setattr(
        coverage_endpoint,
        "database_evaluation_cutoff",
        lambda _session: evaluated_at,
        raising=False,
    )

    response = client.post(
        f"/api/v1/coverage/evaluate?as_of={expected_date.isoformat()}",
        headers=auth_headers(user),
    )

    assert response.status_code == 200, response.text
    assert response.json()["as_of"] == expected_date.isoformat()
    stored = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(user_id=user.id, stock_id=stock.id, kind="eod_price")
        .one()
    )
    assert stored.evaluated_at == evaluated_at


def test_current_business_date_price_read_keeps_exact_utc_knowledge_cutoff(
    db_session, user_factory
):
    from app.services.canonical_financials import evaluation_business_date
    from app.services.research_coverage import evaluate_research_coverage

    user = user_factory(email="coverage-exact-cutoff@example.com")
    stock = _stock(db_session, "EXACTCUT")
    _watchlist(db_session, user.id, stock)
    evaluated_at = datetime(2026, 9, 7, 0, 30, tzinfo=timezone.utc)
    as_of = evaluation_business_date(evaluated_at)
    session_date = expected_session_on_or_before(stock.exchange, as_of).session_date
    before_cutoff = StockPrice(
        stock_id=stock.id,
        price_date=session_date,
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1_000,
        currency="USD",
        source="twelvedata",
        created_at=evaluated_at - timedelta(minutes=15),
    )
    after_cutoff = StockPrice(
        stock_id=stock.id,
        price_date=session_date,
        open=200,
        high=201,
        low=199,
        close=200,
        volume=1_000,
        currency="USD",
        source="twelvedata",
        created_at=evaluated_at + timedelta(minutes=15),
    )
    db_session.add_all([before_cutoff, after_cutoff])
    db_session.flush()

    evaluate_research_coverage(
        db_session,
        user_id=user.id,
        as_of=as_of,
        include_as_of_session=True,
        evaluated_at=evaluated_at,
    )

    price_requirement = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(user_id=user.id, stock_id=stock.id, kind="eod_price")
        .one()
    )
    assert price_requirement.source_ref_id == before_cutoff.id
    assert price_requirement.evidence_json["close"] == "100.0"
