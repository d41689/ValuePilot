from __future__ import annotations

from datetime import date, timedelta

from app.models.oracles_lens import OraclesLensSignal
from app.models.research import ResearchCase, ResearchInboxAction, ResearchInboxActionEvent
from app.models.stocks import PoolMembership, Stock, StockPool
from app.services.oracles_lens.constants import SCORE_VERSION


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
    pool = StockPool(user_id=user_id, name=f"Watch {stock.ticker}")
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


def test_inbox_regeneration_is_idempotent_explainable_and_prioritized(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="inbox-priority@example.com")
    own = _stock(db_session, "IBOWN")
    watch = _stock(db_session, "IBWAT")
    researching = _stock(db_session, "IBRES")
    queued = _stock(db_session, "IBQUE")
    candidate = _stock(db_session, "IBCAN")
    lens = _stock(db_session, "IBLEN")
    db_session.add_all(
        [
            ResearchCase(
                user_id=user.id,
                stock_id=own.id,
                state="monitoring",
                decision="own",
                next_review_on=date(2026, 7, 19),
            ),
            ResearchCase(
                user_id=user.id,
                stock_id=watch.id,
                state="monitoring",
                decision="watch",
                next_review_on=date(2026, 7, 20),
            ),
            ResearchCase(user_id=user.id, stock_id=researching.id, state="researching"),
            ResearchCase(user_id=user.id, stock_id=queued.id, state="queued"),
        ]
    )
    _watchlist(db_session, user.id, candidate)
    db_session.add(
        OraclesLensSignal(
            stock_id=lens.id,
            report_quarter="2026-Q1",
            quarter_end_date=date(2026, 3, 31),
            score_version=SCORE_VERSION,
            raw_consensus_count=3,
            signal_weighted_consensus_score=3,
            distinctive_consensus_score=2,
            score_confidence="high_confidence",
            caution_flag_codes=[],
            score_explanation={},
            computed_at=date(2026, 5, 15),
        )
    )
    db_session.commit()

    first = client.post(
        "/api/v1/research/inbox/regenerate?as_of=2026-07-20&lens=consensus",
        headers=auth_headers(user),
    )
    second = client.post(
        "/api/v1/research/inbox/regenerate?as_of=2026-07-20&lens=consensus",
        headers=auth_headers(user),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    listing = client.get(
        "/api/v1/research/inbox", headers=auth_headers(user)
    ).json()
    assert [item["ticker"] for item in listing["items"]] == [
        "IBOWN",
        "IBWAT",
        "IBRES",
        "IBQUE",
        "IBCAN",
        "IBLEN",
    ]
    assert [item["matched_rule"] for item in listing["items"]] == [
        "owned_review_overdue",
        "watch_review_due",
        "research_incomplete",
        "case_queued",
        "watchlist_without_case",
        "oracles_lens_consensus_candidate",
    ]
    assert all(item["reason"] for item in listing["items"])
    assert db_session.query(ResearchInboxAction).count() == 6
    # Regeneration observes an unchanged projection without noisy audit events.
    assert db_session.query(ResearchInboxActionEvent).count() == 6


def test_inbox_snooze_is_bounded_dismissal_is_informational_only_and_audited(
    client, db_session, user_factory, auth_headers
):
    today = date.today()
    valid_snooze_date = today + timedelta(days=30)
    invalid_snooze_date = today + timedelta(days=31)
    user = user_factory(email="inbox-actions@example.com")
    due_stock = _stock(db_session, "DUE")
    candidate_stock = _stock(db_session, "DISC")
    db_session.add(
        ResearchCase(
            user_id=user.id,
            stock_id=due_stock.id,
            state="monitoring",
            decision="own",
            next_review_on=date(2026, 7, 1),
        )
    )
    _watchlist(db_session, user.id, candidate_stock)
    db_session.commit()
    client.post(
        "/api/v1/research/inbox/regenerate?as_of=2026-07-20",
        headers=auth_headers(user),
    )
    rows = db_session.query(ResearchInboxAction).all()
    due = next(row for row in rows if row.action_family == "review_due")
    candidate = next(row for row in rows if row.action_family == "candidate_discovery")

    too_long = client.post(
        f"/api/v1/research/inbox/{due.id}/snooze",
        headers=auth_headers(user),
        json={"snoozed_until": invalid_snooze_date.isoformat()},
    )
    snoozed = client.post(
        f"/api/v1/research/inbox/{due.id}/snooze",
        headers=auth_headers(user),
        json={"snoozed_until": valid_snooze_date.isoformat()},
    )
    cannot_dismiss = client.post(
        f"/api/v1/research/inbox/{due.id}/dismiss",
        headers=auth_headers(user),
    )
    dismissed = client.post(
        f"/api/v1/research/inbox/{candidate.id}/dismiss",
        headers=auth_headers(user),
    )

    assert too_long.status_code == 422
    assert snoozed.status_code == 200, snoozed.text
    assert cannot_dismiss.status_code == 422
    assert dismissed.status_code == 200, dismissed.text
    assert db_session.get(ResearchInboxAction, due.id).state == "snoozed"
    assert db_session.get(ResearchInboxAction, candidate.id).state == "dismissed"
    assert (
        db_session.query(ResearchInboxActionEvent)
        .filter(ResearchInboxActionEvent.event_type.in_(["snoozed", "dismissed"]))
        .count()
        == 2
    )

    client.post(
        f"/api/v1/research/inbox/regenerate?as_of={(valid_snooze_date + timedelta(days=1)).isoformat()}",
        headers=auth_headers(user),
    )
    assert db_session.get(ResearchInboxAction, due.id).state == "open"
    # Same informational source version remains dismissed.
    assert db_session.get(ResearchInboxAction, candidate.id).state == "dismissed"


def test_inbox_source_version_supersedes_old_action_without_deleting_history(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="inbox-version@example.com")
    stock = _stock(db_session, "VERS")
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="researching")
    db_session.add(case)
    db_session.commit()

    client.post(
        "/api/v1/research/inbox/regenerate?as_of=2026-07-20",
        headers=auth_headers(user),
    )
    old = db_session.query(ResearchInboxAction).filter_by(user_id=user.id).one()
    case.head_revision_number = 1
    case.version = 2
    db_session.commit()
    client.post(
        "/api/v1/research/inbox/regenerate?as_of=2026-07-20",
        headers=auth_headers(user),
    )

    actions = (
        db_session.query(ResearchInboxAction)
        .filter_by(user_id=user.id)
        .order_by(ResearchInboxAction.id)
        .all()
    )
    assert len(actions) == 2
    assert actions[0].id == old.id
    assert actions[0].state == "superseded"
    assert actions[1].state == "open"
    assert actions[1].supersedes_action_id == old.id


def test_inbox_is_user_scoped_and_cross_user_action_is_404(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory(email="inbox-owner@example.com")
    other = user_factory(email="inbox-other@example.com")
    stock = _stock(db_session, "IBPRIV")
    db_session.add(ResearchCase(user_id=owner.id, stock_id=stock.id, state="queued"))
    db_session.commit()
    client.post(
        "/api/v1/research/inbox/regenerate?as_of=2026-07-20",
        headers=auth_headers(owner),
    )
    action = db_session.query(ResearchInboxAction).filter_by(user_id=owner.id).one()

    result = client.post(
        f"/api/v1/research/inbox/{action.id}/complete",
        headers=auth_headers(other),
    )

    assert result.status_code == 404
    assert client.get(
        "/api/v1/research/inbox", headers=auth_headers(other)
    ).json()["items"] == []
