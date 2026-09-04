from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Body
from sqlalchemy import select, func, delete

from app.api.deps import SessionDep, CurrentUser
from app.models.stocks import StockPool, PoolMembership, Stock
from app.models.facts import MetricFact
from app.services.market_data_service import (
    read_canonical_eod_prices,
    read_current_eod_prices,
    serialize_canonical_eod_price,
)
from app.services.canonical_financials import CanonicalSourceConflictError
from app.services.source_reconciliation import (
    CanonicalReconciliationError,
    guard_reconciled_source_selection,
)
from app.services.valuation import read_valuation_contexts, relative_discount


router = APIRouter()

PIOTROSKI_TOTAL_KEY = "score.piotroski.total"


def _serialize_piotroski_total(fact: MetricFact) -> dict[str, Any]:
    value_json = fact.value_json if isinstance(fact.value_json, dict) else {}
    return {
        "period_end_date": fact.period_end_date.isoformat() if fact.period_end_date else None,
        "fiscal_year": value_json.get("fiscal_year") or (fact.period_end_date.year if fact.period_end_date else None),
        "score": float(fact.value_numeric) if fact.value_numeric is not None else None,
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
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, dict[str, Any]]]:
    if not stock_ids:
        return {}, {}

    unique_stock_ids = list(dict.fromkeys(stock_ids))
    scores_by_stock_id: dict[int, list[dict[str, Any]]] = {stock_id: [] for stock_id in unique_stock_ids}
    states_by_stock_id: dict[int, dict[str, Any]] = {}

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

    facts_by_stock_id: dict[int, list[MetricFact]] = {
        stock_id: [] for stock_id in unique_stock_ids
    }
    for fact in facts:
        facts_by_stock_id[fact.stock_id].append(fact)

    evaluated_at = datetime.now(timezone.utc)
    for stock_id, stock_facts in facts_by_stock_id.items():
        guarded, state = _guard_piotroski_display_facts(
            session,
            user_id=user_id,
            stock_id=stock_id,
            facts=stock_facts,
            evaluated_at=evaluated_at,
        )
        states_by_stock_id[stock_id] = state
        for fact in guarded:
            if not _is_displayable_historical_piotroski_total(fact):
                continue
            stock_scores = scores_by_stock_id[stock_id]
            if len(stock_scores) < 3:
                stock_scores.append(_serialize_piotroski_total(fact))

    return scores_by_stock_id, states_by_stock_id


def _guard_piotroski_display_facts(
    session: SessionDep,
    *,
    user_id: int,
    stock_id: int,
    facts: list[MetricFact],
    evaluated_at: datetime,
) -> tuple[list[MetricFact], dict[str, Any]]:
    if not facts:
        return [], {
            "status": "unavailable",
            "reason_code": "piotroski_f_score_unavailable",
            "blocking_reasons": [],
        }
    try:
        guarded = guard_reconciled_source_selection(
            facts,
            consumer="stock_pool_piotroski_display",
            knowledge_cutoff=evaluated_at,
            session=session,
            user_id=user_id,
        )
    except CanonicalReconciliationError as error:
        reasons = sorted(
            {
                str(item.get("reason_code"))
                for item in error.blocking_items
                if item.get("reason_code")
            }
        )
        return [], {
            "status": "unavailable",
            "reason_code": error.code,
            "blocking_reasons": reasons,
        }
    except CanonicalSourceConflictError as error:
        return [], {
            "status": "unavailable",
            "reason_code": error.code,
            "blocking_reasons": ["explicit_source_selection_required"],
        }
    return list(guarded), {
        "status": "available",
        "reason_code": None,
        "blocking_reasons": [],
    }


def _piotroski_compare_fact_nature(fact: MetricFact) -> str:
    value_json = fact.value_json if isinstance(fact.value_json, dict) else {}
    fact_nature = value_json.get("fact_nature")
    return fact_nature if isinstance(fact_nature, str) and fact_nature else "actual"


def _piotroski_compare_year(fact: MetricFact) -> int | None:
    value_json = fact.value_json if isinstance(fact.value_json, dict) else {}
    fiscal_year = value_json.get("fiscal_year")
    if isinstance(fiscal_year, int):
        return fiscal_year
    return fact.period_end_date.year if fact.period_end_date else None


def _piotroski_compare_display_score(fact: MetricFact | None) -> str:
    if fact is None:
        return "—"
    value_json = fact.value_json if isinstance(fact.value_json, dict) else {}
    if isinstance(fact.value_numeric, (int, float, Decimal)):
        return f"{float(fact.value_numeric):.0f}"
    partial_score = value_json.get("partial_score")
    max_available_score = value_json.get("max_available_score")
    if isinstance(partial_score, int) and isinstance(max_available_score, int):
        return f"{partial_score}/{max_available_score}"
    return "—"


