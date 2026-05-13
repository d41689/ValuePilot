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


class StockDetailCaveatFlag(BaseModel):
    key: str
    group: str
    severity: Literal["warning", "info"]
    label: str


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
    consensus_count: int
    distinctiveness_tier: DistinctivenessTier
    caveat_severity: CaveatSeverity
    score_confidence: ScoreConfidence
    # Detail-only fields.
    top_holders: list[StockDetailTopHolder]
    caveat_flags: list[StockDetailCaveatFlag]


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
