from typing import Any
from fastapi import APIRouter, HTTPException, Body
from sqlalchemy import select, func
from app.api.deps import SessionDep
from app.models.stocks import Stock
from app.models.facts import MetricFact
from app.services.market_data_service import MarketDataService

router = APIRouter()

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
        "pe": facts_by_key.get("val.pe"),
        "oeps_normalized": facts_by_key.get("owners_earnings_per_share_normalized"),
        "oeps_series": oeps_series,
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
) -> Any:
    """
    Get normalized metric facts for a stock.
    """
    # Verify stock exists
    stock = session.get(Stock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    # Get current facts
    stmt = select(MetricFact).where(
        MetricFact.stock_id == stock_id,
        MetricFact.is_current.is_(True)
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


@router.post("/prices/refresh", response_model=list[dict])
def refresh_stock_prices(
    session: SessionDep,
    payload: dict = Body(...),
) -> Any:
    stock_ids = payload.get("stock_ids")
    reason = payload.get("reason", "unspecified")
    if not isinstance(stock_ids, list) or not stock_ids:
        raise HTTPException(status_code=400, detail="stock_ids must be a non-empty list")

    service = MarketDataService(session)
    return service.refresh_stock_prices(stock_ids, reason=reason)