def _serialize_piotroski_compare_cell(year: int, fact: MetricFact | None) -> dict[str, Any]:
    value_json = fact.value_json if fact and isinstance(fact.value_json, dict) else {}
    return {
        "fiscal_year": year,
        "score": float(fact.value_numeric) if fact and isinstance(fact.value_numeric, (int, float, Decimal)) else None,
        "display_score": _piotroski_compare_display_score(fact),
        "fact_nature": _piotroski_compare_fact_nature(fact) if fact else None,
        "status": value_json.get("status") if fact else None,
    }


def _select_piotroski_compare_facts(facts: list[MetricFact]) -> list[MetricFact]:
    actual: list[MetricFact] = []
    estimates: list[MetricFact] = []
    for fact in facts:
        if _piotroski_compare_year(fact) is None:
            continue
        if _piotroski_compare_fact_nature(fact) == "estimate":
            estimates.append(fact)
        else:
            actual.append(fact)
    actual.sort(key=lambda fact: _piotroski_compare_year(fact) or 0, reverse=True)
    estimates.sort(key=lambda fact: _piotroski_compare_year(fact) or 0)
    selected_actual = sorted(actual[:5], key=lambda fact: _piotroski_compare_year(fact) or 0)
    return selected_actual + estimates[:2]


def _piotroski_compare_payload(
    session: SessionDep,
    user_id: int,
    members: list[PoolMembership],
    *,
    watchlist: dict[str, Any],
) -> dict[str, Any]:
    unique_members: list[PoolMembership] = []
    seen_stock_ids: set[int] = set()
    for member in members:
        if member.stock_id in seen_stock_ids:
            continue
        seen_stock_ids.add(member.stock_id)
        unique_members.append(member)

    stock_ids = [member.stock_id for member in unique_members]
    facts_by_stock_id: dict[int, list[MetricFact]] = {stock_id: [] for stock_id in stock_ids}
    if stock_ids:
        facts = session.scalars(
            select(MetricFact)
            .where(
                MetricFact.user_id == user_id,
                MetricFact.stock_id.in_(stock_ids),
                MetricFact.metric_key == PIOTROSKI_TOTAL_KEY,
                MetricFact.source_type == "calculated",
                MetricFact.is_current.is_(True),
                MetricFact.period_type == "FY",
                MetricFact.period_end_date.is_not(None),
            )
            .order_by(MetricFact.stock_id.asc(), MetricFact.period_end_date.asc(), MetricFact.created_at.desc())
        ).all()
        for fact in facts:
            facts_by_stock_id.setdefault(fact.stock_id, []).append(fact)

    selected_by_stock_id: dict[int, dict[int, MetricFact]] = {}
    states_by_stock_id: dict[int, dict[str, Any]] = {}
    years: set[int] = set()
    for stock_id, facts in facts_by_stock_id.items():
        guarded, state = _guard_piotroski_display_facts(
            session,
            user_id=user_id,
            stock_id=stock_id,
            facts=facts,
            evaluated_at=datetime.now(timezone.utc),
        )
        states_by_stock_id[stock_id] = state
        selected = {}
        for fact in _select_piotroski_compare_facts(guarded):
            year = _piotroski_compare_year(fact)
            if year is None or year in selected:
                continue
            selected[year] = fact
            years.add(year)
        selected_by_stock_id[stock_id] = selected

    ordered_years = sorted(years)
    stocks_by_id = {
        int(stock.id): stock
        for stock in session.scalars(
            select(Stock).where(Stock.id.in_(stock_ids))
        ).all()
    }
    rows: list[dict[str, Any]] = []
    for member in unique_members:
        stock = stocks_by_id.get(int(member.stock_id))
        if not stock:
            continue
        by_year = selected_by_stock_id.get(stock.id, {})
        rows.append(
            {
                "stock_id": stock.id,
                "ticker": stock.ticker,
                "exchange": stock.listing_exchange or stock.exchange,
                "market_country": stock.market_country,
                "listing_exchange": stock.listing_exchange,
                "company_name": stock.company_name,
                "piotroski_f_score_state": states_by_stock_id[stock.id],
                "scores": [
                    _serialize_piotroski_compare_cell(year, by_year.get(year))
                    for year in ordered_years
                ],
            }
        )

    rows.sort(key=lambda row: row["ticker"])
    return {"watchlist": watchlist, "years": ordered_years, "rows": rows}


