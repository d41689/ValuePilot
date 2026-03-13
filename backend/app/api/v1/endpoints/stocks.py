from typing import Any
from fastapi import APIRouter, HTTPException, Body, Query
from sqlalchemy import select, func, update, and_, or_
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from app.api.deps import SessionDep, CurrentUser
from app.models.stocks import Stock, StockPrice
from app.models.facts import MetricFact
from app.models.users import User
from app.services.market_data_service import MarketDataService
from app.services.market_data_service import compute_target_date

router = APIRouter()

ET = ZoneInfo("America/New_York")
FAIR_VALUE_KEY = "val.fair_value"
DCF_INPUT_FACT_KEYS = {
    "net_profit_per_share": "per_share.eps",
    "depreciation": "is.depreciation",
    "shares_outstanding": "equity.shares_outstanding",
    "capital_spending_per_share": "per_share.capital_spending",
}


def _dcf_value(value: float, source: str) -> dict[str, float | str]:
    return {"value": float(value), "source": source}


def _build_dcf_inputs_entry(inputs_by_key: dict[str, MetricFact | None]) -> dict[str, dict[str, float | str]]:
    eps_fact = inputs_by_key.get(DCF_INPUT_FACT_KEYS["net_profit_per_share"])
    capex_fact = inputs_by_key.get(DCF_INPUT_FACT_KEYS["capital_spending_per_share"])
    depreciation_fact = inputs_by_key.get(DCF_INPUT_FACT_KEYS["depreciation"])
    shares_fact = inputs_by_key.get(DCF_INPUT_FACT_KEYS["shares_outstanding"])

    eps_value = float(eps_fact.value_numeric) if eps_fact and eps_fact.value_numeric is not None else 0.0
    eps_source = "fact" if eps_fact and eps_fact.value_numeric is not None else "missing"

    capex_value = float(capex_fact.value_numeric) if capex_fact and capex_fact.value_numeric is not None else 0.0
    capex_source = "fact" if capex_fact and capex_fact.value_numeric is not None else "missing"

    depreciation_value = (
        float(depreciation_fact.value_numeric)
        if depreciation_fact and depreciation_fact.value_numeric is not None
        else 0.0
    )
    shares_value = float(shares_fact.value_numeric) if shares_fact and shares_fact.value_numeric is not None else 0.0
    depreciation_per_share = depreciation_value / shares_value if shares_value > 0 else 0.0
    depreciation_source = (
        "computed"
        if depreciation_fact and depreciation_fact.value_numeric is not None and shares_value > 0
        else "missing"
    )

    return {
        "net_profit_per_share": _dcf_value(eps_value, eps_source),
        "depreciation_per_share": _dcf_value(depreciation_per_share, depreciation_source),
        "capital_spending_per_share": _dcf_value(capex_value, capex_source),
    }


