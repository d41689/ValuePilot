"""MVP4-02 base scoring primitives.

Three shared inputs that MVP4-03 (signal-weighted consensus) and
MVP4-04 (conviction score) consume:

  - :func:`compute_portfolio_weight` — plan §7.3, per-holding weight.
  - :func:`compute_holding_streak` — plan §7.10, consecutive-quarter
    ownership count.
  - :func:`compute_add_intensity` — plan §7.4, shares-delta intensity.

Per the MVP4 decision gate's MVP4-01 pre-start condition #3, scoring
reads ``holdings_13f`` joined to the active ``Filing13F`` / current
``ParseRun13F`` (PRD §7.3 query contract). The cross-quarter walks
required by §7.4 / §7.10 happen here; ``ownership_changes`` is not
consulted.

D2 / D3 caveat-propagation rules are surfaced as canonical caveat
code constants on the result dataclasses. MVP4-05 will map them onto
the user-facing caution-flags surface; here we only emit them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.institutions import (
    Filing13F,
    Holding13F,
    ParseRun13F,
    QualityFinding13F,
)
from app.services.thirteenf_holdings_query import HR_FORM_TYPES
from app.services.thirteenf_quality_codes import (
    HISTORICAL_BACKFILL_NEEDS_VALIDATION as _BACKFILL_FINDING_RULE_CODE,
    OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION as _RECOMPUTE_FINDING_RULE_CODE,
)

# ---------------------------------------------------------------------------
# Canonical caveat codes (consumed by MVP4-05 caution-flags surface)
# ---------------------------------------------------------------------------

# D3 rule (a): partial-coverage filing has no per-manager denominator.
PARTIAL_COVERAGE_CAVEAT = "PARTIAL_COVERAGE"

# D3 rule (d): NT quarter resets the streak; not an exit.
NT_QUARTER_STREAK_BREAK_CAVEAT = "NT_QUARTER_STREAK_BREAK"

# D3 rule (b): open OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION
# finding means the stored cross-quarter delta may be wrong. Score-emitted
# row-level code, not a readiness pass-through.
STALE_UNTIL_RECOMPUTE_CAVEAT = "stale_until_recompute"

# D3 rule (e): open HISTORICAL_BACKFILL_NEEDS_VALIDATION finding means the
# underlying holding row is awaiting validation; readiness pass-through
# spelling preserved so the user-facing API surfaces a single canonical
# string for this concept.
HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT = "HISTORICAL_BACKFILL_NEEDS_VALIDATION"

# D2: walking back across the data-window floor; pre-window ownership is
# not observable, so streak/intensity inputs are right-censored.
PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT = "PRE_2023_PRE_HISTORY_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioWeightResult:
    value: Optional[Decimal]
    caveats: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HoldingStreakResult:
    streak_quarters: int
    caveats: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AddIntensityResult:
    value: Optional[Decimal]
    caveats: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# compute_portfolio_weight (plan §7.3)
# ---------------------------------------------------------------------------


def compute_portfolio_weight(holding: Holding13F) -> PortfolioWeightResult:
    """Per-holding portfolio weight.

    Returns ``None`` with a ``PARTIAL_COVERAGE`` caveat when the parent
    filing is a Combination Report (PRD §7.2 line 588–592 mandates
    portfolio_weight_pct=NULL); returns ``None`` (no caveat) when neither
    computed nor reported total is available.
    """
    filing: Filing13F = holding.filing
    if filing.coverage_completeness == "partial":
        return PortfolioWeightResult(value=None, caveats=[PARTIAL_COVERAGE_CAVEAT])

    denominator = filing.computed_total_value_thousands or filing.reported_total_value_thousands
    if not denominator or not holding.value_thousands:
        return PortfolioWeightResult(value=None)

    weight = Decimal(holding.value_thousands) / Decimal(denominator)
    return PortfolioWeightResult(value=weight)


# ---------------------------------------------------------------------------
# Quarter math (local copy — shared helper moves to MVP4-09 if a third
# consumer appears)
# ---------------------------------------------------------------------------


def _quarter_key(quarter: str) -> tuple[int, int]:
    year_str, qtr_str = quarter.split("-Q", 1)
    return int(year_str), int(qtr_str)


def _previous_quarter(quarter: str) -> str:
    year, qtr = _quarter_key(quarter)
    if qtr == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{qtr - 1}"


# ---------------------------------------------------------------------------
# compute_holding_streak (plan §7.10)
# ---------------------------------------------------------------------------


def _is_nt_quarter(session: Session, *, manager_id: int, quarter: str) -> bool:
    return (
        session.query(Filing13F.id)
        .filter(Filing13F.manager_id == manager_id)
        .filter(Filing13F.report_quarter == quarter)
        .filter(Filing13F.form_type == "13F-NT")
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .first()
        is not None
    )


def _has_active_holding(
    session: Session, *, manager_id: int, stock_id: int, quarter: str
) -> bool:
    return (
        session.query(Holding13F.id)
        .join(ParseRun13F, Holding13F.parse_run_id == ParseRun13F.id)
        .join(Filing13F, Filing13F.accession_number == ParseRun13F.accession_number)
        .filter(Filing13F.form_type.in_(HR_FORM_TYPES))
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .filter(ParseRun13F.is_current.is_(True))
        .filter(Holding13F.manager_id == manager_id)
        .filter(Holding13F.stock_id == stock_id)
        .filter(Holding13F.report_quarter == quarter)
        .first()
        is not None
    )


def _shares_for_holding(
    session: Session, *, manager_id: int, stock_id: int, quarter: str
) -> Optional[int]:
    row = (
        session.query(Holding13F.ssh_prnamt)
        .join(ParseRun13F, Holding13F.parse_run_id == ParseRun13F.id)
        .join(Filing13F, Filing13F.accession_number == ParseRun13F.accession_number)
        .filter(Filing13F.form_type.in_(HR_FORM_TYPES))
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .filter(ParseRun13F.is_current.is_(True))
        .filter(Holding13F.manager_id == manager_id)
        .filter(Holding13F.stock_id == stock_id)
        .filter(Holding13F.report_quarter == quarter)
        .first()
    )
    return row[0] if row else None


def compute_holding_streak(
    session: Session,
    *,
    manager_id: int,
    stock_id: int,
    current_quarter: str,
    lookback: int = 8,
    data_window_start_quarter: str = "2023-Q1",
) -> HoldingStreakResult:
    """Count consecutive quarters of active ownership ending at ``current_quarter``.

    Per D3 rule (d) an NT quarter resets the streak with the
    ``NT_QUARTER_STREAK_BREAK`` caveat. Per D2 if the walk reaches the
    data-window floor while still active, emit
    ``PRE_2023_PRE_HISTORY_UNAVAILABLE`` so callers know the streak is
    right-censored.
    """
    caveats: list[str] = []
    streak = 0
    cursor = current_quarter
    floor = _quarter_key(data_window_start_quarter)

    for _ in range(lookback):
        if _has_active_holding(session, manager_id=manager_id, stock_id=stock_id, quarter=cursor):
            streak += 1
        elif _is_nt_quarter(session, manager_id=manager_id, quarter=cursor):
            # NT quarter: doesn't extend the streak, doesn't terminate as exit.
            # The streak resets to what we've accumulated since the NT — i.e.,
            # we stop walking but record the caveat.
            if NT_QUARTER_STREAK_BREAK_CAVEAT not in caveats:
                caveats.append(NT_QUARTER_STREAK_BREAK_CAVEAT)
            break
        else:
            # Genuine non-owning quarter → terminate as exit.
            break

        if _quarter_key(cursor) <= floor:
            # Reached the data-window floor; pre-window history not observable.
            if PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT not in caveats:
                caveats.append(PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT)
            break

        cursor = _previous_quarter(cursor)

    return HoldingStreakResult(streak_quarters=streak, caveats=caveats)


# ---------------------------------------------------------------------------
# compute_add_intensity (plan §7.4)
# ---------------------------------------------------------------------------


def _has_open_finding_for(
    session: Session, *, rule_code: str, manager_id: int, quarter: str
) -> bool:
    return (
        session.query(QualityFinding13F.id)
        .filter(QualityFinding13F.rule_code == rule_code)
        .filter(QualityFinding13F.status == "open")
        .filter(QualityFinding13F.manager_id == manager_id)
        .filter(QualityFinding13F.quarter == quarter)
        .first()
        is not None
    )


def compute_add_intensity(
    session: Session,
    *,
    manager_id: int,
    stock_id: int,
    current_quarter: str,
    data_window_start_quarter: str = "2023-Q1",
) -> AddIntensityResult:
    """Plan §7.4 add intensity in shares space.

    Result vocabulary:
    - ``None`` + ``PRE_2023_PRE_HISTORY_UNAVAILABLE`` when previous quarter
      is before the data-window floor (right-censored, can't say new vs
      pre-existing).
    - ``Decimal("0.0")`` + ``stale_until_recompute`` when an open
      ``OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`` finding
      exists for the holder × ``current_quarter``.
    - ``Decimal("0.0")`` + ``HISTORICAL_BACKFILL_NEEDS_VALIDATION`` when an
      open backfill-validation finding exists.
    - ``Decimal("1.0")`` for a new position (holder had no prior quarter
      shares, but previous quarter is after the floor).
    - ``Decimal("-1.0")`` for a full exit (current quarter has no holding
      but previous did).
    - Otherwise ``(current - previous) / max(current, previous)`` in
      ``[-1, 1]``.
    """
    caveats: list[str] = []

    # D3 rules (b) and (e): snap to flat when an open finding suggests the
    # stored cross-quarter values may be wrong. Caveats fire before the
    # numerical computation runs so a downstream score consumer sees the
    # demotion before it sees a misleading magnitude.
    if _has_open_finding_for(
        session, rule_code=_RECOMPUTE_FINDING_RULE_CODE,
        manager_id=manager_id, quarter=current_quarter,
    ):
        caveats.append(STALE_UNTIL_RECOMPUTE_CAVEAT)
    if _has_open_finding_for(
        session, rule_code=_BACKFILL_FINDING_RULE_CODE,
        manager_id=manager_id, quarter=current_quarter,
    ):
        caveats.append(HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT)
    if caveats:
        return AddIntensityResult(value=Decimal("0.0"), caveats=caveats)

    previous_quarter = _previous_quarter(current_quarter)
    pre_window = _quarter_key(previous_quarter) < _quarter_key(data_window_start_quarter)

    current_shares = _shares_for_holding(
        session, manager_id=manager_id, stock_id=stock_id, quarter=current_quarter,
    )
    previous_shares = _shares_for_holding(
        session, manager_id=manager_id, stock_id=stock_id, quarter=previous_quarter,
    )

    if previous_shares is None:
        if pre_window:
            # Previous quarter is before the data-window floor; we cannot say
            # whether this is a new position or a pre-existing holding.
            return AddIntensityResult(
                value=None,
                caveats=[PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT],
            )
        if current_shares is None:
            # No data either side — nothing to say.
            return AddIntensityResult(value=None)
        return AddIntensityResult(value=Decimal("1.0"))

    if current_shares is None:
        # Full exit.
        return AddIntensityResult(value=Decimal("-1.0"))

    denominator = max(current_shares, previous_shares)
    if denominator == 0:
        return AddIntensityResult(value=Decimal("0.0"))
    delta = Decimal(current_shares - previous_shares) / Decimal(denominator)
    return AddIntensityResult(value=delta)
