from __future__ import annotations

from datetime import datetime, timezone, date
from typing import Any

from fastapi import APIRouter, HTTPException, Body
from sqlalchemy import select, func, delete

from app.api.deps import SessionDep, CurrentUser
from app.models.stocks import StockPool, PoolMembership, Stock, StockPrice
from app.models.facts import MetricFact
from app.services.market_data_service import compute_target_date, ET


router = APIRouter()

FAIR_VALUE_KEY = "val.fair_value"
TARGET_FALLBACK_KEY = "target.price_18m.mid"
PIOTROSKI_TOTAL_KEY = "score.piotroski.total"


def _latest_price_for_date(session: SessionDep, stock_id: int, price_date: date) -> StockPrice | None:
    return session.scalars(
        select(StockPrice)
        .where(StockPrice.stock_id == stock_id, StockPrice.price_date == price_date)
        .order_by(StockPrice.created_at.desc())
        .limit(1)
    ).first()


def _fair_value_for_stock(session: SessionDep, user_id: int, stock_id: int) -> tuple[float | None, str | None]:
    manual = session.scalars(
        select(MetricFact)
        .where(
            MetricFact.user_id == user_id,
            MetricFact.stock_id == stock_id,
            MetricFact.metric_key == FAIR_VALUE_KEY,
            MetricFact.is_current.is_(True),
            MetricFact.source_type == "manual",
        )
        .order_by(MetricFact.created_at.desc())
        .limit(1)
    ).first()
    if manual and manual.value_numeric is not None:
        return float(manual.value_numeric), "manual"

    fallback = session.scalars(
        select(MetricFact)
        .where(
            MetricFact.user_id == user_id,
            MetricFact.stock_id == stock_id,
            MetricFact.metric_key == TARGET_FALLBACK_KEY,
            MetricFact.is_current.is_(True),
        )
        .order_by(MetricFact.created_at.desc())
        .limit(1)
    ).first()
    if fallback and fallback.value_numeric is not None:
        return float(fallback.value_numeric), TARGET_FALLBACK_KEY

    return None, None


def _calc_mos(price: float | None, fair_value: float | None) -> float | None:
    if price is None or fair_value is None:
        return None
    if fair_value == 0:
        return None
    return (fair_value - price) / fair_value


def _serialize_piotroski_total(fact: MetricFact) -> dict[str, Any]:
    value_json = fact.value_json if isinstance(fact.value_json, dict) else {}
    return {
        "period_end_date": fact.period_end_date.isoformat() if fact.period_end_date else None,
        "fiscal_year": value_json.get("fiscal_year") or (fact.period_end_date.year if fact.period_end_date else None),
        "score": fact.value_numeric,
        "status": value_json.get("status"),
        "variant": value_json.get("variant"),
        "partial_score": value_json.get("partial_score"),
        "available_indicators": value_json.get("available_indicators"),
        "max_available_score": value_json.get("max_available_score"),
        "missing_indicators": value_json.get("missing_indicators") or [],
    }


def _is_displayable_historical_piotroski_total(fact: MetricFact) -> bool:
    if fact.period_end_date and fact.period_end_date > date.today():
        return False
    value_json = fact.value_json if isinstance(fact.value_json, dict) else {}
    return value_json.get("fact_nature") != "estimate"


def _piotroski_scores_for_stocks(
    session: SessionDep, user_id: int, stock_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    if not stock_ids:
        return {}

    unique_stock_ids = list(dict.fromkeys(stock_ids))
    scores_by_stock_id: dict[int, list[dict[str, Any]]] = {stock_id: [] for stock_id in unique_stock_ids}

    facts = session.scalars(
        select(MetricFact)
        .where(
            MetricFact.user_id == user_id,
            MetricFact.stock_id.in_(unique_stock_ids),
            MetricFact.metric_key == PIOTROSKI_TOTAL_KEY,
            MetricFact.source_type == "calculated",
            MetricFact.is_current.is_(True),
            MetricFact.period_type == "FY",
            MetricFact.period_end_date.is_not(None),
        )
        .order_by(MetricFact.stock_id.asc(), MetricFact.period_end_date.desc(), MetricFact.created_at.desc())
    ).all()

    for fact in facts:
        if not _is_displayable_historical_piotroski_total(fact):
            continue
        stock_scores = scores_by_stock_id.get(fact.stock_id)
        if stock_scores is not None and len(stock_scores) < 3:
            stock_scores.append(_serialize_piotroski_total(fact))

    return scores_by_stock_id


def _watchlist_rows_for_memberships(
    session: SessionDep,
    user_id: int,
    members: list[PoolMembership],
) -> list[dict[str, Any]]:
    if not members:
        return []

    now_et = datetime.now(timezone.utc).astimezone(ET)
    target_date = compute_target_date(now_et)
    piotroski_scores_by_stock_id = _piotroski_scores_for_stocks(
        session, user_id, [membership.stock_id for membership in members]
    )

    rows: list[dict[str, Any]] = []
    for membership in members:
        stock = session.get(Stock, membership.stock_id)
        if not stock:
            continue

        latest = _latest_price_for_date(session, stock.id, target_date)
        price = float(latest.close) if latest else None
        price_updated_at = latest.created_at if latest else None

        prev_price_date = session.scalar(
            select(func.max(StockPrice.price_date))
            .where(
                StockPrice.stock_id == stock.id,
                StockPrice.price_date < target_date,
            )
        )
        delta_today = None
        if prev_price_date and latest:
            prev_price = _latest_price_for_date(session, stock.id, prev_price_date)
            if prev_price and prev_price.close is not None:
                delta_today = float(latest.close) - float(prev_price.close)

        fair_value, fair_value_source = _fair_value_for_stock(session, user_id, stock.id)
        mos = _calc_mos(price, fair_value)

        rows.append(
            {
                "membership_id": membership.id,
                "stock_id": stock.id,
                "ticker": stock.ticker,
                "exchange": stock.exchange,
                "company_name": stock.company_name,
                "price": price,
                "price_date": target_date.isoformat(),
                "price_updated_at": price_updated_at,
                "fair_value": fair_value,
                "fair_value_source": fair_value_source,
                "mos": mos,
                "delta_today": delta_today,
                "piotroski_f_scores": piotroski_scores_by_stock_id.get(stock.id, []),
            }
        )

    return rows


@router.get("", response_model=list[dict])
def list_stock_pools(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    user_id = current_user.id

    pools = session.scalars(
        select(StockPool).where(StockPool.user_id == user_id).order_by(StockPool.created_at.desc())
    ).all()
    if not pools:
        return []

    pool_ids = [p.id for p in pools]
    counts = dict(
        session.execute(
            select(PoolMembership.pool_id, func.count(PoolMembership.id))
            .where(PoolMembership.pool_id.in_(pool_ids))
            .group_by(PoolMembership.pool_id)
        ).all()
    )

    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "created_at": p.created_at,
            "member_count": counts.get(p.id, 0),
        }
        for p in pools
    ]