def _resolve_normalized_dcf_inputs(
    oeps_facts: list[MetricFact],
    dcf_inputs_series_by_year: dict[int, dict[str, dict[str, float | str]]],
) -> dict[str, dict[str, float | str]] | None:
    latest_five = [fact for fact in oeps_facts if fact.period_end_date is not None][:5]
    if not latest_five:
        return None

    ranked = sorted(
        latest_five,
        key=lambda fact: (
            float(fact.value_numeric) if fact.value_numeric is not None else 0.0,
            fact.period_end_date,
        ),
    )
    median_fact = ranked[len(ranked) // 2]
    median_year = median_fact.period_end_date.year if median_fact.period_end_date else None
    if median_year is None:
        return None
    return dcf_inputs_series_by_year.get(median_year)


def _visible_fact_predicate(current_user_id: int, admin_user_ids: list[int]):
    return or_(
        and_(
            MetricFact.source_type == "parsed",
            or_(
                MetricFact.user_id == current_user_id,
                MetricFact.user_id.in_(admin_user_ids),
            ),
        ),
        and_(
            MetricFact.user_id == current_user_id,
            MetricFact.source_type.in_(["manual", "calculated"]),
        ),
    )


@router.get("/by_ticker/{ticker}", response_model=dict)
def read_stock_by_ticker(
    ticker: str,
    session: SessionDep,
) -> Any:
    """
    Get stock overview by ticker (case-insensitive).
    """
    ticker_normalized = ticker.strip().lower()
    stmt = (
        select(Stock)
        .where(func.lower(Stock.ticker) == ticker_normalized)
        .order_by(Stock.id.asc())
        .limit(1)
    )
    stock = session.scalars(stmt).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    facts_stmt = select(MetricFact).where(
        MetricFact.stock_id == stock.id,
        MetricFact.is_current.is_(True),
        MetricFact.metric_key.in_(
            ["mkt.price", "val.pe", "owners_earnings_per_share_normalized"]
        ),
    )
    facts = session.scalars(facts_stmt).all()
    facts_by_key = {fact.metric_key: fact.value_numeric for fact in facts}

    now_et = datetime.now(timezone.utc).astimezone(ET)
    target_date = compute_target_date(now_et)
    latest_price = session.scalars(
        select(StockPrice)
        .where(StockPrice.stock_id == stock.id, StockPrice.price_date == target_date)
        .order_by(StockPrice.created_at.desc())
        .limit(1)
    ).first()
    if latest_price is None:
        latest_price = session.scalars(
            select(StockPrice)
            .where(StockPrice.stock_id == stock.id)
            .order_by(StockPrice.price_date.desc(), StockPrice.created_at.desc())
            .limit(1)
        ).first()

    oeps_stmt = (
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock.id,
            MetricFact.is_current.is_(True),
            MetricFact.metric_key == "owners_earnings_per_share",
            MetricFact.period_type == "FY",
        )
        .order_by(MetricFact.period_end_date.desc())
        .limit(6)
    )
    oeps_facts = session.scalars(oeps_stmt).all()
    oeps_series = []
    for fact in oeps_facts:
        period_end = fact.period_end_date
        if not period_end:
            continue
        value = fact.value_numeric if fact.value_numeric is not None else 0.0
        oeps_series.append({"year": period_end.year, "value": value})

    dcf_inputs_stmt = (
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock.id,
            MetricFact.is_current.is_(True),
            MetricFact.period_type == "FY",
            MetricFact.metric_key.in_(list(DCF_INPUT_FACT_KEYS.values())),
        )
        .order_by(MetricFact.metric_key.asc(), MetricFact.period_end_date.desc())
    )
    dcf_input_facts = session.scalars(dcf_inputs_stmt).all()
    dcf_inputs_by_date: dict[date, dict[str, MetricFact | None]] = {}
    for fact in dcf_input_facts:
        period_end = fact.period_end_date
        if not period_end:
            continue
        by_key = dcf_inputs_by_date.setdefault(period_end, {})
        if fact.metric_key not in by_key:
            by_key[fact.metric_key] = fact

    dcf_inputs_series = []
    dcf_inputs_series_by_year: dict[int, dict[str, dict[str, float | str]]] = {}
    for fact in oeps_facts:
        period_end = fact.period_end_date
        if not period_end:
            continue
        entry = _build_dcf_inputs_entry(dcf_inputs_by_date.get(period_end, {}))
        dcf_inputs_series.append({"year": period_end.year, **entry})
        dcf_inputs_series_by_year[period_end.year] = entry
    dcf_inputs = _resolve_normalized_dcf_inputs(oeps_facts, dcf_inputs_series_by_year)

    growth_metric_keys = [
        "rates.sales.cagr_est",
        "rates.revenues.cagr_est",
        "rates.cash_flow.cagr_est",
        "rates.earnings.cagr_est",
    ]
    growth_stmt = (
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock.id,
            MetricFact.is_current.is_(True),
            MetricFact.metric_key.in_(growth_metric_keys),
        )
        .order_by(MetricFact.metric_key.asc(), MetricFact.period_end_date.desc())
    )
    growth_facts = session.scalars(growth_stmt).all()
    growth_by_metric_key: dict[str, float] = {}

    def _growth_value_pct(fact: MetricFact) -> float | None:
        raw_value = None
        if isinstance(fact.value_json, dict):
            raw_value = fact.value_json.get("value")
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        if fact.value_numeric is not None:
            return float(fact.value_numeric) * 100.0
        return None

    for fact in growth_facts:
        if fact.metric_key in growth_by_metric_key:
            continue
        value = _growth_value_pct(fact)
        if value is not None:
            growth_by_metric_key[fact.metric_key] = value

    growth_rate_options = []

    if "rates.sales.cagr_est" in growth_by_metric_key:
        growth_rate_options.append(
            {"key": "sales", "label": "Sales", "value": growth_by_metric_key["rates.sales.cagr_est"]}
        )
    elif "rates.revenues.cagr_est" in growth_by_metric_key:
        growth_rate_options.append(
            {"key": "revenues", "label": "Revenues", "value": growth_by_metric_key["rates.revenues.cagr_est"]}
        )

    if "rates.cash_flow.cagr_est" in growth_by_metric_key:
        growth_rate_options.append(
            {"key": "cash_flow", "label": "Cash Flow", "value": growth_by_metric_key["rates.cash_flow.cagr_est"]}
        )
    if "rates.earnings.cagr_est" in growth_by_metric_key:
        growth_rate_options.append(
            {"key": "earnings", "label": "Earnings", "value": growth_by_metric_key["rates.earnings.cagr_est"]}
        )

    return {
        "id": stock.id,
        "ticker": stock.ticker,
        "exchange": stock.exchange,
        "company_name": stock.company_name,
        "price": facts_by_key.get("mkt.price"),
        "latest_price": float(latest_price.close) if latest_price and latest_price.close is not None else None,
        "latest_price_date": latest_price.price_date.isoformat() if latest_price else None,
        "latest_price_updated_at": latest_price.created_at.isoformat() if latest_price else None,
        "pe": facts_by_key.get("val.pe"),
        "oeps_normalized": facts_by_key.get("owners_earnings_per_share_normalized"),
        "oeps_series": oeps_series,
        "dcf_inputs": dcf_inputs,
        "dcf_inputs_series": dcf_inputs_series,
        "growth_rate_options": growth_rate_options,
    }

