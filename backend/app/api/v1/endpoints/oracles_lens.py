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
        True,
        description=(
            "MVP8-01 (MVP5-03 Phase 3, 2026-05-13): server default is "
            "now ``True`` — the persisted ``oracles_lens_signals`` rows "
            "for the requested period at the current SCORE_VERSION are "
            "the canonical signal-weighted score path. Setting "
            "``use_persisted_scores=false`` is the observation-window "
            "escape hatch that forces the legacy in-memory dashboard "
            "formula; Phase 4 will retire that flag after one full "
            "scoring cycle with no material divergence."
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
