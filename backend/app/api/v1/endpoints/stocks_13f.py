"""MVP7-01: ``POST /api/v1/stocks/13f-snapshots`` batch endpoint for
the Watchlist × 13F Insight fusion.

Returns per-stock 13F-derived signals (Conviction percentile, Δ
Holders, Distinctiveness tier, Caveat severity) for a requested
``stock_ids`` subset and 13F period. Reuses
``build_oracles_lens_dashboard`` for universe ranking — no new
scoring logic.

Per Pre-MVP7-01 SR3, ``use_persisted_scores=True`` is intentionally
not exposed here; the persisted read path is gated on MVP5-03
Phase 3 PO sign-off.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.stocks_13f_snapshot import (
    AvailableStockSnapshot,
    StockSnapshotRequest,
    StockSnapshotResponse,
    UnavailableStockSnapshot,
)
from app.services.oracles_lens.dashboard import build_oracles_lens_dashboard

router = APIRouter()


# Distinctiveness tier thresholds (Pre-MVP7-01 D1 heuristic, V1).
_DISTINCTIVE_MAX_CONSENSUS = 8
_DISTINCTIVE_MIN_COVERAGE = 0.7
_CROWDED_MIN_CONSENSUS = 20
_CROWDED_MAX_COVERAGE = 0.5


def _distinctiveness_tier(consensus_count: int, coverage: float) -> str:
    if (
        consensus_count <= _DISTINCTIVE_MAX_CONSENSUS
        and coverage >= _DISTINCTIVE_MIN_COVERAGE
    ):
        return "distinctive"
    if (
        consensus_count >= _CROWDED_MIN_CONSENSUS
        and coverage < _CROWDED_MAX_COVERAGE
    ):
        return "crowded"
    return "mixed"


def _caveat_severity_from_flags(flags: list[dict[str, Any]]) -> str:
    if not flags:
        return "ok"
    if any(flag.get("severity") == "warning" for flag in flags):
        return "high-caution"
    return "caution"


def _period_filing_deadline(period_end_iso: str | None) -> str | None:
    """Return the SEC 13F filing deadline for a period (period_end + 45d).

    Input is the dashboard's ``period_end_date`` ISO string.
    """
    if not period_end_iso:
        return None
    from datetime import date

    try:
        end = date.fromisoformat(period_end_iso)
    except ValueError:
        return None
    return (end + timedelta(days=45)).isoformat()


def _snapshot_from_item(item: dict[str, Any], percentile: float) -> AvailableStockSnapshot:
    """Project a dashboard ``_stock_payload`` row + universe percentile
    into the API surface."""
    manager_summary = item.get("manager_signal_summary") or {}
    coverage = float(manager_summary.get("manager_signal_quality_coverage") or 0.0)
    consensus_count = int(item.get("consensus_count") or 0)
    caveat_flags = item.get("caution_flags") or []
    caveat_codes = [
        flag.get("key", "")
        for flag in caveat_flags
        if isinstance(flag, dict) and flag.get("key")
    ]
    return AvailableStockSnapshot(
        stock_id=int(item["stock_id"]),
        conviction_score=float(item.get("conviction_score") or 0),
        conviction_percentile=percentile,
        delta_holders=(
            int(item.get("adders_count") or 0)
            - int(item.get("reducers_count") or 0)
        ),
        adders_count=int(item.get("adders_count") or 0),
        reducers_count=int(item.get("reducers_count") or 0),
        consensus_count=consensus_count,
        distinctiveness_tier=_distinctiveness_tier(consensus_count, coverage),
        caveat_severity=_caveat_severity_from_flags(caveat_flags),
        caveat_codes=caveat_codes,
        score_confidence=str(item.get("score_confidence") or "low"),
    )


def _holdings_count_for_stock(session: Session, stock_id: int, period_end: str) -> int:
    """Count 13F holdings for a stock at a given period_end (regardless
    of whether the stock qualifies for ranking). Used to disambiguate
    ``below_min_holders`` from ``no_holders`` in the unavailable path."""
    from datetime import date

    from app.models.institutions import Filing13F, Holding13F

    try:
        end_date = date.fromisoformat(period_end)
    except ValueError:
        return 0
    return (
        session.query(Holding13F)
        .join(Filing13F, Holding13F.filing_id == Filing13F.id)
        .filter(Holding13F.stock_id == stock_id)
        .filter(Filing13F.period_of_report == end_date)
        .filter(Filing13F.is_latest_for_period == True)  # noqa: E712
        .count()
    )


@router.post("/13f-snapshots", response_model=StockSnapshotResponse)
def read_stocks_13f_snapshots(
    body: StockSnapshotRequest,
    db: Session = Depends(get_db),
) -> StockSnapshotResponse:
    # Translate the API's "latest" sentinel into the dashboard's
    # ``period=None`` for-latest-complete convention.
    period_arg = (
        None if body.period in (None, "latest") else body.period
    )
    try:
        dashboard = build_oracles_lens_dashboard(
            db,
            period=period_arg,
            limit=0,                  # disable top-50 truncation; we need the full universe for percentile
            use_persisted_scores=False,  # MVP7-01 SR3 — Phase 3 gating
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    period_label = dashboard.get("period")
    period_end_iso = dashboard.get("period_end_date")
    filing_deadline = _period_filing_deadline(period_end_iso)

    items: list[dict[str, Any]] = dashboard.get("items") or []
    # Universe ranking by conviction_score desc, ties broken by insertion
    # order (the dashboard ordering is by signal_weighted_consensus desc
    # by default; we re-sort here so percentile is conviction-aligned per
    # Pre-MVP7-01 D1).
    sorted_items = sorted(
        items,
        key=lambda i: float(i.get("conviction_score") or 0),
        reverse=True,
    )
    universe_size = len(sorted_items)

    # Build rank lookup: stock_id -> 1-indexed conviction rank.
    rank_by_stock: dict[int, int] = {}
    for index, item in enumerate(sorted_items, start=1):
        sid = int(item.get("stock_id") or 0)
        if sid:
            rank_by_stock[sid] = index

    item_by_stock: dict[int, dict[str, Any]] = {
        int(item["stock_id"]): item for item in items if "stock_id" in item
    }

    snapshots: list[AvailableStockSnapshot | UnavailableStockSnapshot] = []

    if period_label is None or period_end_iso is None or universe_size == 0:
        # No qualifying period (e.g. empty 13F universe). Return
        # all requested stocks as unavailable with the no-qualifying-
        # period reason so the frontend can render the empty-state
        # tooltip uniformly.
        return StockSnapshotResponse(
            period=period_label,
            period_filing_deadline=filing_deadline,
            universe_size=universe_size,
            snapshots=[
                UnavailableStockSnapshot(
                    stock_id=sid,
                    unavailable_reason="no_qualifying_period",
                )
                for sid in body.stock_ids
            ],
        )

    for stock_id in body.stock_ids:
        item = item_by_stock.get(stock_id)
        if item is not None:
            rank = rank_by_stock.get(stock_id)
            if rank is None:  # defensive: should be present when item is
                snapshots.append(
                    UnavailableStockSnapshot(
                        stock_id=stock_id,
                        unavailable_reason="below_min_holders",
                    )
                )
                continue
            percentile = 1.0 - (rank - 1) / universe_size
            snapshots.append(_snapshot_from_item(item, percentile))
            continue

        # Stock is not in the ranked universe. Distinguish
        # ``below_min_holders`` (some 13F holdings present, fewer than
        # min_holders) from ``no_holders`` (zero 13F coverage for the
        # period).
        holdings_count = _holdings_count_for_stock(db, stock_id, period_end_iso)
        snapshots.append(
            UnavailableStockSnapshot(
                stock_id=stock_id,
                unavailable_reason=(
                    "below_min_holders" if holdings_count > 0 else "no_holders"
                ),
            )
        )

    return StockSnapshotResponse(
        period=period_label,
        period_filing_deadline=filing_deadline,
        universe_size=universe_size,
        snapshots=snapshots,
    )