def _watchlist_rows_for_memberships(
    session: SessionDep,
    user_id: int,
    members: list[PoolMembership],
) -> list[dict[str, Any]]:
    if not members:
        return []

    stock_ids = list(dict.fromkeys(int(member.stock_id) for member in members))
    piotroski_scores_by_stock_id, piotroski_states_by_stock_id = _piotroski_scores_for_stocks(
        session, user_id, stock_ids
    )
    stocks_by_id = {
        int(stock.id): stock
        for stock in session.scalars(
            select(Stock).where(Stock.id.in_(stock_ids))
        ).all()
    }
    evaluated_at = datetime.now(timezone.utc)
    current_prices = read_current_eod_prices(
        session,
        stocks=stocks_by_id.values(),
        evaluated_at=evaluated_at,
    )
    previous_stocks = [
        stock
        for stock_id, stock in stocks_by_id.items()
        if current_prices[stock_id].status == "available"
        and current_prices[stock_id].price_date is not None
    ]
    previous_prices = read_canonical_eod_prices(
        session,
        stocks=previous_stocks,
        as_of_by_stock_id={
            int(stock.id): current_prices[int(stock.id)].price_date
            for stock in previous_stocks
        },
        knowledge_cutoff=evaluated_at,
    ) if previous_stocks else {}
    valuations = read_valuation_contexts(
        session,
        user_id=user_id,
        stock_ids=stock_ids,
    )

    rows: list[dict[str, Any]] = []
    for membership in members:
        stock = stocks_by_id.get(int(membership.stock_id))
        if not stock:
            continue

        current_price = current_prices[stock.id]
        price = current_price.current_value

        previous_price = previous_prices.get(stock.id)
        delta_today = None
        if current_price.status != "available" or price is None:
            delta_today_state = {
                "status": "unavailable",
                "reason_code": current_price.reason_code or "price_unavailable",
                "currency": None,
            }
        elif previous_price is None or previous_price.status != "available":
            delta_today_state = {
                "status": "unavailable",
                "reason_code": (
                    previous_price.reason_code
                    if previous_price is not None
                    else "previous_price_unavailable"
                ),
                "currency": None,
            }
        elif (
            current_price.currency is None
            or previous_price.currency is None
        ):
            delta_today_state = {
                "status": "unavailable",
                "reason_code": "price_currency_unavailable",
                "currency": None,
            }
        elif current_price.currency != previous_price.currency:
            delta_today_state = {
                "status": "unavailable",
                "reason_code": "currency_mismatch",
                "currency": None,
            }
        elif previous_price.current_value is None:
            delta_today_state = {
                "status": "unavailable",
                "reason_code": "previous_price_unavailable",
                "currency": None,
            }
        else:
            delta_today = price - previous_price.current_value
            delta_today_state = {
                "status": "available",
                "reason_code": None,
                "currency": current_price.currency,
            }

        valuation = valuations[stock.id]
        fair_value = valuation.user_intrinsic_value
        if current_price.status != "available":
            price_comparison_reason = current_price.reason_code
        elif fair_value is None:
            price_comparison_reason = "intrinsic_value_unavailable"
        elif current_price.currency != valuation.user_intrinsic_value_currency:
            price_comparison_reason = "currency_mismatch"
        else:
            price_comparison_reason = None
        mos = (
            relative_discount(price, fair_value)
            if price_comparison_reason is None
            else None
        )
        if current_price.status != "available":
            reference_comparison_reason = current_price.reason_code
        elif valuation.system_reference_value is None:
            reference_comparison_reason = "valuation_reference_unavailable"
        elif current_price.currency != valuation.system_reference_currency:
            reference_comparison_reason = "currency_mismatch"
        else:
            reference_comparison_reason = None

        rows.append(
            {
                "membership_id": membership.id,
                "stock_id": stock.id,
                "ticker": stock.ticker,
                "exchange": stock.listing_exchange or stock.exchange,
                "market_country": stock.market_country,
                "listing_exchange": stock.listing_exchange,
                "company_name": stock.company_name,
                "current_price": serialize_canonical_eod_price(current_price),
                "fair_value": fair_value,
                "fair_value_source": "manual" if fair_value is not None else None,
                "fair_value_status": valuation.user_intrinsic_value_status,
                "fair_value_as_of": valuation.user_intrinsic_value_as_of,
                "fair_value_currency": valuation.user_intrinsic_value_currency,
                "mos": mos,
                "price_comparison_reason": price_comparison_reason,
                "valuation_reference": valuation.system_reference_value,
                "valuation_reference_source": valuation.system_reference_type,
                "valuation_reference_as_of": valuation.system_reference_as_of,
                "valuation_reference_currency": valuation.system_reference_currency,
                "discount_to_reference": (
                    relative_discount(price, valuation.system_reference_value)
                    if reference_comparison_reason is None
                    else None
                ),
                "reference_comparison_reason": reference_comparison_reason,
                "delta_today": delta_today,
                "delta_today_state": delta_today_state,
                "piotroski_f_scores": piotroski_scores_by_stock_id.get(stock.id, []),
                "piotroski_f_score_state": piotroski_states_by_stock_id[stock.id],
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


@router.get("/overview/f-score-compare", response_model=dict)
def overview_f_score_compare(
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
    return _piotroski_compare_payload(
        session,
        user_id,
        members,
        watchlist={"id": "overview", "name": "Overview"},
    )


@router.get("/{pool_id}/f-score-compare", response_model=dict)
def pool_f_score_compare(
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
    return _piotroski_compare_payload(
        session,
        user_id,
        members,
        watchlist={"id": pool.id, "name": pool.name},
    )


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
            "exchange": stock.listing_exchange or stock.exchange,
            "market_country": stock.market_country,
            "listing_exchange": stock.listing_exchange,
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
