from typing import Any, List, Dict
from fastapi import APIRouter, HTTPException, Body
from app.api.deps import SessionDep, CurrentUser
from app.services.screener_service import ScreenerService
from app.services.canonical_financials import (
    CanonicalSourceConflictError,
    CanonicalUnavailableError,
    PiotroskiMethodAuthorityError,
    UnsupportedSystemMethodError,
)
from app.services.source_reconciliation import CanonicalReconciliationError

router = APIRouter()

@router.post("/run", response_model=List[dict])
def run_screen(
    session: SessionDep,
    current_user: CurrentUser,
    rule: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Simple AND screen",
                "value": {
                    "type": "AND",
                    "conditions": [
                        {"metric": "pe_ratio", "operator": "<", "value": 25},
                        {"metric": "dividend_yield", "operator": ">", "value": 0.01},
                    ],
                },
            },
        },
    ),
) -> Any:
    """
    Run a stock screen based on dynamic rules.
    """
    service = ScreenerService(session)
    try:
        results = service.execute_screen(rule, current_user_id=current_user.id)
        stock_ids = [stock.id for stock in results]
        metrics_by_stock = service.fetch_metrics_for_stocks(
            stock_ids,
            current_user_id=current_user.id,
            selected_source_type=rule.get("source_type"),
        )
        return [
            {
                "id": stock.id,
                "ticker": stock.ticker,
                "company_name": stock.company_name,
                "metrics": metrics_by_stock.get(stock.id, {}),
            }
            for stock in results
        ]
    except (
        CanonicalSourceConflictError,
        CanonicalUnavailableError,
        CanonicalReconciliationError,
        PiotroskiMethodAuthorityError,
        UnsupportedSystemMethodError,
    ) as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "message": str(error),
                "source_types": list(getattr(error, "source_types", ())),
                "blocking_reasons": sorted(
                    {
                        str(item.get("reason_code"))
                        for item in getattr(error, "blocking_items", ())
                    }
                ),
            },
        ) from error
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
