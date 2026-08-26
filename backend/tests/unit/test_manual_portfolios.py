from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.models.portfolios import ManualPortfolio, ManualPosition, PositionJournalEvent
from app.models.research import ResearchCase, ResearchCaseRevision
from app.models.stocks import Stock, StockPrice
from app.schemas.portfolios import (
    ManualPortfolioCreate,
    ManualPositionClose,
    ManualPositionCreate,
    ManualPositionResize,
    ManualPositionReview,
)
from app.services.manual_portfolios import (
    PortfolioError,
    close_position,
    create_portfolio,
    create_position,
    get_portfolio_workspace,
    record_position_review,
    resize_position,
)


def _stock(db_session, ticker="LONG", *, active=True):
    stock = Stock(
        ticker=ticker,
        exchange="NASDAQ",
        company_name=f"{ticker} Holdings",
        security_type="Common Stock",
        is_active=active,
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _portfolio(db_session, user_id):
    return create_portfolio(
        db_session,
        user_id=user_id,
        payload=ManualPortfolioCreate(name="Long-term holdings"),
    )


def test_open_resize_review_close_is_decimal_versioned_and_append_only(
    db_session, user_factory
):
    user = user_factory("portfolio-owner@example.com")
    stock = _stock(db_session)
    portfolio = _portfolio(db_session, user.id)

    position = create_position(
        db_session,
        user_id=user.id,
        portfolio_id=portfolio.id,
        payload=ManualPositionCreate(
            stock_id=stock.id,
            quantity=Decimal("12.34567890"),
            average_unit_cost=Decimal("98.123456"),
            currency="usd",
            opened_on=date(2026, 7, 1),
            reason="Initial manual record; no broker synchronization.",
        ),
    )
    assert position.quantity == Decimal("12.34567890")
    assert position.average_unit_cost == Decimal("98.123456")
    assert position.currency == "USD"
    assert position.version == 1

    position = resize_position(
        db_session,
        user_id=user.id,
        position_id=position.id,
        payload=ManualPositionResize(
            expected_version=1,
            quantity=Decimal("15.00000000"),
            average_unit_cost=Decimal("102.000000"),
            reason="Added after independent review.",
        ),
    )
    assert position.version == 2
    position = record_position_review(
        db_session,
        user_id=user.id,
        position_id=position.id,
        payload=ManualPositionReview(
            expected_version=2,
            reviewed_on=date(2026, 7, 20),
            reason="Thesis remains intact; no action.",
        ),
    )
    assert position.version == 3
    position = close_position(
        db_session,
        user_id=user.id,
        position_id=position.id,
        payload=ManualPositionClose(
            expected_version=3,
            closed_on=date(2026, 7, 21),
            reason="Thesis invalidated; this is a journal event, not an execution record.",
        ),
    )
    assert position.state == "closed"
    assert position.quantity == Decimal("0")
    assert position.version == 4
    events = (
        db_session.query(PositionJournalEvent)
        .filter_by(position_id=position.id)
        .order_by(PositionJournalEvent.sequence_number)
        .all()
    )
    assert [event.event_type for event in events] == ["open", "resize", "review", "close"]
    assert events[0].new_quantity == Decimal("12.34567890")
    assert events[-1].recorded_ticker == "LONG"


def test_short_zero_and_currencyless_cost_are_rejected(db_session, user_factory):
    user = user_factory("portfolio-validation@example.com")
    stock = _stock(db_session, "SAFE")
    portfolio = _portfolio(db_session, user.id)

    for quantity in [Decimal("0"), Decimal("-1")]:
        with pytest.raises(ValueError):
            ManualPositionCreate(
                stock_id=stock.id,
                quantity=quantity,
                currency="USD",
                opened_on=date(2026, 7, 1),
            )
    with pytest.raises(ValueError):
        ManualPositionCreate(
            stock_id=stock.id,
            quantity=Decimal("1"),
            average_unit_cost=Decimal("20"),
            currency="US",
            opened_on=date(2026, 7, 1),
        )


def test_position_writers_reject_stale_version_without_partial_event(
    db_session, user_factory
):
    user = user_factory("portfolio-conflict@example.com")
    stock = _stock(db_session, "LOCK")
    portfolio = _portfolio(db_session, user.id)
    position = create_position(
        db_session,
        user_id=user.id,
        portfolio_id=portfolio.id,
        payload=ManualPositionCreate(
            stock_id=stock.id,
            quantity=Decimal("2"),
            currency="USD",
            opened_on=date(2026, 7, 1),
        ),
    )
    with pytest.raises(PortfolioError) as error:
        resize_position(
            db_session,
            user_id=user.id,
            position_id=position.id,
            payload=ManualPositionResize(
                expected_version=2,
                quantity=Decimal("3"),
            ),
        )
    assert error.value.status_code == 409
    assert db_session.query(PositionJournalEvent).filter_by(position_id=position.id).count() == 1


def test_research_link_must_match_user_stock_and_revision(db_session, user_factory):
    owner = user_factory("portfolio-research-owner@example.com")
    other = user_factory("portfolio-research-other@example.com")
    stock = _stock(db_session, "CASE")
    portfolio = _portfolio(db_session, owner.id)
    foreign_case = ResearchCase(user_id=other.id, stock_id=stock.id, state="queued")
    db_session.add(foreign_case)
    db_session.commit()

    with pytest.raises(PortfolioError, match="research case"):
        create_position(
            db_session,
            user_id=owner.id,
            portfolio_id=portfolio.id,
            payload=ManualPositionCreate(
                stock_id=stock.id,
                quantity=Decimal("1"),
                currency="USD",
                opened_on=date(2026, 7, 1),
                research_case_id=foreign_case.id,
            ),
        )


def test_workspace_exposes_overdue_review_calendar_and_recorded_vs_current_thesis(
    db_session, user_factory
):
    user = user_factory("portfolio-review-calendar@example.com")
    stock = _stock(db_session, "REVIEW")
    portfolio = _portfolio(db_session, user.id)
    case = ResearchCase(
        user_id=user.id,
        stock_id=stock.id,
        state="monitoring",
        decision="own",
        next_review_on=date(2026, 7, 15),
        head_revision_number=2,
    )
    db_session.add(case)
    db_session.flush()
    recorded = ResearchCaseRevision(
        case_id=case.id,
        revision_number=1,
        thesis="Original ownership thesis.",
        assumptions_json=[],
        risks_json=[{"risk": "Competition"}],
        evidence_json=[],
        case_state="monitoring",
        valuation_low=Decimal("80"),
        valuation_base=Decimal("100"),
        valuation_high=Decimal("120"),
        valuation_currency="USD",
        valuation_as_of_date=date(2026, 6, 1),
        decision="own",
        next_review_on=date(2026, 7, 15),
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=user.id,
    )
    current = ResearchCaseRevision(
        case_id=case.id,
        revision_number=2,
        thesis="Current thesis after new evidence.",
        variant_view="The moat may be narrowing.",
        assumptions_json=[],
        risks_json=[{"risk": "Competition accelerated"}],
        evidence_json=[],
        case_state="monitoring",
        valuation_low=Decimal("70"),
        valuation_base=Decimal("90"),
        valuation_high=Decimal("110"),
        valuation_currency="USD",
        valuation_as_of_date=date(2026, 7, 10),
        decision="own",
        next_review_on=date(2026, 7, 15),
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=user.id,
    )
    db_session.add_all([recorded, current])
    db_session.commit()
    position = create_position(
        db_session,
        user_id=user.id,
        portfolio_id=portfolio.id,
        payload=ManualPositionCreate(
            stock_id=stock.id,
            quantity=Decimal("1"),
            currency="USD",
            opened_on=date(2026, 6, 2),
            research_case_id=case.id,
            research_revision_id=recorded.id,
        ),
    )

    workspace = get_portfolio_workspace(
        db_session,
        user_id=user.id,
        portfolio_id=portfolio.id,
        as_of=date(2026, 7, 20),
    )

    item = next(row for row in workspace["positions"] if row["id"] == position.id)
    assert item["review_status"] == "overdue"
    assert item["next_review_on"] == "2026-07-15"
    assert workspace["review_calendar"][0]["position_id"] == position.id
    comparison = workspace["research_comparisons"][str(position.id)]
    assert comparison["recorded_revision"]["thesis"] == "Original ownership thesis."
    assert comparison["current_revision"]["thesis"] == "Current thesis after new evidence."
    assert comparison["current_case"]["head_revision_number"] == 2


def test_workspace_never_calculates_unknown_or_mismatched_currency(
    db_session, user_factory
):
    user = user_factory("portfolio-currency@example.com")
    usd_stock = _stock(db_session, "USD1")
    mismatch_stock = _stock(db_session, "CAD1")
    unknown_stock = _stock(db_session, "UNK1")
    portfolio = _portfolio(db_session, user.id)
    positions = []
    for stock in [usd_stock, mismatch_stock, unknown_stock]:
        positions.append(
            create_position(
                db_session,
                user_id=user.id,
                portfolio_id=portfolio.id,
                payload=ManualPositionCreate(
                    stock_id=stock.id,
                    quantity=Decimal("2"),
                    average_unit_cost=Decimal("50"),
                    currency="USD",
                    opened_on=date(2026, 7, 1),
                ),
            )
        )
    db_session.add_all(
        [
            StockPrice(stock_id=usd_stock.id, price_date=date(2026, 7, 17), open=75, high=75, low=75, close=75, currency="USD", source="fixture"),
            StockPrice(stock_id=mismatch_stock.id, price_date=date(2026, 7, 17), open=75, high=75, low=75, close=75, currency="CAD", source="fixture"),
            StockPrice(stock_id=unknown_stock.id, price_date=date(2026, 7, 17), open=75, high=75, low=75, close=75, currency=None, source="fixture"),
        ]
    )
    db_session.commit()

    workspace = get_portfolio_workspace(
        db_session,
        user_id=user.id,
        portfolio_id=portfolio.id,
        as_of=date(2026, 7, 20),
    )
    by_ticker = {item["ticker"]: item for item in workspace["positions"]}
    assert by_ticker["USD1"]["valuation_status"] == "available"
    assert by_ticker["USD1"]["market_value"] == "150.000000"
    assert by_ticker["USD1"]["unrealized_return"] == "0.500000"
    assert by_ticker["CAD1"]["valuation_status"] == "currency_mismatch"
    assert by_ticker["CAD1"]["market_value"] is None
    assert by_ticker["UNK1"]["valuation_status"] == "price_currency_unavailable"
    assert by_ticker["UNK1"]["unrealized_return"] is None
    assert workspace["totals_by_currency"] == {"USD": "150.000000"}
    assert workspace["cross_currency_total"] is None


def test_inactive_stock_is_retained_with_typed_limitation(db_session, user_factory):
    user = user_factory("portfolio-inactive@example.com")
    stock = _stock(db_session, "OLD", active=False)
    portfolio = _portfolio(db_session, user.id)
    create_position(
        db_session,
        user_id=user.id,
        portfolio_id=portfolio.id,
        payload=ManualPositionCreate(
            stock_id=stock.id,
            quantity=Decimal("1"),
            currency="USD",
            opened_on=date(2026, 7, 1),
        ),
    )
    workspace = get_portfolio_workspace(
        db_session, user_id=user.id, portfolio_id=portfolio.id, as_of=date(2026, 7, 20)
    )
    assert workspace["positions"][0]["identity_state"] == "stock_inactive"
    assert workspace["positions"][0]["valuation_status"] == "stock_inactive"


def test_portfolio_api_is_non_disclosing_across_users(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory("portfolio-api-owner@example.com")
    other = user_factory("portfolio-api-other@example.com")
    portfolio = _portfolio(db_session, owner.id)

    response = client.get(
        f"/api/v1/portfolios/{portfolio.id}", headers=auth_headers(other)
    )
    assert response.status_code == 404


def test_position_events_reject_update_and_delete_at_database_boundary(
    db_session, user_factory
):
    user = user_factory("portfolio-append-only@example.com")
    stock = _stock(db_session, "AUDIT")
    portfolio = _portfolio(db_session, user.id)
    position = create_position(
        db_session,
        user_id=user.id,
        portfolio_id=portfolio.id,
        payload=ManualPositionCreate(
            stock_id=stock.id,
            quantity=Decimal("1"),
            currency="USD",
            opened_on=date(2026, 7, 1),
        ),
    )
    event = db_session.query(PositionJournalEvent).filter_by(position_id=position.id).one()

    with pytest.raises(DatabaseError):
        db_session.execute(
            text("UPDATE position_journal_events SET reason = 'tampered' WHERE id = :id"),
            {"id": event.id},
        )
        db_session.flush()
    db_session.rollback()
    assert db_session.query(PositionJournalEvent).filter_by(position_id=position.id).count() == 1
