from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.oracles_lens.dashboard import build_oracles_lens_dashboard

router = APIRouter()


@router.get("/oracles-lens", response_model=dict)
def read_oracles_lens_dashboard(
    period: str | None = Query(None, description="13F period, e.g. 2025-Q4"),
    lookback_quarters: int = Query(4, ge=1, le=20),
    min_holders: int = Query(3, ge=1, le=50),
    superinvestor_only: bool = Query(True),
    min_signal_score: float | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    sort: str = Query("signal_weighted_consensus"),
    use_persisted_scores: bool = Query(
        False,
        description=(
            "MVP4-03b: when true, return only stocks with a persisted "
            "oracles_lens_signals row for the requested period and the "
            "current SCORE_VERSION; the signal-weighted score comes "
            "from the table rather than the in-memory dashboard formula."
        ),
    ),
    db: Session = Depends(get_db),
) -> Any:
    try:
        return build_oracles_lens_dashboard(
            db,
            period=period,
            lookback_quarters=lookback_quarters,
            min_holders=min_holders,
            superinvestor_only=superinvestor_only,
            min_signal_score=min_signal_score,
            limit=limit,
            sort=sort,
            use_persisted_scores=use_persisted_scores,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
