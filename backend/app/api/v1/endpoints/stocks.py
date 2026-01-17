from typing import Any
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from app.api.deps import SessionDep
from app.models.stocks import Stock
from app.models.facts import MetricFact

router = APIRouter()

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
