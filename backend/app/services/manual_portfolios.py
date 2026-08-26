"""Transactional manual-portfolio and decision-journal application service."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.portfolios import ManualPortfolio, ManualPosition, PositionJournalEvent
from app.models.research import ResearchCase, ResearchCaseRevision
from app.models.stocks import Stock
from app.schemas.portfolios import (
    ManualPortfolioArchive,
    ManualPortfolioCreate,
    ManualPositionClose,
    ManualPositionCreate,
    ManualPositionResize,
    ManualPositionReview,
)
from app.services.market_data_service import read_canonical_eod_price


SIX_PLACES = Decimal("0.000001")


class PortfolioError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _owned_portfolio(
    session: Session, *, user_id: int, portfolio_id: int, for_update: bool = False
) -> ManualPortfolio:
    query = session.query(ManualPortfolio).filter(
        ManualPortfolio.id == portfolio_id,
        ManualPortfolio.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()
    row = query.one_or_none()
    if row is None:
        raise PortfolioError("portfolio_not_found", "Portfolio not found.", status_code=404)
    return row


def _owned_position(
    session: Session, *, user_id: int, position_id: int, for_update: bool = False
) -> ManualPosition:
    query = session.query(ManualPosition).filter(
        ManualPosition.id == position_id,
        ManualPosition.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()
    row = query.one_or_none()
    if row is None:
        raise PortfolioError("position_not_found", "Position not found.", status_code=404)
    return row


def _validate_research_link(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    research_case_id: int | None,
    research_revision_id: int | None,
) -> None:
    if research_case_id is None:
        if research_revision_id is not None:
            raise PortfolioError("invalid_research_link", "A revision requires a research case.")
        return
    case = (
        session.query(ResearchCase)
        .filter(
            ResearchCase.id == research_case_id,
            ResearchCase.user_id == user_id,
            ResearchCase.stock_id == stock_id,
        )
        .one_or_none()
    )
    if case is None:
        raise PortfolioError(
            "research_case_unavailable",
            "The research case is unavailable or does not match this user and stock.",
        )
    if research_revision_id is not None:
        revision = (
            session.query(ResearchCaseRevision)
            .filter(
                ResearchCaseRevision.id == research_revision_id,
                ResearchCaseRevision.case_id == case.id,
                ResearchCaseRevision.snapshot_stock_id == stock_id,
            )
            .one_or_none()
        )
        if revision is None:
            raise PortfolioError(
                "research_revision_unavailable",
                "The research revision is unavailable or does not match the case.",
            )


def _append_event(
    session: Session,
    *,
    position: ManualPosition,
    stock: Stock,
    sequence_number: int,
    event_type: str,
    effective_on: date,
    prior_quantity: Decimal | None,
    new_quantity: Decimal | None,
    prior_average_unit_cost: Decimal | None,
    new_average_unit_cost: Decimal | None,
    reason: str | None,
    research_case_id: int | None,
    research_revision_id: int | None,
    payload: dict[str, Any] | None = None,
) -> PositionJournalEvent:
    event = PositionJournalEvent(
        position_id=position.id,
        portfolio_id=position.portfolio_id,
        user_id=position.user_id,
        sequence_number=sequence_number,
        event_type=event_type,
        effective_on=effective_on,
        prior_quantity=prior_quantity,
        new_quantity=new_quantity,
        prior_average_unit_cost=prior_average_unit_cost,
        new_average_unit_cost=new_average_unit_cost,
        currency=position.currency,
        reason=reason,
        research_case_id=research_case_id,
        research_revision_id=research_revision_id,
        recorded_stock_id=stock.id,
        recorded_ticker=stock.ticker,
        recorded_company_name=stock.company_name,
        recorded_exchange=stock.exchange,
        payload_json=payload,
    )
    session.add(event)
    return event


def create_portfolio(
    session: Session, *, user_id: int, payload: ManualPortfolioCreate
) -> ManualPortfolio:
    row = ManualPortfolio(
        user_id=user_id,
        name=payload.name,
        description=payload.description,
        status="active",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def archive_portfolio(
    session: Session,
    *,
    user_id: int,
    portfolio_id: int,
    payload: ManualPortfolioArchive,
) -> ManualPortfolio:
    row = _owned_portfolio(
        session, user_id=user_id, portfolio_id=portfolio_id, for_update=True
    )
    if row.version != payload.expected_version:
        raise PortfolioError(
            "stale_portfolio_version", "The portfolio changed after it was opened.", status_code=409
        )
    if row.status == "archived":
        return row
    open_count = (
        session.query(ManualPosition)
        .filter_by(portfolio_id=row.id, user_id=user_id, state="open")
        .count()
    )
    if open_count:
        raise PortfolioError(
            "portfolio_has_open_positions",
            "Close all manual positions before archiving the portfolio.",
            status_code=409,
        )
    row.status = "archived"
    row.archived_at = datetime.now(timezone.utc)
    row.version += 1
    session.commit()
    session.refresh(row)
    return row


def create_position(
    session: Session,
    *,
    user_id: int,
    portfolio_id: int,
    payload: ManualPositionCreate,
) -> ManualPosition:
    portfolio = _owned_portfolio(
        session, user_id=user_id, portfolio_id=portfolio_id, for_update=True
    )
    if portfolio.status != "active":
        raise PortfolioError("portfolio_archived", "Archived portfolios cannot be changed.", status_code=409)
    stock = session.get(Stock, payload.stock_id)
    if stock is None:
        raise PortfolioError("stock_not_found", "Stock not found.", status_code=404)
    _validate_research_link(
        session,
        user_id=user_id,
        stock_id=stock.id,
        research_case_id=payload.research_case_id,
        research_revision_id=payload.research_revision_id,
    )
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"manual-position:{portfolio.id}:{stock.id}"},
    )
    existing = (
        session.query(ManualPosition)
        .filter_by(portfolio_id=portfolio.id, stock_id=stock.id, state="open")
        .one_or_none()
    )
    if existing:
        raise PortfolioError(
            "open_position_exists",
            "An open manual position already exists for this stock in the portfolio.",
            status_code=409,
        )
    row = ManualPosition(
        portfolio_id=portfolio.id,
        user_id=user_id,
        stock_id=stock.id,
        state="open",
        quantity=payload.quantity,
        average_unit_cost=payload.average_unit_cost,
        currency=payload.currency,
        research_case_id=payload.research_case_id,
        research_revision_id=payload.research_revision_id,
        opened_on=payload.opened_on,
        version=1,
    )
    session.add(row)
    session.flush()
    _append_event(
        session,
        position=row,
        stock=stock,
        sequence_number=1,
        event_type="open",
        effective_on=payload.opened_on,
        prior_quantity=None,
        new_quantity=payload.quantity,
        prior_average_unit_cost=None,
        new_average_unit_cost=payload.average_unit_cost,
        reason=payload.reason,
        research_case_id=payload.research_case_id,
        research_revision_id=payload.research_revision_id,
        payload={"manual_record": True, "broker_synchronized": False},
    )
    session.commit()
    session.refresh(row)
    return row


def _prepare_position_write(
    session: Session,
    *,
    user_id: int,
    position_id: int,
    expected_version: int,
    research_case_id: int | None,
    research_revision_id: int | None,
) -> tuple[ManualPosition, Stock]:
    row = _owned_position(
        session, user_id=user_id, position_id=position_id, for_update=True
    )
    if row.version != expected_version:
        raise PortfolioError(
            "stale_position_version",
            "The position changed after it was opened.",
            status_code=409,
        )
    if row.state != "open":
        raise PortfolioError("position_closed", "Closed positions cannot be changed.", status_code=409)
    stock = session.get(Stock, row.stock_id)
    assert stock is not None
    _validate_research_link(
        session,
        user_id=user_id,
        stock_id=row.stock_id,
        research_case_id=research_case_id,
        research_revision_id=research_revision_id,
    )
    return row, stock


def resize_position(
    session: Session,
    *,
    user_id: int,
    position_id: int,
    payload: ManualPositionResize,
) -> ManualPosition:
    row, stock = _prepare_position_write(
        session,
        user_id=user_id,
        position_id=position_id,
        expected_version=payload.expected_version,
        research_case_id=payload.research_case_id,
        research_revision_id=payload.research_revision_id,
    )
    prior_quantity = row.quantity
    prior_cost = row.average_unit_cost
    row.quantity = payload.quantity
    if payload.average_unit_cost is not None:
        row.average_unit_cost = payload.average_unit_cost
    if payload.research_case_id is not None:
        row.research_case_id = payload.research_case_id
        row.research_revision_id = payload.research_revision_id
    row.version += 1
    _append_event(
        session,
        position=row,
        stock=stock,
        sequence_number=row.version,
        event_type="resize",
        effective_on=date.today(),
        prior_quantity=prior_quantity,
        new_quantity=row.quantity,
        prior_average_unit_cost=prior_cost,
        new_average_unit_cost=row.average_unit_cost,
        reason=payload.reason,
        research_case_id=row.research_case_id,
        research_revision_id=row.research_revision_id,
    )
    session.commit()
    session.refresh(row)
    return row


def record_position_review(
    session: Session,
    *,
    user_id: int,
    position_id: int,
    payload: ManualPositionReview,
) -> ManualPosition:
    row, stock = _prepare_position_write(
        session,
        user_id=user_id,
        position_id=position_id,
        expected_version=payload.expected_version,
        research_case_id=payload.research_case_id,
        research_revision_id=payload.research_revision_id,
    )
    if payload.research_case_id is not None:
        row.research_case_id = payload.research_case_id
        row.research_revision_id = payload.research_revision_id
    row.last_reviewed_on = payload.reviewed_on
    row.version += 1
    _append_event(
        session,
        position=row,
        stock=stock,
        sequence_number=row.version,
        event_type="review",
        effective_on=payload.reviewed_on,
        prior_quantity=row.quantity,
        new_quantity=row.quantity,
        prior_average_unit_cost=row.average_unit_cost,
        new_average_unit_cost=row.average_unit_cost,
        reason=payload.reason,
        research_case_id=row.research_case_id,
        research_revision_id=row.research_revision_id,
    )
    session.commit()
    session.refresh(row)
    return row


def close_position(
    session: Session,
    *,
    user_id: int,
    position_id: int,
    payload: ManualPositionClose,
) -> ManualPosition:
    row, stock = _prepare_position_write(
        session,
        user_id=user_id,
        position_id=position_id,
        expected_version=payload.expected_version,
        research_case_id=payload.research_case_id,
        research_revision_id=payload.research_revision_id,
    )
    if payload.closed_on < row.opened_on:
        raise PortfolioError("invalid_close_date", "Close date cannot precede open date.")
    prior_quantity = row.quantity
    if payload.research_case_id is not None:
        row.research_case_id = payload.research_case_id
        row.research_revision_id = payload.research_revision_id
    row.state = "closed"
    row.quantity = Decimal("0")
    row.closed_on = payload.closed_on
    row.version += 1
    _append_event(
        session,
        position=row,
        stock=stock,
        sequence_number=row.version,
        event_type="close",
        effective_on=payload.closed_on,
        prior_quantity=prior_quantity,
        new_quantity=Decimal("0"),
        prior_average_unit_cost=row.average_unit_cost,
        new_average_unit_cost=row.average_unit_cost,
        reason=payload.reason,
        research_case_id=row.research_case_id,
        research_revision_id=row.research_revision_id,
        payload={"manual_record": True, "execution_record": False},
    )
    session.commit()
    session.refresh(row)
    return row


def _decimal(value: Decimal | None, quantize: Decimal | None = None) -> str | None:
    if value is None:
        return None
    if quantize is not None:
        value = value.quantize(quantize, rounding=ROUND_HALF_UP)
    return format(value, "f")


def serialize_portfolio(row: ManualPortfolio) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "version": row.version,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def serialize_position(row: ManualPosition, stock: Stock) -> dict[str, Any]:
    return {
        "id": row.id,
        "portfolio_id": row.portfolio_id,
        "stock_id": row.stock_id,
        "ticker": stock.ticker,
        "company_name": stock.company_name,
        "state": row.state,
        "quantity": _decimal(row.quantity),
        "average_unit_cost": _decimal(row.average_unit_cost),
        "currency": row.currency,
        "research_case_id": row.research_case_id,
        "research_revision_id": row.research_revision_id,
        "opened_on": row.opened_on.isoformat(),
        "closed_on": row.closed_on.isoformat() if row.closed_on else None,
        "last_reviewed_on": row.last_reviewed_on.isoformat() if row.last_reviewed_on else None,
        "version": row.version,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def get_portfolio_workspace(
    session: Session, *, user_id: int, portfolio_id: int, as_of: date
) -> dict[str, Any]:
    portfolio = _owned_portfolio(
        session, user_id=user_id, portfolio_id=portfolio_id
    )
    rows = (
        session.query(ManualPosition, Stock)
        .join(Stock, Stock.id == ManualPosition.stock_id)
        .filter(
            ManualPosition.portfolio_id == portfolio.id,
            ManualPosition.user_id == user_id,
        )
        .order_by(
            (ManualPosition.state == "open").desc(),
            Stock.ticker,
            ManualPosition.id,
        )
        .all()
    )
    position_ids = [position.id for position, _stock in rows]
    events = (
        session.query(PositionJournalEvent)
        .filter(
            PositionJournalEvent.user_id == user_id,
            PositionJournalEvent.portfolio_id == portfolio.id,
            PositionJournalEvent.position_id.in_(position_ids or [-1]),
        )
        .order_by(PositionJournalEvent.created_at.desc(), PositionJournalEvent.id.desc())
        .limit(500)
        .all()
    )
    case_ids = {
        int(position.research_case_id)
        for position, _stock in rows
        if position.research_case_id is not None
    }
    cases_by_id = {
        case.id: case
        for case in session.query(ResearchCase)
        .filter(
            ResearchCase.user_id == user_id,
            ResearchCase.id.in_(case_ids or {-1}),
        )
        .all()
    }
    current_revisions_by_case: dict[int, ResearchCaseRevision] = {}
    for revision in (
        session.query(ResearchCaseRevision)
        .filter(ResearchCaseRevision.case_id.in_(case_ids or {-1}))
        .order_by(
            ResearchCaseRevision.case_id,
            ResearchCaseRevision.revision_number.desc(),
        )
        .all()
    ):
        case = cases_by_id.get(revision.case_id)
        if case is not None and revision.revision_number == case.head_revision_number:
            current_revisions_by_case.setdefault(case.id, revision)
    positions: list[dict[str, Any]] = []
    totals: dict[str, Decimal] = {}
    for position, stock in rows:
        item = serialize_position(position, stock)
        linked_case = cases_by_id.get(position.research_case_id or -1)
        if linked_case is None:
            review_status = "unlinked"
            next_review_on = None
        elif linked_case.state == "researching":
            review_status = "under_review"
            next_review_on = None
        elif linked_case.state != "monitoring":
            review_status = "decision_terminal_or_incomplete"
            next_review_on = linked_case.next_review_on
        elif linked_case.next_review_on is None:
            review_status = "unscheduled"
            next_review_on = None
        elif linked_case.next_review_on < as_of:
            review_status = "overdue"
            next_review_on = linked_case.next_review_on
        elif linked_case.next_review_on == as_of:
            review_status = "due_today"
            next_review_on = linked_case.next_review_on
        else:
            review_status = "scheduled"
            next_review_on = linked_case.next_review_on
        item["review_status"] = review_status
        item["next_review_on"] = (
            next_review_on.isoformat() if next_review_on is not None else None
        )
        item["identity_state"] = "active" if stock.is_active else "stock_inactive"
        price = read_canonical_eod_price(session, stock=stock, as_of=as_of)
        item["price"] = str(price.close) if price.close is not None else None
        item["price_date"] = price.price_date.isoformat() if price.price_date else None
        item["price_currency"] = price.currency
        item["price_freshness_state"] = price.freshness_state
        item["market_value"] = None
        item["unrealized_return"] = None
        if not stock.is_active:
            valuation_status = "stock_inactive"
        elif price.close is None:
            valuation_status = "price_unavailable"
        elif price.currency is None:
            valuation_status = "price_currency_unavailable"
        elif price.currency != position.currency:
            valuation_status = "currency_mismatch"
        elif position.state != "open":
            valuation_status = "position_closed"
        else:
            valuation_status = "available"
            close = Decimal(str(price.close))
            market_value = (position.quantity * close).quantize(
                SIX_PLACES, rounding=ROUND_HALF_UP
            )
            item["market_value"] = _decimal(market_value)
            totals[position.currency] = totals.get(position.currency, Decimal("0")) + market_value
            if position.average_unit_cost is not None:
                item["unrealized_return"] = _decimal(
                    ((close - position.average_unit_cost) / position.average_unit_cost),
                    SIX_PLACES,
                )
        item["valuation_status"] = valuation_status
        positions.append(item)

    linked_revisions = {
        revision.id: revision
        for revision in session.query(ResearchCaseRevision)
        .join(ResearchCase, ResearchCase.id == ResearchCaseRevision.case_id)
        .filter(
            ResearchCase.user_id == user_id,
            ResearchCaseRevision.id.in_(
                [position.research_revision_id for position, _ in rows if position.research_revision_id]
                or [-1]
            ),
        )
        .all()
    }

    def revision_snapshot(revision: ResearchCaseRevision | None) -> dict[str, Any] | None:
        if revision is None:
            return None
        return {
            "id": revision.id,
            "case_id": revision.case_id,
            "revision_number": revision.revision_number,
            "thesis": revision.thesis,
            "variant_view": revision.variant_view,
            "decision": revision.decision,
            "valuation_base": _decimal(revision.valuation_base),
            "valuation_as_of_date": (
                revision.valuation_as_of_date.isoformat()
                if revision.valuation_as_of_date
                else None
            ),
            "recorded_ticker": revision.stock_ticker,
            "created_at": revision.created_at.isoformat(),
        }

    review_calendar = sorted(
        [
            {
                "position_id": item["id"],
                "stock_id": item["stock_id"],
                "ticker": item["ticker"],
                "research_case_id": item["research_case_id"],
                "review_status": item["review_status"],
                "next_review_on": item["next_review_on"],
                "last_reviewed_on": item["last_reviewed_on"],
            }
            for item in positions
            if item["state"] == "open"
        ],
        key=lambda item: (
            {
                "overdue": 0,
                "due_today": 1,
                "under_review": 2,
                "scheduled": 3,
                "unscheduled": 4,
                "unlinked": 5,
                "decision_terminal_or_incomplete": 6,
            }.get(item["review_status"], 9),
            item["next_review_on"] or "9999-12-31",
            item["ticker"],
        ),
    )
    research_comparisons = {}
    for position, _stock in rows:
        case = cases_by_id.get(position.research_case_id or -1)
        if case is None:
            continue
        research_comparisons[str(position.id)] = {
            "recorded_revision": revision_snapshot(
                linked_revisions.get(position.research_revision_id or -1)
            ),
            "current_revision": revision_snapshot(
                current_revisions_by_case.get(case.id)
            ),
            "current_case": {
                "id": case.id,
                "state": case.state,
                "decision": case.decision,
                "next_review_on": (
                    case.next_review_on.isoformat() if case.next_review_on else None
                ),
                "head_revision_number": case.head_revision_number,
            },
        }
    return {
        "as_of": as_of.isoformat(),
        "portfolio": serialize_portfolio(portfolio),
        "positions": positions,
        "totals_by_currency": {
            currency: _decimal(value, SIX_PLACES) for currency, value in sorted(totals.items())
        },
        "cross_currency_total": None,
        "review_calendar": review_calendar,
        "journal_events": [
            {
                "id": event.id,
                "position_id": event.position_id,
                "sequence_number": event.sequence_number,
                "event_type": event.event_type,
                "effective_on": event.effective_on.isoformat(),
                "prior_quantity": _decimal(event.prior_quantity),
                "new_quantity": _decimal(event.new_quantity),
                "prior_average_unit_cost": _decimal(event.prior_average_unit_cost),
                "new_average_unit_cost": _decimal(event.new_average_unit_cost),
                "currency": event.currency,
                "reason": event.reason,
                "research_case_id": event.research_case_id,
                "research_revision_id": event.research_revision_id,
                "recorded_identity": {
                    "stock_id": event.recorded_stock_id,
                    "ticker": event.recorded_ticker,
                    "company_name": event.recorded_company_name,
                    "exchange": event.recorded_exchange,
                },
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ],
        "linked_revisions": {
            str(revision_id): revision_snapshot(revision)
            for revision_id, revision in linked_revisions.items()
        },
        "research_comparisons": research_comparisons,
        "disclaimer": (
            "Manual records are not broker-synchronized and do not represent executions, "
            "tax lots, realized gains, fees, or tax accounting."
        ),
    }
