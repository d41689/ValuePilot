from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.models.portfolios import ManualPortfolio
from app.schemas.portfolios import (
    ManualPortfolioArchive,
    ManualPortfolioCreate,
    ManualPositionClose,
    ManualPositionCreate,
    ManualPositionResize,
    ManualPositionReview,
)
from app.services.manual_portfolios import (
    PortfolioError,
    archive_portfolio,
    close_position,
    create_portfolio,
    create_position,
    get_portfolio_workspace,
    record_position_review,
    resize_position,
    serialize_portfolio,
    serialize_position,
)
from app.models.stocks import Stock


router = APIRouter()


def _raise(session: SessionDep, error: PortfolioError) -> None:
    session.rollback()
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    ) from error


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_manual_portfolio(
    payload: ManualPortfolioCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        row = create_portfolio(session, user_id=current_user.id, payload=payload)
    except PortfolioError as error:
        _raise(session, error)
    return {"portfolio": serialize_portfolio(row)}


@router.get("", response_model=dict)
def list_manual_portfolios(
    session: SessionDep,
    current_user: CurrentUser,
    status_filter: Literal["active", "archived"] | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    query = session.query(ManualPortfolio).filter(
        ManualPortfolio.user_id == current_user.id
    )
    if status_filter:
        query = query.filter(ManualPortfolio.status == status_filter)
    total = query.count()
    rows = (
        query.order_by(ManualPortfolio.updated_at.desc(), ManualPortfolio.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_portfolio(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{portfolio_id}", response_model=dict)
def get_manual_portfolio(
    portfolio_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    as_of: date | None = Query(default=None),
) -> dict[str, Any]:
    try:
        return get_portfolio_workspace(
            session,
            user_id=current_user.id,
            portfolio_id=portfolio_id,
            as_of=as_of or date.today(),
        )
    except PortfolioError as error:
        _raise(session, error)


@router.post("/{portfolio_id}/archive", response_model=dict)
def archive_manual_portfolio(
    portfolio_id: int,
    payload: ManualPortfolioArchive,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        row = archive_portfolio(
            session,
            user_id=current_user.id,
            portfolio_id=portfolio_id,
            payload=payload,
        )
    except PortfolioError as error:
        _raise(session, error)
    return {"portfolio": serialize_portfolio(row)}


@router.post("/{portfolio_id}/positions", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_manual_position(
    portfolio_id: int,
    payload: ManualPositionCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        row = create_position(
            session,
            user_id=current_user.id,
            portfolio_id=portfolio_id,
            payload=payload,
        )
    except PortfolioError as error:
        _raise(session, error)
    stock = session.get(Stock, row.stock_id)
    assert stock is not None
    return {"position": serialize_position(row, stock)}


@router.post("/positions/{position_id}/resize", response_model=dict)
def resize_manual_position(
    position_id: int,
    payload: ManualPositionResize,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        row = resize_position(
            session,
            user_id=current_user.id,
            position_id=position_id,
            payload=payload,
        )
    except PortfolioError as error:
        _raise(session, error)
    stock = session.get(Stock, row.stock_id)
    assert stock is not None
    return {"position": serialize_position(row, stock)}


@router.post("/positions/{position_id}/review", response_model=dict)
def review_manual_position(
    position_id: int,
    payload: ManualPositionReview,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        row = record_position_review(
            session,
            user_id=current_user.id,
            position_id=position_id,
            payload=payload,
        )
    except PortfolioError as error:
        _raise(session, error)
    stock = session.get(Stock, row.stock_id)
    assert stock is not None
    return {"position": serialize_position(row, stock)}


@router.post("/positions/{position_id}/close", response_model=dict)
def close_manual_position(
    position_id: int,
    payload: ManualPositionClose,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        row = close_position(
            session,
            user_id=current_user.id,
            position_id=position_id,
            payload=payload,
        )
    except PortfolioError as error:
        _raise(session, error)
    stock = session.get(Stock, row.stock_id)
    assert stock is not None
    return {"position": serialize_position(row, stock)}
