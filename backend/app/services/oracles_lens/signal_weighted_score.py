"""MVP4-03 signal-weighted consensus score (plan §7.2).

Primary ranking metric for Oracle's Lens V1. For each stock that has
at least ``min_holders`` linked direct holdings in the active HR/HR-A
current parse run (PRD §7.3 query contract), computes:

    signal_weighted_consensus_score =
        Σ (manager_signal_weight × position_signal_weight)

Inputs come from MVP4-02 primitives (`compute_portfolio_weight`,
`compute_holding_streak`, `compute_add_intensity`) and MVP4-11
`resolve_manager_type`. The result is persisted into
`oracles_lens_signals` via ORM upsert (MVP4-01 D4) and the
per-holder component breakdown is replaced in
`oracles_lens_score_components`.

JobRun orchestration mirrors MVP3-05 / MVP3-07: a typed
`SignalWeightedBackfillError` is raised for duplicate-active enqueue
and for the `IntegrityError` race on the partial unique index, so
callers always see one predictable failure mode.

The user-facing read endpoint (plan §9.1) lives in
`api/v1/endpoints/thirteenf_admin.consumer_router`; this module
exposes the read helper it calls.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    JobRun,
    ParseRun13F,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.models.stocks import Stock
from app.services.oracles_lens.base_primitives import (
    HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT,
    NT_QUARTER_STREAK_BREAK_CAVEAT,
    PARTIAL_COVERAGE_CAVEAT,
    PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT,
    STALE_UNTIL_RECOMPUTE_CAVEAT,
    _previous_quarter,
    compute_add_intensity,
    compute_holding_streak,
    compute_portfolio_weight,
)
from app.services.oracles_lens.constants import (
    ACTION_ADJUSTMENT_ADD,
    ACTION_ADJUSTMENT_EXIT,
    ACTION_ADJUSTMENT_NEW,
    ACTION_ADJUSTMENT_REDUCE,
    MANAGER_SIGNAL_WEIGHTS,
    POSITION_BASE_BONUS_STREAK,
    POSITION_BASE_BONUS_TOP_10,
    POSITION_BASE_BONUS_WEIGHT_5PCT,
    POSITION_STREAK_THRESHOLD,
    POSITION_TOP_N_THRESHOLD,
    POSITION_WEIGHT_5PCT_THRESHOLD,
    SCORE_VERSION,
)
from app.services.oracles_lens.manager_signal import (
    DerivedManagerSignalProfile,
    derive_manager_signal_profile,
)
from app.services.oracles_lens.manager_taxonomy import resolve_manager_type
from app.services.thirteenf_holdings_query import HR_FORM_TYPES

logger = logging.getLogger(__name__)

JOB_TYPE = "oracles_lens_score_backfill"
_ACTIVE_JOB_STATUSES = ("queued", "running", "cancel_requested")
_LOW_CAVEATS = frozenset({
    STALE_UNTIL_RECOMPUTE_CAVEAT,
    HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT,
})
_MEDIUM_CAVEATS = frozenset({
    PARTIAL_COVERAGE_CAVEAT,
    NT_QUARTER_STREAK_BREAK_CAVEAT,
    PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT,
    # MVP4-05 — amendment-status caveats from Filing13F.amendment_status.
    # Same tier as PARTIAL_COVERAGE because the holder's snapshot may
    # change when the amendment lands.
    "AMENDMENTS_PENDING",
    "AMENDMENT_FAILED",
})
# Per-row CONFIDENTIAL_TREATMENT is sourced from
# Filing13F.has_confidential_treatment at compute time (not a
# base_primitives caveat). Emitted with this canonical code so the
# user-facing API surface matches the readiness vocabulary.
CONFIDENTIAL_TREATMENT_CAVEAT = "CONFIDENTIAL_TREATMENT"


class SignalWeightedBackfillError(ValueError):
    """Raised for duplicate-active enqueue or the partial-index race."""


@dataclass(frozen=True)
class PositionSignalWeightResult:
    value: Decimal
    base: Decimal
    bonus_top_10: Decimal
    bonus_weight_5pct: Decimal
    bonus_streak: Decimal
    action_adjustment: Decimal


# ---------------------------------------------------------------------------
# Pure functions (no DB)
# ---------------------------------------------------------------------------


def compute_position_signal_weight(
    *,
    portfolio_weight: Optional[Decimal],
    holding_streak_quarters: int,
    is_top_10: bool,
    add_intensity: Optional[Decimal],
    caveats: Iterable[str],
) -> PositionSignalWeightResult:
    """Plan §7.2 position_signal_weight formula. Pure function; no DB.

    Caveat-handling rule (PO-approved, 2026-05-11):

    **Class A — delta-only caveats.** Suppress only
    ``action_adjustment``; snapshot-derived inputs (portfolio_weight
    base, top-10 bonus, weight-5% bonus, streak bonus) are still
    rewarded because they describe the *current quarter's* holding
    fact, not the cross-quarter delta. Score confidence is still
    demoted to ``low`` (separately, by
    ``determine_score_confidence``).

    Class A includes:
    - ``stale_until_recompute`` (MVP3-06 corporate-action recompute
      pending — cross-quarter delta untrusted)
    - ``HISTORICAL_BACKFILL_NEEDS_VALIDATION`` (MVP3-07 backfill
      validation pending — cross-quarter delta untrusted)
    - ``PRE_2023_PRE_HISTORY_UNAVAILABLE`` (D2 — streak / add
      intensity right-censored; surfaces via the streak / intensity
      caveats already collected by MVP4-02 primitives)
    - ``OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_*`` (alias for
      ``stale_until_recompute``)

    Product rationale: "this manager really does hold AAPL at 8.2%
    portfolio weight in their top 10 with a 6-quarter streak" remains
    a true snapshot signal even when we cannot trust the
    quarter-over-quarter add/reduce/exit classification. A
    snapshot-only contribution + a ``low`` confidence label is
    honest; zeroing the whole position-signal-weight would lose the
    13F snapshot's actual value.

    **Class B — snapshot-integrity caveats** (NOT handled here).
    These corrupt the snapshot itself and should suppress the entire
    holder contribution from the primary score, not just the action
    component:
    - pending amendment affecting the current quarter's filing
    - failed amendment affecting the current quarter's filing
    - unresolved CUSIP mapping (no stock_id)
    - 13F-NT / notice reported elsewhere (no direct holdings)
    - combination report when complete manager-level weight is
      required
    - confidential treatment that omits the current holder

    Class B handling is filed as a future task — see the MVP4-03
    task log's "Class B caveats" backlog note. MVP4-03 ships only
    the Class A suppression rule.
    """
    caveat_set = set(caveats or ())
    base = Decimal(portfolio_weight) if portfolio_weight is not None else Decimal("0")

    bonus_top_10 = POSITION_BASE_BONUS_TOP_10 if is_top_10 else Decimal("0")
    bonus_weight_5pct = (
        POSITION_BASE_BONUS_WEIGHT_5PCT
        if portfolio_weight is not None and portfolio_weight >= POSITION_WEIGHT_5PCT_THRESHOLD
        else Decimal("0")
    )
    bonus_streak = (
        POSITION_BASE_BONUS_STREAK
        if holding_streak_quarters >= POSITION_STREAK_THRESHOLD
        else Decimal("0")
    )

    # D3 rules (b) / (e): when the cross-quarter delta is flagged as
    # untrusted by an open recompute / backfill-validation finding,
    # the action adjustment is clamped to 0 regardless of magnitude.
    if caveat_set & _LOW_CAVEATS:
        action_adjustment = Decimal("0")
    elif add_intensity is None:
        action_adjustment = Decimal("0")
    elif add_intensity == Decimal("0"):
        action_adjustment = Decimal("0")
    elif add_intensity == Decimal("1.0"):
        action_adjustment = ACTION_ADJUSTMENT_NEW
    elif add_intensity > Decimal("0"):
        action_adjustment = ACTION_ADJUSTMENT_ADD
    elif add_intensity == Decimal("-1.0"):
        action_adjustment = ACTION_ADJUSTMENT_EXIT
    else:
        action_adjustment = ACTION_ADJUSTMENT_REDUCE

    value = base + bonus_top_10 + bonus_weight_5pct + bonus_streak + action_adjustment
    return PositionSignalWeightResult(
        value=value,
        base=base,
        bonus_top_10=bonus_top_10,
        bonus_weight_5pct=bonus_weight_5pct,
        bonus_streak=bonus_streak,
        action_adjustment=action_adjustment,
    )


def determine_score_confidence(caveats: Iterable[str]) -> str:
    """Plan §7.12 + D3 caveat-propagation rules. Worst-tier wins."""
    caveat_set = set(caveats or ())
    if caveat_set & _LOW_CAVEATS:
        return "low_confidence"
    if caveat_set & _MEDIUM_CAVEATS or CONFIDENTIAL_TREATMENT_CAVEAT in caveat_set:
        return "medium_confidence"
    return "high_confidence"


# ---------------------------------------------------------------------------
# Compute service
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _HolderContribution:
    holding_id: int
    manager_id: int
    manager_canonical_type: str
    manager_type_source: str
    manager_weight: Decimal
    position_signal_weight: PositionSignalWeightResult
    contribution: Decimal
    caveats: list[str]
    # Raw primitive inputs preserved so downstream consumers
    # (MVP4-04 conviction, MVP4-05 caution flags) don't have to
    # re-derive them from the position_signal_weight bonuses.
    holding_streak_quarters: int = 0
    add_intensity: Optional[Decimal] = None


@dataclass(frozen=True)
class _ExcludedHolder:
    """MVP5-02: a holder dropped from the score-side aggregate because
    their filing's ``amendment_status`` flags a pending or failed
    amendment. Their caveats still feed ``aggregate_caveats`` so the
    page-level caution panel sees the AMENDMENTS_PENDING /
    AMENDMENT_FAILED code, but their (manager_weight ×
    position_signal_weight) does NOT contribute to the score."""
    manager_id: int
    manager_canonical_name: str
    exclusion_reason: str
    caveats: list[str]


# MVP5-02 stable exclusion-reason constants. Frontend and admin
# consumers can switch on these.
EXCLUSION_REASON_AMENDMENT_PENDING = "AMENDMENT_PENDING_EXCLUDED"
EXCLUSION_REASON_AMENDMENT_FAILED = "AMENDMENT_FAILED_EXCLUDED"


def compute_signal_weighted_scores(
    session: Session,
    *,
    quarter: str,
    score_version: str = SCORE_VERSION,
    min_holders: int = 3,
    source_job_id: Optional[int] = None,
) -> dict[str, Any]:
    """Compute, upsert, and return aggregate impact for one quarter."""
    eligible_stock_ids = _eligible_stock_ids(
        session, quarter=quarter, min_holders=min_holders,
    )
    if not eligible_stock_ids:
        return {
            "quarter": quarter,
            "score_version": score_version,
            "filings_scored": 0,
            "components_written": 0,
        }

    top_n_by_manager = _top_n_stock_ids_per_manager(
        session, quarter=quarter, top_n=POSITION_TOP_N_THRESHOLD,
    )

    # Cache for the MVP5-01 behavior-derived profile path. Populated
    # lazily inside the per-stock loop so we only pay the cost for
    # managers whose admin ``manager_type`` is ``"unknown"`` AND who
    # actually appear as holders in this scoring batch.
    derived_profile_cache: _DerivedProfileCache = {}

    filings_scored = 0
    components_written = 0
    now = datetime.now(timezone.utc)

    for stock_id in eligible_stock_ids:
        contributions, excluded = _contributions_for_stock(
            session,
            quarter=quarter,
            stock_id=stock_id,
            top_n_by_manager=top_n_by_manager,
            derived_profile_cache=derived_profile_cache,
        )
        if len(contributions) < min_holders:
            # MVP5-02: the floor counts INCLUDED contributions only.
            # If amendment-blocked exclusion drops the included list
            # below the floor, the stock is dropped entirely — a
            # score over 1-2 holders is statistically meaningless.
            continue

        total = sum((c.contribution for c in contributions), Decimal("0"))
        # MVP5-02: aggregate_caveats unions caveats from BOTH included
        # contributions and excluded holders, so page-level codes like
        # AMENDMENTS_PENDING still surface in caution_flag_codes even
        # though the excluded holder's contribution was dropped.
        aggregate_caveats = _aggregate_caveats(contributions, excluded)
        score_confidence = determine_score_confidence(aggregate_caveats)
        score_explanation = _build_score_explanation(
            contributions, aggregate_caveats, score_confidence,
            excluded=excluded,
        )

        # MVP4-04: conviction (plan §7.9) is a passenger on the same
        # compute pass; same row, same upsert, additional component
        # rows. ``ConvictionComponents`` is a pure-function output;
        # no extra DB queries.
        from app.services.oracles_lens.conviction_score import (
            compute_conviction_components,
        )
        conviction = compute_conviction_components(contributions)

        # MVP4-06: distinctive consensus (plan §7.11) — same passenger
        # pattern. Multiplies the signal-weighted total by three
        # in-[0,1] factors, so distinctive ≤ signal_weighted by
        # construction.
        from app.services.oracles_lens.distinctive_consensus import (
            compute_distinctive_consensus,
        )
        distinctive = compute_distinctive_consensus(
            signal_weighted_score=total,
            contributions=contributions,
        )

        quarter_end = _quarter_end_date(quarter)
        signal_id = _upsert_signal(
            session,
            stock_id=stock_id,
            quarter=quarter,
            quarter_end_date=quarter_end,
            score_version=score_version,
            score_value=total,
            raw_consensus_count=len(contributions),
            score_confidence=score_confidence,
            caution_flag_codes=aggregate_caveats,
            score_explanation=score_explanation,
            computed_at=now,
            source_job_id=source_job_id,
            conviction_score=Decimal(conviction.total),
            distinctive_consensus_score=distinctive.distinctive_consensus_score,
        )
        components_written += _replace_components(
            session,
            signal_id=signal_id,
            contributions=contributions,
            conviction=conviction,
            distinctive=distinctive,
        )
        filings_scored += 1

    session.commit()
    return {
        "quarter": quarter,
        "score_version": score_version,
        "filings_scored": filings_scored,
        "components_written": components_written,
    }


# ---------------------------------------------------------------------------
# Behavior-derived profile cache (MVP5-01)
# ---------------------------------------------------------------------------


# Sentinel for "behavior derivation attempted, no usable profile" so the
# cache distinguishes "never tried" from "tried, can't classify."
_DerivedProfileCache = dict[int, Optional[DerivedManagerSignalProfile]]


def _derive_manager_profile(
    session: Session,
    *,
    manager_id: int,
    quarter: str,
    cache: _DerivedProfileCache,
) -> Optional[DerivedManagerSignalProfile]:
    """Lazily compute the behavior-derived signal profile for a manager
    whose admin ``manager_type`` is ``"unknown"``, caching the result
    so the per-stock scoring loop only pays the cost once per manager.

    Pulls the manager's full current-quarter portfolio (eligible HR
    active / linked / direct holdings), computes ``portfolio_weight``
    + ``holding_streak_quarters`` per holding, and derives
    ``turnover_proxy`` from the symmetric difference of current vs
    previous-quarter stock_ids — same shape as the in-memory
    dashboard's ``_manager_turnover_proxy``.

    Returns ``None`` only when the manager has no eligible current-
    quarter holdings (so behavior derivation has no signal at all).
    A return value with ``manager_type=='unknown'`` from
    ``derive_manager_signal_profile`` IS cached and IS returned —
    the resolver upstream will treat it as a fallback_unknown.
    """
    if manager_id in cache:
        return cache[manager_id]

    holdings = (
        session.query(Holding13F)
        .join(ParseRun13F, Holding13F.parse_run_id == ParseRun13F.id)
        .join(
            Filing13F,
            Filing13F.accession_number == ParseRun13F.accession_number,
        )
        .filter(Filing13F.form_type.in_(HR_FORM_TYPES))
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .filter(ParseRun13F.is_current.is_(True))
        .filter(Holding13F.manager_id == manager_id)
        .filter(Holding13F.report_quarter == quarter)
        .filter(Holding13F.cusip_mapping_status == "linked")
        .filter(Holding13F.holding_attribution_status == "direct")
        .all()
    )
    if not holdings:
        cache[manager_id] = None
        return None

    position_weights: list[float] = []
    holding_streak_quarters: list[int] = []
    for holding in holdings:
        weight_result = compute_portfolio_weight(holding)
        if weight_result.value is None:
            continue
        position_weights.append(float(weight_result.value))
        streak_result = compute_holding_streak(
            session,
            manager_id=manager_id,
            stock_id=holding.stock_id,
            current_quarter=quarter,
        )
        holding_streak_quarters.append(streak_result.streak_quarters)

    if not position_weights:
        cache[manager_id] = None
        return None

    current_stock_ids = {h.stock_id for h in holdings}
    previous_quarter = _previous_quarter(quarter)
    previous_stock_rows = (
        session.query(Holding13F.stock_id)
        .join(ParseRun13F, Holding13F.parse_run_id == ParseRun13F.id)
        .join(
            Filing13F,
            Filing13F.accession_number == ParseRun13F.accession_number,
        )
        .filter(Filing13F.form_type.in_(HR_FORM_TYPES))
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .filter(ParseRun13F.is_current.is_(True))
        .filter(Holding13F.manager_id == manager_id)
        .filter(Holding13F.report_quarter == previous_quarter)
        .filter(Holding13F.cusip_mapping_status == "linked")
        .filter(Holding13F.holding_attribution_status == "direct")
        .distinct()
        .all()
    )
    previous_stock_ids = {row[0] for row in previous_stock_rows}

    union = current_stock_ids | previous_stock_ids
    if not union:
        turnover_proxy: Optional[float] = None
    else:
        changed = current_stock_ids.symmetric_difference(previous_stock_ids)
        turnover_proxy = len(changed) / len(union)

    profile = derive_manager_signal_profile(
        position_weights=position_weights,
        holding_streak_quarters=holding_streak_quarters,
        turnover_proxy=turnover_proxy,
    )
    cache[manager_id] = profile
    return profile


# ---------------------------------------------------------------------------
# Compute helpers
# ---------------------------------------------------------------------------


def _eligible_stock_ids(
    session: Session, *, quarter: str, min_holders: int,
) -> list[int]:
    """Stocks with >= ``min_holders`` linked direct holdings in active
    HR/HR-A current parse runs for the quarter."""
    from sqlalchemy import func

    rows = (
        session.query(
            Holding13F.stock_id,
            func.count(func.distinct(Holding13F.manager_id)).label("c"),
        )
        .join(ParseRun13F, Holding13F.parse_run_id == ParseRun13F.id)
        .join(
            Filing13F,
            Filing13F.accession_number == ParseRun13F.accession_number,
        )
        .filter(Filing13F.form_type.in_(HR_FORM_TYPES))
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .filter(ParseRun13F.is_current.is_(True))
        .filter(Holding13F.report_quarter == quarter)
        .filter(Holding13F.stock_id.isnot(None))
        .filter(Holding13F.cusip_mapping_status == "linked")
        .filter(Holding13F.holding_attribution_status == "direct")
        .group_by(Holding13F.stock_id)
        .having(func.count(func.distinct(Holding13F.manager_id)) >= min_holders)
        .all()
    )
    return [row.stock_id for row in rows]


def _top_n_stock_ids_per_manager(
    session: Session, *, quarter: str, top_n: int,
) -> dict[int, set[int]]:
    """Per (manager, quarter), the set of stock_ids with the top-N
    value_thousands. Used for the ``bonus_top_10`` lookup.

    Returns ``{manager_id: {stock_id, ...}}``. The dict is built in
    one pass over the quarter's holdings; expected size is N managers
    × top_n stocks, well within memory bounds for the V1 universe
    (under 100 managers).
    """
    rows = (
        session.query(
            Holding13F.manager_id,
            Holding13F.stock_id,
            Holding13F.value_thousands,
        )
        .join(ParseRun13F, Holding13F.parse_run_id == ParseRun13F.id)
        .join(
            Filing13F,
            Filing13F.accession_number == ParseRun13F.accession_number,
        )
        .filter(Filing13F.form_type.in_(HR_FORM_TYPES))
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .filter(ParseRun13F.is_current.is_(True))
        .filter(Holding13F.report_quarter == quarter)
        .filter(Holding13F.stock_id.isnot(None))
        .filter(Holding13F.cusip_mapping_status == "linked")
        .filter(Holding13F.value_thousands.isnot(None))
        .all()
    )
    grouped: dict[int, list[tuple[int, int]]] = {}
    for row in rows:
        grouped.setdefault(row.manager_id, []).append(
            (int(row.value_thousands or 0), row.stock_id)
        )
    top_by_manager: dict[int, set[int]] = {}
    for manager_id, items in grouped.items():
        items.sort(reverse=True)
        top_by_manager[manager_id] = {sid for _, sid in items[:top_n]}
    return top_by_manager


def _contributions_for_stock(
    session: Session,
    *,
    quarter: str,
    stock_id: int,
    top_n_by_manager: dict[int, set[int]],
    derived_profile_cache: _DerivedProfileCache,
) -> tuple[list[_HolderContribution], list[_ExcludedHolder]]:
    """For one (stock, quarter), iterate active linked direct holders
    and produce a contribution per holder."""
    holdings = (
        session.query(Holding13F, InstitutionManager, Filing13F)
        .join(ParseRun13F, Holding13F.parse_run_id == ParseRun13F.id)
        .join(Filing13F, Filing13F.accession_number == ParseRun13F.accession_number)
        .join(InstitutionManager, InstitutionManager.id == Holding13F.manager_id)
        .filter(Filing13F.form_type.in_(HR_FORM_TYPES))
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .filter(ParseRun13F.is_current.is_(True))
        .filter(Holding13F.report_quarter == quarter)
        .filter(Holding13F.stock_id == stock_id)
        .filter(Holding13F.cusip_mapping_status == "linked")
        .filter(Holding13F.holding_attribution_status == "direct")
        .all()
    )

    contributions: list[_HolderContribution] = []
    excluded: list[_ExcludedHolder] = []
    for holding, manager, filing in holdings:
        # Per-holder caveats from MVP4-02 primitives + filing flags.
        per_holder_caveats: list[str] = []

        portfolio_weight_result = compute_portfolio_weight(holding)
        per_holder_caveats.extend(portfolio_weight_result.caveats)
        portfolio_weight = portfolio_weight_result.value

        streak_result = compute_holding_streak(
            session,
            manager_id=manager.id,
            stock_id=stock_id,
            current_quarter=quarter,
        )
        per_holder_caveats.extend(streak_result.caveats)

        add_intensity_result = compute_add_intensity(
            session,
            manager_id=manager.id,
            stock_id=stock_id,
            current_quarter=quarter,
        )
        per_holder_caveats.extend(add_intensity_result.caveats)

        if filing.has_confidential_treatment:
            per_holder_caveats.append(CONFIDENTIAL_TREATMENT_CAVEAT)

        # MVP4-05: surface filing-level amendment caveats on every
        # contribution from that filing so the user-facing caution
        # panel sees "this holder's filing has a pending amendment"
        # without re-querying.
        from app.services.oracles_lens.caution_flags import (
            CAVEAT_AMENDMENT_FAILED as _AMENDMENT_FAILED,
            CAVEAT_AMENDMENTS_PENDING as _AMENDMENTS_PENDING,
        )
        if filing.amendment_status == "amendments_pending":
            per_holder_caveats.append(_AMENDMENTS_PENDING)
        elif filing.amendment_status == "amendment_failed":
            per_holder_caveats.append(_AMENDMENT_FAILED)

        # MVP5-02: amendment-pending / amendment-failed holders are
        # excluded from the score-side aggregate. Their caveats still
        # flow into ``per_holder_caveats`` → ``aggregate_caveats`` via
        # the ``_ExcludedHolder`` record so the page-level caution
        # panel keeps the AMENDMENTS_PENDING / AMENDMENT_FAILED signal.
        if filing.amendment_status == "amendments_pending":
            excluded.append(
                _ExcludedHolder(
                    manager_id=manager.id,
                    manager_canonical_name=manager.canonical_name,
                    exclusion_reason=EXCLUSION_REASON_AMENDMENT_PENDING,
                    caveats=per_holder_caveats,
                )
            )
            continue
        if filing.amendment_status == "amendment_failed":
            excluded.append(
                _ExcludedHolder(
                    manager_id=manager.id,
                    manager_canonical_name=manager.canonical_name,
                    exclusion_reason=EXCLUSION_REASON_AMENDMENT_FAILED,
                    caveats=per_holder_caveats,
                )
            )
            continue

        is_top_10 = stock_id in top_n_by_manager.get(manager.id, set())

        position_signal_weight = compute_position_signal_weight(
            portfolio_weight=portfolio_weight,
            holding_streak_quarters=streak_result.streak_quarters,
            is_top_10=is_top_10,
            add_intensity=add_intensity_result.value,
            caveats=per_holder_caveats,
        )

        # MVP5-01: when admin manager_type is "unknown", lazily compute
        # the behavior-derived profile so the MVP4-11 three-tier
        # precedence (admin → behavior → fallback_unknown) is real in
        # production scoring. The cache is keyed on manager_id and
        # populated on first hit; subsequent stocks held by the same
        # manager reuse the cached profile.
        if (manager.manager_type or "unknown") == "unknown":
            derived_profile = _derive_manager_profile(
                session,
                manager_id=manager.id,
                quarter=quarter,
                cache=derived_profile_cache,
            )
        else:
            derived_profile = None
        type_resolution = resolve_manager_type(
            manager, derived_profile=derived_profile,
        )

        contribution = type_resolution.weight * position_signal_weight.value
        contributions.append(
            _HolderContribution(
                holding_id=holding.id,
                manager_id=manager.id,
                manager_canonical_type=type_resolution.canonical_type,
                manager_type_source=type_resolution.source,
                manager_weight=type_resolution.weight,
                position_signal_weight=position_signal_weight,
                contribution=contribution,
                caveats=per_holder_caveats,
                holding_streak_quarters=streak_result.streak_quarters,
                add_intensity=add_intensity_result.value,
            )
        )

    return contributions, excluded


def _aggregate_caveats(
    contributions: list[_HolderContribution],
    excluded: list[_ExcludedHolder] | None = None,
) -> list[str]:
    """Union of per-holder caveats, deduped while preserving first-seen
    order so the response shape is deterministic.

    MVP5-02: also unions caveats from excluded holders so AMENDMENTS_PENDING
    / AMENDMENT_FAILED (and any other per-holder caveats on the excluded
    filing) still surface at the page level even though the holder's
    contribution was dropped from the score.
    """
    seen: list[str] = []
    for c in contributions:
        for code in c.caveats:
            if code not in seen:
                seen.append(code)
    for e in excluded or []:
        for code in e.caveats:
            if code not in seen:
                seen.append(code)
    return seen


def _build_score_explanation(
    contributions: list[_HolderContribution],
    aggregate_caveats: list[str],
    score_confidence: str,
    *,
    excluded: list[_ExcludedHolder] | None = None,
) -> dict[str, Any]:
    """Composite summary surfaced in the main ranking table per plan
    §8.3. Detail per-component breakdown lives in
    `oracles_lens_score_components`.
    """
    high_signal_count = sum(
        1 for c in contributions if c.manager_weight >= Decimal("0.80")
    )
    top_10_count = sum(
        1 for c in contributions if c.position_signal_weight.bonus_top_10 > Decimal("0")
    )
    streak_count = sum(
        1 for c in contributions if c.position_signal_weight.bonus_streak > Decimal("0")
    )

    primary_reasons: list[str] = []
    if high_signal_count:
        primary_reasons.append(
            f"{high_signal_count} high-signal manager{'s' if high_signal_count > 1 else ''} hold this stock"
        )
    if top_10_count:
        primary_reasons.append(
            f"{top_10_count} holder{'s' if top_10_count > 1 else ''} rank it as a top-10 position"
        )
    if streak_count:
        primary_reasons.append(
            f"{streak_count} holder{'s' if streak_count > 1 else ''} hold it for >= 4 quarters"
        )

    # D3 / P2 #4: confidence demotion reasons traceable from the codes.
    # Surface *every* active caveat that contributed to a demotion, not
    # just the tier-winning ones. If a stock has both a low caveat (e.g.
    # ``stale_until_recompute``) and a medium caveat (e.g.
    # ``AMENDMENTS_PENDING``), an investor seeing ``low_confidence`` in
    # the UI should still see the medium caveat in the drilldown — its
    # snapshot integrity issue is independent of the staleness reason.
    # ``demoted_to`` records the per-caveat tier, not the aggregate tier.
    confidence_demotion_reasons: list[dict[str, str]] = []
    if score_confidence in ("low_confidence", "medium_confidence"):
        for code in aggregate_caveats:
            if code in _LOW_CAVEATS:
                confidence_demotion_reasons.append(
                    {"code": code, "demoted_to": "low_confidence"}
                )
            elif code in _MEDIUM_CAVEATS or code == CONFIDENTIAL_TREATMENT_CAVEAT:
                confidence_demotion_reasons.append(
                    {"code": code, "demoted_to": "medium_confidence"}
                )

    # MVP5-01: per-tier counts of how each holder's manager_type was
    # resolved (admin / behavior / fallback_unknown). Slim summary at
    # the score_explanation level; per-holder detail lives in
    # ``oracles_lens_score_components`` (evidence_json on the
    # ``manager_signal_weight`` rows). Lets the dashboard render a
    # one-line "5 admin / 2 behavior / 1 fallback" attribution without
    # joining to the components table.
    manager_type_source_counts: dict[str, int] = {
        "admin": 0,
        "behavior": 0,
        "fallback_unknown": 0,
    }
    for c in contributions:
        manager_type_source_counts[c.manager_type_source] = (
            manager_type_source_counts.get(c.manager_type_source, 0) + 1
        )

    # MVP5-02: surface amendment-blocked holders so the drilldown can
    # render "1 holder excluded — amendment pending" without joining
    # to another table. Empty list/zero when nothing is excluded so
    # downstream consumers can rely on the field shape.
    excluded_payload = [
        {
            "manager_id": e.manager_id,
            "manager_canonical_name": e.manager_canonical_name,
            "exclusion_reason": e.exclusion_reason,
        }
        for e in (excluded or [])
    ]

    return {
        "primary_reasons": primary_reasons,
        "confidence_demotion_reasons": confidence_demotion_reasons,
        "manager_type_source_counts": manager_type_source_counts,
        "excluded_holder_count": len(excluded_payload),
        "excluded_holders": excluded_payload,
    }


def _quarter_end_date(quarter: str) -> Any:
    from datetime import date

    year_str, qtr_str = quarter.split("-Q", 1)
    period_end_month = int(qtr_str) * 3
    last_day = 31 if period_end_month in (1, 3, 5, 7, 8, 10, 12) else 30
    return date(int(year_str), period_end_month, last_day)


def _upsert_signal(
    session: Session,
    *,
    stock_id: int,
    quarter: str,
    quarter_end_date,
    score_version: str,
    score_value: Decimal,
    raw_consensus_count: int,
    score_confidence: str,
    caution_flag_codes: list[str],
    score_explanation: dict[str, Any],
    computed_at: datetime,
    source_job_id: Optional[int],
    conviction_score: Optional[Decimal] = None,
    distinctive_consensus_score: Optional[Decimal] = None,
) -> int:
    """ORM upsert via ``INSERT ... ON CONFLICT DO UPDATE`` per MVP4-01 D4."""
    stmt = pg_insert(OraclesLensSignal).values(
        stock_id=stock_id,
        report_quarter=quarter,
        quarter_end_date=quarter_end_date,
        score_version=score_version,
        raw_consensus_count=raw_consensus_count,
        signal_weighted_consensus_score=score_value,
        conviction_score=conviction_score,
        distinctive_consensus_score=distinctive_consensus_score,
        score_confidence=score_confidence,
        caution_flag_codes=caution_flag_codes,
        score_explanation=score_explanation,
        computed_at=computed_at,
        source_job_id=source_job_id,
    )
    update_set = {
        "raw_consensus_count": stmt.excluded.raw_consensus_count,
        "signal_weighted_consensus_score": stmt.excluded.signal_weighted_consensus_score,
        "conviction_score": stmt.excluded.conviction_score,
        "distinctive_consensus_score": stmt.excluded.distinctive_consensus_score,
        "score_confidence": stmt.excluded.score_confidence,
        "caution_flag_codes": stmt.excluded.caution_flag_codes,
        "score_explanation": stmt.excluded.score_explanation,
        "computed_at": stmt.excluded.computed_at,
        "source_job_id": stmt.excluded.source_job_id,
        "quarter_end_date": stmt.excluded.quarter_end_date,
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["stock_id", "report_quarter", "score_version"],
        set_=update_set,
    ).returning(OraclesLensSignal.id)
    result = session.execute(stmt)
    signal_id = result.scalar_one()
    session.flush()
    return signal_id


def _replace_components(
    session: Session,
    *,
    signal_id: int,
    contributions: list[_HolderContribution],
    conviction=None,
    distinctive=None,
) -> int:
    """Replace component rows for a score: delete existing then bulk
    insert. Component breakdown is per-holder for the
    signal-weighted inputs; conviction (MVP4-04) writes one row per
    component-name with the stock-level aggregate.
    """
    session.query(OraclesLensScoreComponent).filter(
        OraclesLensScoreComponent.score_id == signal_id
    ).delete(synchronize_session=False)
    session.flush()

    written = 0
    for c in contributions:
        manager_evidence = {
            "manager_type": c.manager_canonical_type,
            "source": c.manager_type_source,
        }
        position_evidence = {
            "base": str(c.position_signal_weight.base),
            "bonus_top_10": str(c.position_signal_weight.bonus_top_10),
            "bonus_weight_5pct": str(c.position_signal_weight.bonus_weight_5pct),
            "bonus_streak": str(c.position_signal_weight.bonus_streak),
            "action_adjustment": str(c.position_signal_weight.action_adjustment),
            "caveats": c.caveats,
        }
        session.add_all([
            OraclesLensScoreComponent(
                score_id=signal_id,
                component_name="manager_signal_weight",
                manager_id=c.manager_id,
                numeric_value=c.manager_weight,
                string_value=c.manager_canonical_type,
                evidence_json=manager_evidence,
            ),
            OraclesLensScoreComponent(
                score_id=signal_id,
                component_name="position_signal_weight",
                manager_id=c.manager_id,
                numeric_value=c.position_signal_weight.value,
                string_value=None,
                evidence_json=position_evidence,
            ),
        ])
        written += 2

    # MVP4-04: conviction component breakdown is stock-level (not
    # per-holder), so manager_id=None on each row. The capped
    # 0-100 conviction_total is also written for easy drilldown
    # read and matches the parent OraclesLensSignal.conviction_score
    # value.
    if conviction is not None:
        conviction_rows = [
            ("conviction_position_importance", conviction.position_importance),
            ("conviction_holding_persistence", conviction.holding_persistence),
            ("conviction_manager_quality", conviction.manager_quality),
            ("conviction_recent_action", conviction.recent_action),
            ("conviction_agreement", conviction.agreement),
            ("conviction_total", conviction.total),
        ]
        for component_name, value in conviction_rows:
            session.add(
                OraclesLensScoreComponent(
                    score_id=signal_id,
                    component_name=component_name,
                    manager_id=None,
                    numeric_value=Decimal(value),
                    string_value=None,
                    evidence_json={"holder_count": len(contributions)},
                )
            )
            written += 1

    # MVP4-06: distinctive consensus components — stock-level (no
    # per-manager breakdown). evidence_json carries the input that
    # drove each factor so the drilldown can render
    # "signal-weighted 3.12 × 0.82 concentration × 0.75 persistence
    # × 0.92 quality = 1.77 distinctive".
    if distinctive is not None:
        aggregate_weight = sum(
            (c.position_signal_weight.base for c in contributions), Decimal("0"),
        )
        avg_manager_weight = (
            sum((c.manager_weight for c in contributions), Decimal("0"))
            / Decimal(len(contributions))
            if contributions else Decimal("0")
        )
        streaks = [max(c.holding_streak_quarters, 0) for c in contributions]
        median_streak = (
            sorted(streaks)[len(streaks) // 2] if streaks else 0
        )
        distinctive_rows = [
            (
                "distinctive_concentration_factor",
                distinctive.concentration_factor,
                {"aggregate_weight": str(aggregate_weight)},
            ),
            (
                "distinctive_persistence_factor",
                distinctive.persistence_factor,
                {"median_streak_quarters": median_streak},
            ),
            (
                # MVP5-06: renamed from ``distinctive_anti_crowding_factor``
                # per SME #6 #3. Existing rows in production carrying the
                # legacy string are rewritten on the next recompute
                # because ``_replace_components`` deletes and re-inserts
                # all component rows for the signal; no migration needed.
                "distinctive_quality_agreement_factor",
                distinctive.quality_agreement_factor,
                {"avg_manager_signal_weight": str(avg_manager_weight)},
            ),
            (
                "distinctive_total",
                distinctive.distinctive_consensus_score,
                {
                    "concentration_factor": str(distinctive.concentration_factor),
                    "persistence_factor": str(distinctive.persistence_factor),
                    "quality_agreement_factor": str(distinctive.quality_agreement_factor),
                },
            ),
        ]
        for component_name, value, evidence in distinctive_rows:
            session.add(
                OraclesLensScoreComponent(
                    score_id=signal_id,
                    component_name=component_name,
                    manager_id=None,
                    numeric_value=value,
                    string_value=None,
                    evidence_json=evidence,
                )
            )
            written += 1

    session.flush()
    return written


# ---------------------------------------------------------------------------
# JobRun orchestration
# ---------------------------------------------------------------------------


def _active_job_for_lock_key(session: Session, lock_key: str) -> Optional[JobRun]:
    return (
        session.query(JobRun)
        .filter(JobRun.lock_key == lock_key)
        .filter(JobRun.status.in_(_ACTIVE_JOB_STATUSES))
        .order_by(JobRun.created_at.desc(), JobRun.id.desc())
        .first()
    )


def _lock_key(quarter: str, score_version: str) -> str:
    return f"oracles_lens_score:{quarter}:{score_version}"


def enqueue_signal_weighted_backfill(
    session: Session,
    *,
    quarter: str,
    score_version: str = SCORE_VERSION,
    min_holders: int = 3,
    requested_by_user_id: Optional[int] = None,
    trigger_source: str = "admin",
) -> JobRun:
    """Create a `JobRun` for a signal-weighted score backfill.

    Duplicate-active enqueue (`queued` / `running` /
    `cancel_requested`) raises ``SignalWeightedBackfillError``. The
    partial unique index ``uq_job_runs_active_lock_key`` still
    catches the TOCTOU race; the ``IntegrityError`` is translated to
    the same typed error so callers see one predictable failure
    mode (matches MVP3-05 / MVP3-07).
    """
    lock_key = _lock_key(quarter, score_version)

    active = _active_job_for_lock_key(session, lock_key)
    if active is not None:
        raise SignalWeightedBackfillError(
            f"Signal-weighted backfill already active for {quarter} "
            f"version {score_version} (job_id={active.id}, status={active.status})."
        )

    job = JobRun(
        job_type=JOB_TYPE,
        status="queued",
        trigger_source=trigger_source,
        requested_by_user_id=requested_by_user_id,
        lock_key=lock_key,
        dedupe_key=lock_key,
        quarter=quarter,
        input_json={
            "quarter": quarter,
            "score_version": score_version,
            "min_holders": min_holders,
        },
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SignalWeightedBackfillError(
            f"Signal-weighted backfill already active for {quarter} "
            f"version {score_version} (rejected by lock_key uniqueness)."
        ) from exc
    session.refresh(job)
    return job


def execute_signal_weighted_backfill(
    session: Session, *, job_run_id: int,
) -> dict[str, Any]:
    """Run the compute service against a queued JobRun and finalize."""
    job = session.get(JobRun, job_run_id)
    if job is None:
        raise SignalWeightedBackfillError(f"job_run not found: {job_run_id}")

    payload = job.input_json or {}
    quarter = payload.get("quarter")
    score_version = payload.get("score_version", SCORE_VERSION)
    min_holders = int(payload.get("min_holders", 3))
    if not quarter:
        raise SignalWeightedBackfillError(
            f"job_run {job_run_id} input_json missing 'quarter'"
        )

    try:
        impact = compute_signal_weighted_scores(
            session,
            quarter=quarter,
            score_version=score_version,
            min_holders=min_holders,
            source_job_id=job.id,
        )
    except Exception as exc:
        logger.warning("signal_weighted_backfill failed for %s: %s", quarter, exc)
        job = session.get(JobRun, job_run_id)
        job.status = "failed"
        job.error_message = str(exc)
        session.add(job)
        session.commit()
        return {
            "job_run_id": job.id,
            "status": "failed",
            "error_message": str(exc),
        }

    job = session.get(JobRun, job_run_id)
    job.status = "succeeded"
    job.summary_json = {
        "scope": {"quarter": quarter, "score_version": score_version},
        "impact_summary": impact,
    }
    session.add(job)
    session.commit()
    return {
        "job_run_id": job.id,
        "status": "succeeded",
        "impact_summary": impact,
    }


# ---------------------------------------------------------------------------
# Read helper for the HTTP endpoint (plan §9.1)
# ---------------------------------------------------------------------------


def build_oracles_lens_response(
    session: Session,
    *,
    period: str,
    min_holders: int = 3,
    limit: int = 50,
    score_version: str = SCORE_VERSION,
) -> dict[str, Any]:
    """Build the user-facing ranking-table payload."""
    rows = (
        session.query(OraclesLensSignal, Stock)
        .join(Stock, Stock.id == OraclesLensSignal.stock_id)
        .filter(OraclesLensSignal.report_quarter == period)
        .filter(OraclesLensSignal.score_version == score_version)
        .filter(OraclesLensSignal.raw_consensus_count >= min_holders)
        .order_by(
            OraclesLensSignal.signal_weighted_consensus_score.desc().nullslast(),
            OraclesLensSignal.id.asc(),
        )
        .limit(limit)
        .all()
    )

    from app.services.oracles_lens.caution_flags import enrich_caveat_codes

    items: list[dict[str, Any]] = []
    for signal, stock in rows:
        raw_codes = signal.caution_flag_codes or []
        items.append({
            "stock_id": stock.id,
            "ticker": stock.ticker,
            "company_name": stock.company_name,
            "consensus_count": signal.raw_consensus_count,
            "signal_weighted_consensus_score": (
                str(signal.signal_weighted_consensus_score)
                if signal.signal_weighted_consensus_score is not None
                else None
            ),
            "score_confidence": signal.score_confidence,
            "caution_flag_codes": raw_codes,
            # MVP4-05: structured surface for the user-facing caution
            # panel. Same source as caution_flag_codes but enriched
            # with severity / scope / label per the registry, with the
            # score-emitted ↔ readiness-vocabulary alias deduped.
            "caution_flags": enrich_caveat_codes(list(raw_codes)),
            "score_explanation": signal.score_explanation or {},
            "conviction_score": (
                int(signal.conviction_score)
                if signal.conviction_score is not None
                else None
            ),
            "distinctive_consensus_score": (
                str(signal.distinctive_consensus_score)
                if signal.distinctive_consensus_score is not None
                else None
            ),
            # Reserved fields for MVP4-06; null until that service
            # lands so the frontend in MVP4-07 receives a stable shape.
            "add_intensity": None,
            "median_holding_streak_quarters": None,
        })

    return {
        "period": period,
        "score_version": score_version,
        "items": items,
    }
