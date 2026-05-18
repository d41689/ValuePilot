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

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.stocks_13f_snapshot import (
    AvailableStockDetail,
    AvailableStockSnapshot,
    QualityOverlay,
    StockDetailCaveatFlag,
    StockDetailResponse,
    StockDetailTopHolder,
    StockSnapshotRequest,
    StockSnapshotResponse,
    UnavailableStockDetail,
    UnavailableStockSnapshot,
)
from app.services.oracles_lens.dashboard import (
    _m3_facts_by_stock,
    build_oracles_lens_dashboard,
)

router = APIRouter()

# MVP8-A2: metric keys used by the drawer M3 panel.
_M3_METRIC_KEYS: list[str] = [
    "score.piotroski.total",
    "target.price_18m.mid",
    "target.price_18m.low",
    "target.price_18m.high",
    "proj.long_term.low_price",
    "proj.long_term.high_price",
    "quality.earnings_predictability",
]


def _m3_panel_for_stock(db: Session, stock_id: int) -> QualityOverlay:
    """Compact M3 quality/valuation overlay for the Watchlist drawer.

    Returns ``QualityOverlay(has_value_line=False)`` when no Value Line
    facts exist for the stock. Never raises — missing data is a
    first-class state.

    Data fetching delegated to :func:`_m3_facts_by_stock` in the
    ``oracles_lens.dashboard`` service so the legacy Oracle's Lens
    quality overlay and this drawer panel share the same
    most-recent-per-(stock, metric_key) read primitive (D2 of
    post-MVP8-A2 sweep). Return is a typed ``QualityOverlay`` Pydantic
    model so the API contract is enforced at this boundary (D1).
    """
    by_key = _m3_facts_by_stock(db, [stock_id], _M3_METRIC_KEYS).get(stock_id, {})
    if not by_key:
        return QualityOverlay(has_value_line=False)

    # Piotroski is stored in value_json (value_numeric is null for most rows).
    # PR #33 Backend B2: defensive coercion. The docstring promises this
    # function never raises — direct ``int(raw)`` would 500 the endpoint
    # if a future parser writes a malformed value_json (dict, list,
    # non-numeric string). Bool also rejected explicitly because
    # ``bool`` subclasses ``int`` and ``int(True) == 1`` would silently
    # coerce an "indicator was met" flag into a score of 1.
    def _coerce_int(raw: Any) -> int | None:
        if raw is None or isinstance(raw, bool):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    piotroski_score: int | None = None
    piotroski_max: int | None = None
    piotroski_status: str | None = None
    piotroski_fact = by_key.get("score.piotroski.total")
    if piotroski_fact and isinstance(piotroski_fact.value_json, dict):
        vj = piotroski_fact.value_json
        piotroski_score = _coerce_int(vj.get("partial_score"))
        piotroski_max = _coerce_int(vj.get("max_available_score"))
        raw_status = vj.get("status")
        piotroski_status = str(raw_status) if isinstance(raw_status, str) else None

    def _num(key: str) -> float | None:
        fact = by_key.get(key)
        if fact is not None and fact.value_numeric is not None:
            return float(fact.value_numeric)
        return None

    # D1 provenance: source the as-of date + document_id from the
    # ``target.price_18m.mid`` fact (the one the drawer renders most
    # prominently). When multiple VL publications exist, the helper's
    # tiebreak already picked the most recent.
    target_mid_fact = by_key.get("target.price_18m.mid")
    vl_target_period_end: str | None = None
    vl_target_source_document_id: int | None = None
    if target_mid_fact is not None:
        if target_mid_fact.period_end_date is not None:
            vl_target_period_end = target_mid_fact.period_end_date.isoformat()
        vl_target_source_document_id = target_mid_fact.source_document_id

    return QualityOverlay(
        has_value_line=True,
        piotroski_score=piotroski_score,
        piotroski_max=piotroski_max,
        piotroski_status=piotroski_status,
        earnings_predictability=_num("quality.earnings_predictability"),
        vl_target_mid=_num("target.price_18m.mid"),
        vl_target_low=_num("target.price_18m.low"),
        vl_target_high=_num("target.price_18m.high"),
        vl_3y_low=_num("proj.long_term.low_price"),
        vl_3y_high=_num("proj.long_term.high_price"),
        vl_target_period_end=vl_target_period_end,
        vl_target_source_document_id=vl_target_source_document_id,
    )


