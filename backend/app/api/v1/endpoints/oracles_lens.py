from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import OptionalCurrentUser, get_db
from app.models.institutions import InstitutionManager
from app.services.oracles_lens.dashboard import build_oracles_lens_dashboard
from app.services.oracles_lens.manager_universe import (
    resolve_manager_id_allowlist,
)
from app.services.metric_fact_currentness import (
    HistoricalCurrentnessUnverifiableError,
)

router = APIRouter()


def _parse_csv(value: str | None) -> list[str]:
    """Parse a comma-separated query-param value into a clean list.

    Accepts both ``?style_primary=a,b`` (single param, comma-joined)
    and ``?style_primary=`` (empty). Strips whitespace and drops empty
    tokens so ``?style_primary=,a,,b,`` is still {a, b}.
    """
    if not value:
        return []
    return [token.strip() for token in value.split(",") if token.strip()]


def _superinvestor_universe_size(session: Session, *, superinvestor_only: bool) -> int:
    """How many confirmed managers are eligible to contribute to the
    'All' universe (the denominator in 'X of N managers')."""
    query = session.query(func.count(InstitutionManager.id)).filter(
        InstitutionManager.match_status == "confirmed",
        InstitutionManager.cik.isnot(None),
    )
    if superinvestor_only:
        query = query.filter(InstitutionManager.is_superinvestor.is_(True))
    return int(query.scalar() or 0)


@router.get("/oracles-lens", response_model=dict)
def read_oracles_lens_dashboard(
    current_user: OptionalCurrentUser,
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
    style_primary: str | None = Query(
        None,
        description=(
            "Manager-universe filter: comma-separated subset of the "
            "STYLE_PRIMARY V2 vocabulary (e.g. "
            "``value_deep,value_concentrated,quality_compounder`` for "
            "the Deep Value Consensus preset). When set, Signal / "
            "Conviction / Distinctive scores recompute over the "
            "filtered manager subset; the persisted "
            "``oracles_lens_signals`` rows (which reflect the "
            "all-managers universe) are bypassed for this request."
        ),
    ),
    capital_structure: str | None = Query(
        None,
        description=(
            "Manager-universe filter: comma-separated subset of "
            "CAPITAL_STRUCTURE (e.g. ``permanent_capital``)."
        ),
    ),
    market_cap_focus: str | None = Query(
        None,
        description=(
            "Manager-universe filter: comma-separated subset of "
            "MARKET_CAP_FOCUS (e.g. ``small,micro`` for the "
            "Small-cap Sleuths preset)."
        ),
    ),
    db: Session = Depends(get_db),
) -> Any:
    style_list = _parse_csv(style_primary)
    capital_list = _parse_csv(capital_structure)
    market_cap_list = _parse_csv(market_cap_focus)
    try:
        allowlist = resolve_manager_id_allowlist(
            db,
            style_primary=style_list,
            capital_structure=capital_list,
            market_cap_focus=market_cap_list,
            superinvestor_only=superinvestor_only,
        )
    except HistoricalCurrentnessUnverifiableError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    universe_metadata: dict[str, Any] = {
        "applied_filters": {
            "style_primary": style_list,
            "capital_structure": capital_list,
            "market_cap_focus": market_cap_list,
        },
        "filtered_manager_count": (
            len(allowlist) if allowlist is not None
            else _superinvestor_universe_size(db, superinvestor_only=superinvestor_only)
        ),
        "total_manager_count": _superinvestor_universe_size(
            db, superinvestor_only=superinvestor_only,
        ),
    }

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
            manager_id_allowlist=allowlist,
            universe_metadata=universe_metadata,
            user_id=current_user.id if current_user else None,
        )
    except HistoricalCurrentnessUnverifiableError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
