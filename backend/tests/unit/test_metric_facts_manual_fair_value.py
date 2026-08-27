from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.models.users import User
from app.models.stocks import PoolMembership, Stock, StockPool
from app.models.facts import MetricFact
from app.models.research import ResearchCase, ResearchCaseRevision
from app.core.security import hash_password


FAIR_VALUE_KEY = "val.fair_value"
ET = ZoneInfo("America/New_York")


def _make_user(db_session, email: str = "fairvalue@example.com") -> User:
    user = User(email=email, hashed_password=hash_password("TestPass123!"))
    db_session.add(user)
    db_session.commit()
    return user


def _make_stock(db_session, ticker: str) -> Stock:
    stock = Stock(ticker=ticker, exchange="NYSE", company_name=f"{ticker} Inc")
    db_session.add(stock)
    db_session.commit()
    return stock


def test_put_fair_value_preserves_prior_period_and_demotes_only_same_day_slot(
    client, db_session, auth_headers
):
    user = _make_user(db_session)
    stock = _make_stock(db_session, "FVR")
    headers = auth_headers(user)

    today_et = datetime.now(timezone.utc).astimezone(ET).date()
    prior_period_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=100.0,
        unit="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 2, 1),
        source_type="manual",
        is_current=True,
    )
    same_day_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=110.0,
        unit="USD",
        period_type="AS_OF",
        period_end_date=today_et,
        source_type="manual",
        is_current=True,
    )
    db_session.add_all([prior_period_fact, same_day_fact])
    db_session.commit()

    resp = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=headers,
        json={"metric_key": FAIR_VALUE_KEY, "value_numeric": 125.0},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["metric_key"] == FAIR_VALUE_KEY
    assert payload["value_numeric"] == 125.0
    assert payload["is_current"] is True
    assert payload["research_case_id"] is not None
    assert payload["research_revision_id"] is not None

    facts = (
        db_session.query(MetricFact)
        .filter(MetricFact.user_id == user.id, MetricFact.stock_id == stock.id, MetricFact.metric_key == FAIR_VALUE_KEY)
        .order_by(MetricFact.created_at.asc())
        .all()
    )
    assert len(facts) == 3
    by_value = {fact.value_numeric: fact for fact in facts}
    assert by_value[100.0].is_current is True
    assert by_value[110.0].is_current is False
    assert by_value[125.0].is_current is True
    assert by_value[125.0].source_ref_id == payload["research_revision_id"]

    case = db_session.get(ResearchCase, payload["research_case_id"])
    revision = db_session.get(ResearchCaseRevision, payload["research_revision_id"])
    assert case is not None
    assert case.user_id == user.id
    assert case.stock_id == stock.id
    assert case.head_revision_number == 1
    assert revision is not None
    assert revision.case_id == case.id
    assert revision.valuation_low == revision.valuation_base == revision.valuation_high
    assert float(revision.valuation_base) == 125.0
    assert revision.valuation_currency == "USD"


def test_put_dcf_value_copies_labeled_assumptions_into_research_revision(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "fairvalue-dcf@example.com")
    stock = _make_stock(db_session, "DCFJ")

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json={
            "metric_key": FAIR_VALUE_KEY,
            "value_numeric": 150.0,
            "valuation_low": 120.0,
            "valuation_high": 180.0,
            "source": "dcf",
            "assumptions": [
                {
                    "source": "dcf",
                    "label": "DCF model inputs",
                    "discount_rate_pct": 10.0,
                    "growth_rate_pct": 6.0,
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    revision = db_session.get(
        ResearchCaseRevision, response.json()["research_revision_id"]
    )
    assert revision is not None
    assert [float(revision.valuation_low), float(revision.valuation_base), float(revision.valuation_high)] == [
        120.0,
        150.0,
        180.0,
    ]
    assert revision.assumptions_json == [
        {
            "source": "dcf",
            "label": "DCF model inputs",
            "discount_rate_pct": 10.0,
            "growth_rate_pct": 6.0,
        }
    ]


def test_put_fair_value_reopens_monitoring_case_for_explicit_review(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "fairvalue-review@example.com")
    stock = _make_stock(db_session, "REVW")
    pool = StockPool(user_id=user.id, name="Review candidates")
    db_session.add(pool)
    db_session.flush()
    db_session.add(
        PoolMembership(
            user_id=user.id,
            pool_id=pool.id,
            stock_id=stock.id,
            inclusion_type="manual",
        )
    )
    case = ResearchCase(
        user_id=user.id,
        stock_id=stock.id,
        state="monitoring",
        decision="watch",
        next_review_on=date(2026, 10, 1),
        head_revision_number=1,
    )
    db_session.add(case)
    db_session.flush()
    db_session.add(
        ResearchCaseRevision(
            case_id=case.id,
            revision_number=1,
            thesis="Original monitoring thesis",
            risks_json=[{"label": "Competition"}],
            evidence_json=[{"source_type": "user_note", "label": "Note", "claim": "Evidence"}],
            case_state="monitoring",
            valuation_low=90,
            valuation_base=100,
            valuation_high=110,
            valuation_currency="USD",
            valuation_as_of_date=date(2026, 7, 17),
            decision="watch",
            next_review_on=date(2026, 10, 1),
            snapshot_stock_id=stock.id,
            stock_ticker=stock.ticker,
            stock_company_name=stock.company_name,
            stock_exchange=stock.exchange,
            created_by_user_id=user.id,
        )
    )
    db_session.commit()

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json={
            "metric_key": FAIR_VALUE_KEY,
            "value_numeric": 140.0,
            "valuation_low": 120.0,
            "valuation_high": 160.0,
            "source": "watchlist",
            "pool_id": pool.id,
        },
    )

    assert response.status_code == 200, response.text
    db_session.refresh(case)
    assert case.state == "researching"
    assert case.decision is None
    assert case.next_review_on is None
    latest = db_session.get(
        ResearchCaseRevision, response.json()["research_revision_id"]
    )
    assert latest is not None
    assert latest.case_state == "researching"
    assert latest.decision is None


def test_put_fair_value_rejects_unknown_metric_key(client, db_session, auth_headers):
    user = _make_user(db_session, "fairvalue2@example.com")
    stock = _make_stock(db_session, "BAD")
    headers = auth_headers(user)

    resp = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=headers,
        json={"metric_key": "val.unknown", "value_numeric": 10.0},
    )
    assert resp.status_code == 400