@router.post("", response_model=dict)
def create_stock_pool(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    payload: dict = Body(...),
) -> Any:
    user_id = current_user.id

    name = (payload.get("name") or "").strip()
    description = payload.get("description")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    pool = StockPool(user_id=user_id, name=name, description=description)
    session.add(pool)
    session.commit()
    session.refresh(pool)
    return {
        "id": pool.id,
        "name": pool.name,
        "description": pool.description,
        "created_at": pool.created_at,
    }


@router.delete("/{pool_id}", response_model=dict)
def delete_stock_pool(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    pool_id: int,
) -> Any:
    user_id = current_user.id

    pool = session.get(StockPool, pool_id)
    if not pool or pool.user_id != user_id:
        raise HTTPException(status_code=404, detail="Pool not found")

    session.execute(delete(PoolMembership).where(PoolMembership.pool_id == pool_id))
    session.delete(pool)
    session.commit()
    return {"status": "deleted"}


@router.get("/overview/members", response_model=list[dict])
def list_overview_members(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    user_id = current_user.id

    members = session.scalars(
        select(PoolMembership)
        .where(PoolMembership.user_id == user_id)
        .order_by(PoolMembership.created_at.desc(), PoolMembership.id.desc())
    ).all()

    unique_members: list[PoolMembership] = []
    seen_stock_ids: set[int] = set()
    for membership in members:
        if membership.stock_id in seen_stock_ids:
            continue
        seen_stock_ids.add(membership.stock_id)
        unique_members.append(membership)

    return _watchlist_rows_for_memberships(session, user_id, unique_members)


@router.get("/{pool_id}/members", response_model=list[dict])
def list_pool_members(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    pool_id: int,
) -> Any:
    user_id = current_user.id

    pool = session.get(StockPool, pool_id)
    if not pool or pool.user_id != user_id:
        raise HTTPException(status_code=404, detail="Pool not found")

    members = session.scalars(
        select(PoolMembership)
        .where(
            PoolMembership.pool_id == pool_id,
            PoolMembership.user_id == user_id,
        )
        .order_by(PoolMembership.created_at.desc())
    ).all()
    return _watchlist_rows_for_memberships(session, user_id, members)


@router.post("/{pool_id}/members", response_model=dict)
def add_pool_member(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    pool_id: int,
    payload: dict = Body(...),
) -> Any:
    user_id = current_user.id

    pool = session.get(StockPool, pool_id)
    if not pool or pool.user_id != user_id:
        raise HTTPException(status_code=404, detail="Pool not found")

    stock_id = payload.get("stock_id")
    if not isinstance(stock_id, int):
        raise HTTPException(status_code=400, detail="stock_id is required")

    stock = session.get(Stock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    existing = session.scalars(
        select(PoolMembership)
        .where(
            PoolMembership.pool_id == pool_id,
            PoolMembership.stock_id == stock_id,
        )
        .limit(1)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Stock already in pool")

    membership = PoolMembership(
        user_id=user_id,
        pool_id=pool_id,
        stock_id=stock_id,
        inclusion_type="manual",
        rule_id=None,
    )
    session.add(membership)
    session.commit()
    session.refresh(membership)

    return {
        "id": membership.id,
        "pool_id": pool_id,
        "stock": {
            "id": stock.id,
            "ticker": stock.ticker,
            "exchange": stock.exchange,
            "company_name": stock.company_name,
        },
        "created_at": membership.created_at,
    }


@router.delete("/{pool_id}/members/{membership_id}", response_model=dict)
def remove_pool_member(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    pool_id: int,
    membership_id: int,
) -> Any:
    user_id = current_user.id

    pool = session.get(StockPool, pool_id)
    if not pool or pool.user_id != user_id:
        raise HTTPException(status_code=404, detail="Pool not found")

    membership = session.get(PoolMembership, membership_id)
    if not membership or membership.pool_id != pool_id or membership.user_id != user_id:
        raise HTTPException(status_code=404, detail="Membership not found")

    session.delete(membership)
    session.commit()
    return {"status": "deleted"}
