"""MVP7-01: request + response schemas for the
``POST /api/v1/stocks/13f-snapshots`` batch endpoint."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ----- Request -----------------------------------------------------------

class StockSnapshotRequest(BaseModel):
    stock_ids: list[int] = Field(..., min_length=1, max_length=500)
    period: Optional[str] = Field(
        None,
        description=(
            "13F period label, e.g. '2025-Q4'. When omitted, the latest "
            "complete period is used."
        ),
        max_length=10,
    )


# ----- Response ----------------------------------------------------------

DistinctivenessTier = Literal["distinctive", "mixed", "crowded"]
CaveatSeverity = Literal["ok", "caution", "high-caution"]
ScoreConfidence = Literal["high", "medium", "low"]
UnavailableReason = Literal[
    "no_holders", "below_min_holders", "no_qualifying_period"
]


class AvailableStockSnapshot(BaseModel):
    stock_id: int
    available: Literal[True] = True
    conviction_score: float
    conviction_percentile: float = Field(..., ge=0.0, le=1.0)
    delta_holders: int
    adders_count: int
    reducers_count: int
    # MVP8-03B B4: portfolio-weight context for the Δ Holders chip
    # tooltip. Sum of position_weight across adders / reducers.
    adders_portfolio_weight_sum: float = 0.0
    reducers_portfolio_weight_sum: float = 0.0
    consensus_count: int
    distinctiveness_tier: DistinctivenessTier
    caveat_severity: CaveatSeverity
    caveat_codes: list[str]
    score_confidence: ScoreConfidence


class UnavailableStockSnapshot(BaseModel):
    stock_id: int
    available: Literal[False] = False
    unavailable_reason: UnavailableReason


class StockSnapshotResponse(BaseModel):
    period: Optional[str] = Field(
        None,
        description=(
            "Period label of the snapshots. Null when no qualifying period "
            "exists."
        ),
    )
    period_filing_deadline: Optional[str] = Field(
        None,
        description=(
            "SEC 13F filing deadline for the period (period_end + 45 days), "
            "ISO YYYY-MM-DD. Null when ``period`` is null."
        ),
    )
    universe_size: int = Field(
        ...,
        description=(
            "Total number of qualifying ranked stocks in the requested "
            "period. Zero when no qualifying period exists."
        ),
    )
    snapshots: list[AvailableStockSnapshot | UnavailableStockSnapshot]


# ----- MVP7-05 detail endpoint -------------------------------------------

class StockDetailTopHolder(BaseModel):
    manager_id: int
    manager_name: str
    manager_type: str
    # MVP8-03B B1: admin-classified manager_type alongside the canonical
    # (behavior-derived where applicable) one. Drawer renders dual chip
    # when they differ.
    manager_type_admin_classified: str = "unknown"
    manager_signal_weight: float
    position_weight: float
    position_rank: Optional[int] = None
    action: str
    share_delta_pct: Optional[float] = None
    current_shares: Optional[int] = None
    previous_shares: Optional[int] = None
    current_value_thousands: Optional[int] = None
    holding_streak_quarters: int
    portfolio_concentration: Optional[float] = None
    portfolio_holding_count: Optional[int] = None
    average_holding_period_quarters: Optional[float] = None
    filing_date: Optional[str] = None
    accession_no: Optional[str] = None
    # E-03: CIK for EDGAR filing index URL construction in the drawer.
    cik: Optional[str] = None


class StockDetailCaveatFlag(BaseModel):
    key: str
    group: str
    severity: Literal["warning", "info"]
    label: str


class QualityOverlay(BaseModel):
    """MVP8-A2 + D1: typed schema for the Watchlist drawer M3 panel.

    Replaces the prior ``Optional[dict]`` typing so the frontend contract
    is enforced at the API boundary (Pydantic validation + OpenAPI
    emission). All ten value fields default to ``None`` so callers can
    construct ``QualityOverlay(has_value_line=False)`` for the no-data
    path without populating every field.
    """

    has_value_line: bool
    piotroski_score: Optional[int] = None
    piotroski_max: Optional[int] = None
    # Known values in dev DB: "partial", "calculated". "complete" is reserved
    # for full 9-indicator Piotroski runs. Vocabulary stays open (str) until
    # the producer-side conventions are consolidated — Literal would 500 on
    # any unexpected value.
    piotroski_status: Optional[str] = None
    earnings_predictability: Optional[float] = None
    vl_target_mid: Optional[float] = None
    vl_target_low: Optional[float] = None
    vl_target_high: Optional[float] = None
    vl_3y_low: Optional[float] = None
    vl_3y_high: Optional[float] = None
    # D1 provenance: as-of date + source document for the VL 18-month
    # target row that won the most-recent tiebreak. Lets the drawer
    # render "(as of YYYY-MM-DD)" so users don't treat a stale target
    # as the current opinion (SME P2 reviewer note).
    vl_target_period_end: Optional[str] = None
    vl_target_source_document_id: Optional[int] = None


class AvailableStockDetail(BaseModel):
    stock_id: int
    ticker: str
    company_name: Optional[str] = None
    available: Literal[True] = True
    # Same column-summary fields as the batch endpoint, for header
    # recap consistency.
    conviction_score: float
    conviction_percentile: float = Field(..., ge=0.0, le=1.0)
    delta_holders: int
    adders_count: int
    reducers_count: int
    # MVP8-03B B4: portfolio-weight context for the Δ Holders chip
    # tooltip + drawer recap.
    adders_portfolio_weight_sum: float = 0.0
    reducers_portfolio_weight_sum: float = 0.0
    consensus_count: int
    distinctiveness_tier: DistinctivenessTier
    caveat_severity: CaveatSeverity
    score_confidence: ScoreConfidence
    # Detail-only fields.
    top_holders: list[StockDetailTopHolder]
    caveat_flags: list[StockDetailCaveatFlag]
    # MVP8-A2: compact M3 quality/valuation overlay from Value Line facts.
    # ``QualityOverlay(has_value_line=False, ...)`` is the no-data state.
    # Typed schema (D1 hardening) — was ``Optional[dict]`` pre-D1.
    quality_overlay: Optional[QualityOverlay] = None


class UnavailableStockDetail(BaseModel):
    stock_id: int
    ticker: Optional[str] = None
    company_name: Optional[str] = None
    available: Literal[False] = False
    unavailable_reason: UnavailableReason


class StockDetailResponse(BaseModel):
    period: Optional[str] = None
    period_filing_deadline: Optional[str] = None
    universe_size: int
    detail: AvailableStockDetail | UnavailableStockDetail