# Distinctiveness tier thresholds (Pre-MVP7-01 D1 heuristic, V1).
_DISTINCTIVE_MAX_CONSENSUS = 8
_DISTINCTIVE_MIN_COVERAGE = 0.7
_CROWDED_MIN_CONSENSUS = 20
# MVP8-03B B2: ``crowded`` gates on the admin-unknown ratio rather than
# the derived coverage. ``derive_manager_signal_profile`` overwrites the
# admin classification with a behavior-derived one, so the original
# derived-coverage rule almost never fired (audit on 2025-Q3 universe:
# 0 ``crowded`` stocks). The admin-unknown ratio reflects whether the
# operator has actually vetted each holder, not whether the scorer can
# guess from behavior.
_CROWDED_MIN_ADMIN_UNKNOWN_RATIO = 0.5

# The persisted scoring service writes score_confidence using the
# OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS vocabulary ("high_confidence" etc.).
# The watchlist API surface and its Pydantic schemas use the shorter
# watchlist vocabulary ("high" | "medium" | "low"). Normalize at the
# API boundary so the endpoint doesn't throw a ValidationError when
# use_persisted_scores=True is the server default (post-MVP8-01).
_SCORE_CONFIDENCE_NORMALIZE: dict[str, str] = {
    "high_confidence": "high",
    "medium_confidence": "medium",
    "low_confidence": "low",
    "unavailable": "low",
}


def _normalize_score_confidence(raw: str | None) -> str:
    if not raw:
        return "low"
    return _SCORE_CONFIDENCE_NORMALIZE.get(raw, raw) or "low"