@router.get("/{stock_id}", response_model=dict)
def read_stock(
    stock_id: int,
    session: SessionDep,
) -> Any:
    """
    Get stock overview by ID.
    """
    stock = session.get(Stock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    return {
        "id": stock.id,
        "ticker": stock.ticker,
        "exchange": stock.exchange,
        "company_name": stock.company_name,
        "is_active": stock.is_active,
        "created_at": stock.created_at
    }

@router.get("/{stock_id}/facts", response_model=list[dict])
def read_stock_facts(
    stock_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    Get normalized metric facts for a stock.
    """
    # Verify stock exists
    stock = session.get(Stock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    admin_user_ids = list(session.scalars(select(User.id).where(User.role == "admin")).all())

    # Get current facts
    stmt = select(MetricFact).where(
        MetricFact.stock_id == stock_id,
        MetricFact.is_current.is_(True),
        _visible_fact_predicate(current_user.id, admin_user_ids),
    )
    facts = session.scalars(stmt).all()

    return [
        {
            "id": f.id,
            "metric_key": f.metric_key,
            "value_numeric": f.value_numeric,
            "unit": f.unit,
            "period": f.period,
            "period_end_date": f.period_end_date,
            "source_type": f.source_type
        }
        for f in facts
    ]


@router.put("/{stock_id}/facts", response_model=dict)
def upsert_stock_fact(
    *,
    stock_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    payload: dict = Body(...),
) -> Any:
    user_id = current_user.id

    stock = session.get(Stock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    metric_key = payload.get("metric_key")
    value_numeric = payload.get("value_numeric")
    if metric_key != FAIR_VALUE_KEY:
        raise HTTPException(status_code=400, detail="Unsupported metric_key")
    if value_numeric is None or not isinstance(value_numeric, (int, float)):
        raise HTTPException(status_code=400, detail="value_numeric must be a number")

    session.execute(
        update(MetricFact)
        .where(
            MetricFact.user_id == user_id,
            MetricFact.stock_id == stock_id,
            MetricFact.metric_key == metric_key,
            MetricFact.is_current.is_(True),
        )
        .values(is_current=False)
    )

    now_et = datetime.now(timezone.utc).astimezone(ET)
    fact = MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
        value_numeric=float(value_numeric),
        unit="USD",
        period_type="AS_OF",
        period_end_date=now_et.date(),
        source_type="manual",
        is_current=True,
    )
    session.add(fact)
    session.commit()
    session.refresh(fact)

    return {
        "id": fact.id,
        "stock_id": fact.stock_id,
        "metric_key": fact.metric_key,
        "value_numeric": fact.value_numeric,
        "unit": fact.unit,
        "period_type": fact.period_type,
        "period_end_date": fact.period_end_date,
        "source_type": fact.source_type,
        "is_current": fact.is_current,
        "created_at": fact.created_at,
    }


@router.post("/prices/refresh", response_model=list[dict])
def refresh_stock_prices(
    session: SessionDep,
    current_user: CurrentUser,
    payload: dict = Body(...),
) -> Any:
    stock_ids = payload.get("stock_ids")
    reason = payload.get("reason", "unspecified")
    if not isinstance(stock_ids, list) or not stock_ids:
        raise HTTPException(status_code=400, detail="stock_ids must be a non-empty list")

    service = MarketDataService(session)
    return service.refresh_stock_prices(stock_ids, reason=reason)
