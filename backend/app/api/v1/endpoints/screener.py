from typing import Any, List, Dict
from fastapi import APIRouter, HTTPException, Body
from app.api.deps import SessionDep
from app.services.screener_service import ScreenerService

router = APIRouter()

@router.post("/run", response_model=List[dict])
def run_screen(
    session: SessionDep,
    rule: Dict[str, Any] = Body(..., example={
        "type": "AND",
        "conditions": [
            {"metric": "pe_ratio", "operator": "<", "value": 25},
            {"metric": "dividend_yield", "operator": ">", "value": 0.01}
        ]
    })
) -> Any:
    """
    Run a stock screen based on dynamic rules.
    """
    service = ScreenerService(session)
    try:
        results = service.execute_screen(rule)
        return [
            {
                "id": stock.id,
                "ticker": stock.ticker,
                "company_name": stock.company_name
            }
            for stock in results
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