def _distinctiveness_tier(
    consensus_count: int,
    coverage: float,
    *,
    admin_unknown_ratio: float = 0.0,
) -> str:
    if (
        consensus_count <= _DISTINCTIVE_MAX_CONSENSUS
        and coverage >= _DISTINCTIVE_MIN_COVERAGE
    ):
        return "distinctive"
    if (
        consensus_count >= _CROWDED_MIN_CONSENSUS
        and admin_unknown_ratio > _CROWDED_MIN_ADMIN_UNKNOWN_RATIO
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
    admin_unknown_count = int(manager_summary.get("admin_unknown_manager_type_count") or 0)
    admin_unknown_ratio = (admin_unknown_count / consensus_count) if consensus_count else 0.0
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
        adders_portfolio_weight_sum=float(manager_summary.get("adders_portfolio_weight_sum") or 0.0),
        reducers_portfolio_weight_sum=float(manager_summary.get("reducers_portfolio_weight_sum") or 0.0),
        consensus_count=consensus_count,
        distinctiveness_tier=_distinctiveness_tier(
            consensus_count, coverage, admin_unknown_ratio=admin_unknown_ratio,
        ),
        caveat_severity=_caveat_severity_from_flags(caveat_flags),
        caveat_codes=caveat_codes,
        score_confidence=_normalize_score_confidence(item.get("score_confidence")),
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
    use_persisted_scores: bool = Query(
        True,
        description=(
            "MVP8-01 (Phase 3, 2026-05-13): default ``True`` — lockstep "
            "with ``/oracles-lens``. The ``false`` escape hatch forces "
            "the legacy in-memory dashboard formula for the observation "
            "window; Phase 4 will retire it."
        ),
    ),
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
            use_persisted_scores=use_persisted_scores,
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


# ----- MVP7-05 detail endpoint -------------------------------------------


def _top_holder_from_payload(holder: dict[str, Any]) -> StockDetailTopHolder:
    return StockDetailTopHolder(
        manager_id=int(holder["manager_id"]),
        manager_name=str(holder.get("manager_name") or ""),
        manager_type=str(holder.get("manager_type") or "unknown"),
        manager_type_admin_classified=str(
            holder.get("manager_type_admin_classified") or "unknown"
        ),
        manager_signal_weight=float(holder.get("manager_signal_weight") or 0),
        position_weight=float(holder.get("position_weight") or 0),
        position_rank=(
            int(holder["position_rank"])
            if holder.get("position_rank") is not None
            else None
        ),
        action=str(holder.get("action") or "flat"),
        share_delta_pct=(
            float(holder["share_delta_pct"])
            if holder.get("share_delta_pct") is not None
            else None
        ),
        current_shares=(
            int(holder["current_shares"])
            if holder.get("current_shares") is not None
            else None
        ),
        previous_shares=(
            int(holder["previous_shares"])
            if holder.get("previous_shares") is not None
            else None
        ),
        current_value_thousands=(
            int(holder["current_value_thousands"])
            if holder.get("current_value_thousands") is not None
            else None
        ),
        holding_streak_quarters=int(holder.get("holding_streak_quarters") or 0),
        portfolio_concentration=(
            float(holder["portfolio_concentration"])
            if holder.get("portfolio_concentration") is not None
            else None
        ),
        portfolio_holding_count=(
            int(holder["portfolio_holding_count"])
            if holder.get("portfolio_holding_count") is not None
            else None
        ),
        average_holding_period_quarters=(
            float(holder["average_holding_period_quarters"])
            if holder.get("average_holding_period_quarters") is not None
            else None
        ),
        filing_date=(
            str(holder["filing_date"])
            if holder.get("filing_date") is not None
            else None
        ),
        accession_no=(
            str(holder["accession_no"])
            if holder.get("accession_no") is not None
            else None
        ),
        cik=(
            str(holder["cik"])
            if holder.get("cik") is not None
            else None
        ),
    )


def _caveat_flag_from_payload(flag: dict[str, Any]) -> StockDetailCaveatFlag:
    severity = str(flag.get("severity") or "info")
    if severity not in {"warning", "info"}:
        severity = "info"
    return StockDetailCaveatFlag(
        key=str(flag.get("key") or ""),
        group=str(flag.get("group") or "general"),
        severity=severity,  # type: ignore[arg-type]
        label=str(flag.get("label") or ""),
    )


def _stock_meta(db: Session, stock_id: int) -> tuple[str, str | None] | None:
    """Return ``(ticker, company_name)`` for the stock, or ``None`` when the
    stock_id doesn't exist."""
    from app.models.stocks import Stock

    stock = db.get(Stock, stock_id)
    if stock is None:
        return None
    return (stock.ticker or "", stock.company_name)


@router.get("/{stock_id}/13f-detail", response_model=StockDetailResponse)
def read_stock_13f_detail(
    stock_id: int,
    period: str | None = None,
    use_persisted_scores: bool = Query(
        True,
        description=(
            "MVP8-01 (Phase 3, 2026-05-13): default ``True`` — lockstep "
            "with ``/oracles-lens``. The ``false`` escape hatch forces "
            "the legacy in-memory dashboard formula for the observation "
            "window; Phase 4 will retire it."
        ),
    ),
    db: Session = Depends(get_db),
) -> StockDetailResponse:
    """MVP7-05: detail panel for one watchlist row. Returns the same
    column-summary fields as the batch endpoint plus ``top_holders[:3]``
    and the full ``caveat_flags`` list."""
    meta = _stock_meta(db, stock_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Stock {stock_id} not found.")
    ticker, company_name = meta

    period_arg = None if period in (None, "latest") else period
    try:
        dashboard = build_oracles_lens_dashboard(
            db,
            period=period_arg,
            limit=0,
            use_persisted_scores=use_persisted_scores,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    period_label = dashboard.get("period")
    period_end_iso = dashboard.get("period_end_date")
    filing_deadline = _period_filing_deadline(period_end_iso)
    items: list[dict[str, Any]] = dashboard.get("items") or []
    sorted_items = sorted(
        items,
        key=lambda i: float(i.get("conviction_score") or 0),
        reverse=True,
    )
    universe_size = len(sorted_items)

    if period_label is None or period_end_iso is None or universe_size == 0:
        return StockDetailResponse(
            period=period_label,
            period_filing_deadline=filing_deadline,
            universe_size=universe_size,
            detail=UnavailableStockDetail(
                stock_id=stock_id,
                ticker=ticker,
                company_name=company_name,
                unavailable_reason="no_qualifying_period",
            ),
        )

    rank_by_stock: dict[int, int] = {}
    for index, item in enumerate(sorted_items, start=1):
        sid = int(item.get("stock_id") or 0)
        if sid:
            rank_by_stock[sid] = index

    item = next(
        (i for i in items if int(i.get("stock_id") or 0) == stock_id),
        None,
    )
    if item is None:
        holdings_count = _holdings_count_for_stock(db, stock_id, period_end_iso)
        return StockDetailResponse(
            period=period_label,
            period_filing_deadline=filing_deadline,
            universe_size=universe_size,
            detail=UnavailableStockDetail(
                stock_id=stock_id,
                ticker=ticker,
                company_name=company_name,
                unavailable_reason=(
                    "below_min_holders" if holdings_count > 0 else "no_holders"
                ),
            ),
        )

    rank = rank_by_stock.get(stock_id, universe_size)
    percentile = 1.0 - (rank - 1) / universe_size

    manager_summary = item.get("manager_signal_summary") or {}
    coverage = float(manager_summary.get("manager_signal_quality_coverage") or 0.0)
    consensus_count = int(item.get("consensus_count") or 0)
    admin_unknown_count = int(manager_summary.get("admin_unknown_manager_type_count") or 0)
    admin_unknown_ratio = (admin_unknown_count / consensus_count) if consensus_count else 0.0
    caveat_flags = item.get("caution_flags") or []

    top_holders = [
        _top_holder_from_payload(holder)
        for holder in (item.get("top_holders") or [])
    ]
    structured_caveats = [
        _caveat_flag_from_payload(flag)
        for flag in caveat_flags
        if isinstance(flag, dict)
    ]

    detail = AvailableStockDetail(
        stock_id=stock_id,
        ticker=ticker,
        company_name=company_name,
        conviction_score=float(item.get("conviction_score") or 0),
        conviction_percentile=percentile,
        delta_holders=(
            int(item.get("adders_count") or 0)
            - int(item.get("reducers_count") or 0)
        ),
        adders_count=int(item.get("adders_count") or 0),
        reducers_count=int(item.get("reducers_count") or 0),
        adders_portfolio_weight_sum=float(manager_summary.get("adders_portfolio_weight_sum") or 0.0),
        reducers_portfolio_weight_sum=float(manager_summary.get("reducers_portfolio_weight_sum") or 0.0),
        consensus_count=consensus_count,
        distinctiveness_tier=_distinctiveness_tier(
            consensus_count, coverage, admin_unknown_ratio=admin_unknown_ratio,
        ),
        caveat_severity=_caveat_severity_from_flags(caveat_flags),
        score_confidence=_normalize_score_confidence(item.get("score_confidence")),
        top_holders=top_holders,
        caveat_flags=structured_caveats,
        quality_overlay=_m3_panel_for_stock(db, stock_id),
    )

    return StockDetailResponse(
        period=period_label,
        period_filing_deadline=filing_deadline,
        universe_size=universe_size,
        detail=detail,
    )
