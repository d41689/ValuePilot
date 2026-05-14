from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.models.institutions import Filing13F, Holding13F, InstitutionManager
from app.models.oracles_lens import OraclesLensSignal
from app.models.stocks import Stock, StockPrice
from app.services.oracles_lens.constants import SCORE_VERSION
from app.services.oracles_lens.manager_signal import derive_manager_signal_profile


BASELINE_NOTICE = (
    "13F filings are delayed snapshots. They show reported quarter-end holdings, "
    "not current holdings, transaction prices, or buy recommendations."
)

QUALITY_METRIC_KEYS = {
    "piotroski_total": "score.piotroski.total",
    "return_on_total_capital": "bs.return_on_total_capital",
    "return_on_equity": "bs.return_on_equity",
    "net_profit_margin": "is.net_profit_margin",
    "debt_to_capital": "leverage.long_term_debt_to_capital",
    "owners_earnings": "owners_earnings_per_share_normalized",
}
MANUAL_VALUATION_REFERENCE_KEY = "val.fair_value"
VALUE_LINE_VALUATION_REFERENCE_KEY = "target.price_18m.mid"
VALUATION_REFERENCE_KEYS = {
    MANUAL_VALUATION_REFERENCE_KEY,
    VALUE_LINE_VALUATION_REFERENCE_KEY,
}


@dataclass(frozen=True)
class PeriodInfo:
    label: str
    period_end_date: date
    manager_count: int


@dataclass
class ManagerHolding:
    manager_id: int
    manager_name: str
    stock_id: int
    ticker: str
    company_name: str
    shares: int
    value_thousands: int
    filing_total_value_thousands: int | None
    position_weight: float
    filing_date: date | None = None
    accession_no: str | None = None
    position_rank: int = 0
    action: str = "flat"
    previous_shares: int | None = None
    share_delta_pct: float | None = None
    holding_streak_quarters: int = 1
    manager_type: str = "unknown"
    # MVP8-03B B1: preserve the InstitutionManager.manager_type as the
    # admin-classified value before _apply_manager_signal_profiles
    # overwrites ``manager_type`` with the behavior-derived profile. The
    # drawer renders both so reviewers can spot admin-vs-derived
    # divergence in context.
    manager_type_admin_classified: str = "unknown"
    manager_signal_weight: float = 0.6
    portfolio_concentration: float | None = None
    portfolio_holding_count: int | None = None
    average_holding_period_quarters: float | None = None
    manager_profile_source: str = "unknown"
    turnover_proxy: float | None = None
    high_turnover: bool = False


def build_oracles_lens_dashboard(
    session: Session,
    *,
    period: str | None = None,
    lookback_quarters: int = 4,
    min_holders: int = 3,
    superinvestor_only: bool = True,
    min_signal_score: float | None = None,
    limit: int = 50,
    sort: str = "signal_weighted_consensus",
    use_persisted_scores: bool = False,
) -> dict[str, Any]:
    """Build the Oracle's Lens dashboard payload.

    MVP4-03b: when ``use_persisted_scores=True``, the per-stock
    score fields come from ``oracles_lens_signals`` (MVP4-03's
    plan-§7.2 implementation) and stocks without a persisted row
    for the (period, ``SCORE_VERSION``) are excluded. When
    ``use_persisted_scores=False`` (default), the existing
    in-memory formula in ``_stock_payload`` is used unchanged.
    """
    periods = _periods(session, superinvestor_only=superinvestor_only)
    latest_complete = _latest_complete_period(periods, min_manager_coverage=min_holders)

    if period:
        selected_end = _period_label_to_end_date(period)
        selected = next((item for item in periods if item.period_end_date == selected_end), None)
        if selected is None:
            selected = PeriodInfo(_period_label(selected_end), selected_end, 0)
    elif latest_complete:
        selected = latest_complete
    elif periods:
        selected = periods[0]
    else:
        selected = None

    if selected is None:
        return {
            "period": None,
            "period_end_date": None,
            "latest_complete_period": None,
            "baseline_notice": BASELINE_NOTICE,
            "coverage": _empty_coverage(),
            "periods": [],
            "items": [],
        }

    previous_period = _previous_period(periods, selected.period_end_date)
    current_holdings = _holdings_for_period(
        session,
        selected.period_end_date,
        superinvestor_only=superinvestor_only,
    )
    previous_holdings = (
        _holdings_for_period(session, previous_period.period_end_date, superinvestor_only=superinvestor_only)
        if previous_period
        else {}
    )

    _rank_manager_positions(current_holdings)
    turnover_by_manager = _manager_turnover_proxy(current_holdings, previous_holdings)
    streaks = _holding_streaks(
        session,
        selected.period_end_date,
        superinvestor_only=superinvestor_only,
    )

    for key, holding in current_holdings.items():
        previous = previous_holdings.get(key)
        _apply_action(holding, previous)
        holding.turnover_proxy = turnover_by_manager.get(holding.manager_id)
        holding.high_turnover = bool(holding.turnover_proxy is not None and holding.turnover_proxy >= 0.6)
        holding.holding_streak_quarters = streaks.get(key, 1)

    _apply_manager_signal_profiles(current_holdings)

    rows_by_stock: dict[int, list[ManagerHolding]] = defaultdict(list)
    for holding in current_holdings.values():
        rows_by_stock[holding.stock_id].append(holding)

    items = [
        _stock_payload(
            stock_holdings,
            selected_period=selected,
            latest_complete_period=latest_complete,
            min_holders=min_holders,
        )
        for stock_holdings in rows_by_stock.values()
        if len(stock_holdings) >= min_holders
    ]
    if use_persisted_scores:
        items, persisted_score_count = _apply_persisted_scores(
            session, items, period_label=selected.label,
        )
    else:
        persisted_score_count = 0
    if min_signal_score is not None:
        items = [item for item in items if item["signal_weighted_consensus_score"] >= min_signal_score]

    items.sort(key=_sort_key(sort), reverse=True)
    if limit > 0:
        items = items[:limit]

    historical_price_context = bool(
        latest_complete and selected.period_end_date < latest_complete.period_end_date
    )
    price_as_of_date = selected.period_end_date if historical_price_context else None
    price_context = "historical_snapshot" if historical_price_context else "latest"
    quality_by_stock = _quality_overlay_by_stock(
        session,
        [item["stock_id"] for item in items],
        price_as_of_date=price_as_of_date,
        price_context=price_context,
    )
    valuation_by_stock = _valuation_reference_by_stock(
        session,
        {
            item["stock_id"]: (
                item.get("holder_price_estimate_low"),
                item.get("holder_price_estimate_high"),
            )
            for item in items
        },
        price_as_of_date=price_as_of_date,
        price_context=price_context,
    )
    for item in items:
        item["quality_overlay"] = quality_by_stock.get(item["stock_id"], _empty_quality_overlay())
        item.update(valuation_by_stock.get(item["stock_id"], _empty_valuation_reference()))

    coverage = _coverage(
        session,
        selected.period_end_date,
        superinvestor_only=superinvestor_only,
        quality_by_stock=quality_by_stock,
        valuation_by_stock=valuation_by_stock,
        price_context=price_context,
        price_target_date=price_as_of_date,
    )
    # MVP4-03b: surface how many items came from persisted scoring so
    # observability stays honest when the persisted path is exercised.
    coverage["persisted_score_count"] = persisted_score_count
    return {
        "period": selected.label,
        "period_end_date": selected.period_end_date.isoformat(),
        "latest_complete_period": latest_complete.label if latest_complete else None,
        "baseline_notice": BASELINE_NOTICE,
        "coverage": coverage,
        "periods": _period_timeline(periods, selected, latest_complete),
        "items": items,
    }


def _apply_persisted_scores(
    session: Session,
    items: list[dict[str, Any]],
    *,
    period_label: str,
    score_version: str = SCORE_VERSION,
) -> tuple[list[dict[str, Any]], int]:
    """Override per-item score fields with persisted oracles_lens_signals.

    Stocks without a persisted row for (period_label, score_version)
    are dropped from the returned list — no in-memory fallback to
    avoid mixing the dashboard's legacy formula with MVP4-03's
    plan-§7.2 implementation inside a single response. The two
    formulas disagree; users should see one or the other, not both
    side-by-side.
    """
    if not items:
        return [], 0
    stock_ids = [item["stock_id"] for item in items]
    rows = (
        session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.report_quarter == period_label)
        .filter(OraclesLensSignal.score_version == score_version)
        .filter(OraclesLensSignal.stock_id.in_(stock_ids))
        .all()
    )
    persisted_by_stock = {row.stock_id: row for row in rows}

    # Import here so the dashboard module doesn't take a hard
    # dependency on the caution_flags surface when persisted mode
    # is disabled.
    from app.services.oracles_lens.caution_flags import enrich_caveat_codes

    out: list[dict[str, Any]] = []
    for item in items:
        row = persisted_by_stock.get(item["stock_id"])
        if row is None:
            # No persisted score for this stock under the requested
            # score_version → exclude from the response.
            continue
        item["signal_weighted_consensus_score"] = (
            float(row.signal_weighted_consensus_score)
            if row.signal_weighted_consensus_score is not None
            else None
        )
        item["score_confidence"] = row.score_confidence
        raw_codes = list(row.caution_flag_codes or [])
        item["caution_flag_codes"] = raw_codes
        # MVP4-05: also surface the structured caution_flags so a
        # persisted-mode response is shape-compatible with the
        # signal-weighted read helper. Existing in-memory
        # caution_flags (if any) are replaced with the persisted
        # enrichment because the persisted source is canonical in
        # persisted mode.
        item["caution_flags"] = enrich_caveat_codes(raw_codes)
        # Merge persisted explanation keys (e.g.
        # confidence_demotion_reasons) into the existing one so the
        # dashboard's narrative survives the override.
        existing_explanation = dict(item.get("score_explanation") or {})
        existing_explanation.update(row.score_explanation or {})
        item["score_explanation"] = existing_explanation
        item["score_source"] = "persisted"
        out.append(item)
    return out, len(out)


def _period_timeline(
    periods: list[PeriodInfo],
    selected: PeriodInfo,
    latest_complete: PeriodInfo | None,
) -> list[dict[str, Any]]:
    return [
        {
            "label": item.label,
            "period_end_date": item.period_end_date.isoformat(),
            "manager_count": item.manager_count,
            "is_selected": item.period_end_date == selected.period_end_date,
            "is_latest_complete": bool(
                latest_complete and item.period_end_date == latest_complete.period_end_date
            ),
        }
        for item in periods
    ]


def _periods(session: Session, *, superinvestor_only: bool) -> list[PeriodInfo]:
    query = (
        session.query(
            Filing13F.period_of_report,
            func.count(func.distinct(Filing13F.manager_id)),
        )
        .join(InstitutionManager, InstitutionManager.id == Filing13F.manager_id)
        .filter(Filing13F.is_latest_for_period.is_(True))
        .filter(InstitutionManager.match_status == "confirmed")
        .filter(InstitutionManager.cik.isnot(None))
    )
    if superinvestor_only:
        query = query.filter(InstitutionManager.is_superinvestor.is_(True))
    rows = query.group_by(Filing13F.period_of_report).order_by(Filing13F.period_of_report.desc()).all()
    return [
        PeriodInfo(
            label=_period_label(period_end),
            period_end_date=period_end,
            manager_count=int(manager_count or 0),
        )
        for period_end, manager_count in rows
    ]


def _latest_complete_period(periods: list[PeriodInfo], *, min_manager_coverage: int) -> PeriodInfo | None:
    if not periods:
        return None
    max_manager_count = max(item.manager_count for item in periods)
    threshold = max(min_manager_coverage, math.ceil(max_manager_count * 0.8))
    for item in periods:
        if item.manager_count >= threshold:
            return item
    return periods[0]


def _previous_period(periods: list[PeriodInfo], selected_end: date) -> PeriodInfo | None:
    older = [item for item in periods if item.period_end_date < selected_end]
    return older[0] if older else None


def _holdings_for_period(
    session: Session,
    period_end: date,
    *,
    superinvestor_only: bool,
) -> dict[tuple[int, int], ManagerHolding]:
    query = (
        session.query(Holding13F, Filing13F, InstitutionManager, Stock)
        .join(Filing13F, Filing13F.id == Holding13F.filing_id)
        .join(InstitutionManager, InstitutionManager.id == Filing13F.manager_id)
        .join(Stock, Stock.id == Holding13F.stock_id)
        .filter(Filing13F.period_of_report == period_end)
        .filter(Filing13F.is_latest_for_period.is_(True))
        .filter(InstitutionManager.match_status == "confirmed")
        .filter(InstitutionManager.cik.isnot(None))
        .filter(Holding13F.stock_id.isnot(None))
        .filter(Holding13F.shares.isnot(None))
        .filter(Holding13F.put_call.is_(None))
    )
    if superinvestor_only:
        query = query.filter(InstitutionManager.is_superinvestor.is_(True))

    grouped: dict[tuple[int, int], ManagerHolding] = {}
    for holding, filing, manager, stock in query.all():
        key = (manager.id, stock.id)
        total_value = filing.computed_total_value_thousands or filing.reported_total_value_thousands
        if key not in grouped:
            grouped[key] = ManagerHolding(
                manager_id=manager.id,
                manager_name=manager.display_name or manager.legal_name,
                stock_id=stock.id,
                ticker=stock.ticker,
                company_name=stock.company_name,
                shares=0,
                value_thousands=0,
                filing_total_value_thousands=total_value,
                position_weight=0,
                filing_date=filing.filed_at,
                accession_no=filing.accession_no,
                manager_type_admin_classified=manager.manager_type or "unknown",
            )
        grouped[key].shares += int(holding.shares or 0)
        grouped[key].value_thousands += int(holding.value_thousands or 0)

    for manager_holding in grouped.values():
        total_value = manager_holding.filing_total_value_thousands or 0
        manager_holding.position_weight = (
            manager_holding.value_thousands / total_value if total_value > 0 else 0
        )
    return grouped


def _rank_manager_positions(holdings: dict[tuple[int, int], ManagerHolding]) -> None:
    by_manager: dict[int, list[ManagerHolding]] = defaultdict(list)
    for holding in holdings.values():
        by_manager[holding.manager_id].append(holding)
    for manager_holdings in by_manager.values():
        manager_holdings.sort(key=lambda item: item.value_thousands, reverse=True)
        for index, holding in enumerate(manager_holdings, start=1):
            holding.position_rank = index


def _manager_turnover_proxy(
    current: dict[tuple[int, int], ManagerHolding],
    previous: dict[tuple[int, int], ManagerHolding],
) -> dict[int, float]:
    manager_ids = {manager_id for manager_id, _ in current} | {manager_id for manager_id, _ in previous}
    result: dict[int, float] = {}
    for manager_id in manager_ids:
        current_stocks = {stock_id for mgr_id, stock_id in current if mgr_id == manager_id}
        previous_stocks = {stock_id for mgr_id, stock_id in previous if mgr_id == manager_id}
        union = current_stocks | previous_stocks
        if not union:
            continue
        changed = current_stocks.symmetric_difference(previous_stocks)
        result[manager_id] = len(changed) / len(union)
    return result


def _holding_streaks(
    session: Session,
    selected_end: date,
    *,
    superinvestor_only: bool,
) -> dict[tuple[int, int], int]:
    periods = [item.period_end_date for item in _periods(session, superinvestor_only=superinvestor_only)]
    periods = [period for period in periods if period <= selected_end]
    periods.sort(reverse=True)
    if not periods:
        return {}

    presence_by_period = {
        period: set(_holdings_for_period(session, period, superinvestor_only=superinvestor_only).keys())
        for period in periods
    }
    selected_keys = presence_by_period.get(selected_end, set())
    streaks: dict[tuple[int, int], int] = {}
    for key in selected_keys:
        count = 0
        for period in periods:
            if key in presence_by_period.get(period, set()):
                count += 1
            else:
                break
        streaks[key] = count
    return streaks


def _apply_action(holding: ManagerHolding, previous: ManagerHolding | None) -> None:
    if previous is None:
        holding.action = "new"
        holding.previous_shares = None
        holding.share_delta_pct = None
        return
    holding.previous_shares = previous.shares
    if previous.shares <= 0:
        holding.action = "add"
        holding.share_delta_pct = None
        return
    delta = (holding.shares - previous.shares) / previous.shares
    holding.share_delta_pct = delta
    if delta > 0.05:
        holding.action = "add"
    elif delta < -0.05:
        holding.action = "reduce"
    else:
        holding.action = "flat"


def _apply_manager_signal_profiles(holdings: dict[tuple[int, int], ManagerHolding]) -> None:
    by_manager: dict[int, list[ManagerHolding]] = defaultdict(list)
    for holding in holdings.values():
        by_manager[holding.manager_id].append(holding)
    for manager_holdings in by_manager.values():
        profile = derive_manager_signal_profile(
            position_weights=[item.position_weight for item in manager_holdings],
            holding_streak_quarters=[item.holding_streak_quarters for item in manager_holdings],
            turnover_proxy=manager_holdings[0].turnover_proxy,
        )
        for holding in manager_holdings:
            holding.manager_type = profile.manager_type
            holding.manager_signal_weight = profile.manager_signal_weight
            holding.portfolio_concentration = profile.portfolio_concentration
            holding.portfolio_holding_count = profile.portfolio_holding_count
            holding.average_holding_period_quarters = profile.average_holding_period_quarters
            holding.manager_profile_source = profile.source


def _stock_payload(
    holdings: list[ManagerHolding],
    *,
    selected_period: PeriodInfo,
    latest_complete_period: PeriodInfo | None,
    min_holders: int,
) -> dict[str, Any]:
    holdings.sort(key=lambda item: item.position_weight, reverse=True)
    consensus_count = len(holdings)
    aggregate_weight = sum(item.position_weight for item in holdings)
    adders_count = sum(1 for item in holdings if item.action in {"new", "add"})
    reducers_count = sum(1 for item in holdings if item.action in {"reduce", "exit"})
    streak_values = [item.holding_streak_quarters for item in holdings]
    holder_price_estimates = [
        item.value_thousands * 1000 / item.shares
        for item in holdings
        if item.shares and item.shares > 0 and item.value_thousands and item.value_thousands > 0
    ]
    median_streak = int(median(streak_values)) if streak_values else 0
    max_streak = max(streak_values) if streak_values else 0
    signal_score = sum(item.manager_signal_weight * _position_signal_weight(item) for item in holdings)
    conviction_components = _conviction_components(holdings)
    conviction_score = sum(conviction_components.values())
    score_confidence = _score_confidence(holdings, selected_period, latest_complete_period)
    caution_flags = _caution_flags(
        holdings,
        selected_period=selected_period,
        latest_complete_period=latest_complete_period,
        conviction_score=conviction_score,
        score_confidence=score_confidence,
        min_holders=min_holders,
    )
    unknown_count = sum(1 for item in holdings if item.manager_type == "unknown")
    admin_unknown_count = sum(
        1 for item in holdings if item.manager_type_admin_classified == "unknown"
    )
    high_turnover_count = sum(1 for item in holdings if item.high_turnover)
    typed_count = consensus_count - unknown_count
    quality_coverage = typed_count / consensus_count if consensus_count else 0
    # MVP8-03B B4: portfolio-weight context for the Δ Holders chip — sum
    # of position_weight across adders / reducers so the chip tooltip can
    # show "+3 holders · adders weighted 8.2% · reducers weighted 1.1%".
    adders_portfolio_weight_sum = sum(
        item.position_weight for item in holdings if item.action in {"new", "add"}
    )
    reducers_portfolio_weight_sum = sum(
        item.position_weight for item in holdings if item.action in {"reduce", "exit"}
    )

    return {
        "stock_id": holdings[0].stock_id,
        "ticker": holdings[0].ticker,
        "company_name": holdings[0].company_name,
        "consensus_count": consensus_count,
        "signal_weighted_consensus_score": round(signal_score, 4),
        "score_confidence": score_confidence,
        "distinctive_consensus_score": round(signal_score, 4),
        "conviction_score": conviction_score,
        "adders_count": adders_count,
        "reducers_count": reducers_count,
        "aggregate_weight": round(aggregate_weight, 6),
        "add_intensity": round(_add_intensity(holdings), 4),
        "median_holding_streak_quarters": median_streak,
        "max_holding_streak_quarters": max_streak,
        "holder_price_estimate_low": round(min(holder_price_estimates), 6) if holder_price_estimates else None,
        "holder_price_estimate_high": round(max(holder_price_estimates), 6) if holder_price_estimates else None,
        "top_holders": [
            {
                "manager_id": item.manager_id,
                "manager_name": item.manager_name,
                "current_shares": item.shares,
                "previous_shares": item.previous_shares,
                "share_delta_pct": round(item.share_delta_pct, 6) if item.share_delta_pct is not None else None,
                "current_value_thousands": item.value_thousands,
                "holder_price_estimate": (
                    round(item.value_thousands * 1000 / item.shares, 6)
                    if item.shares and item.shares > 0 and item.value_thousands and item.value_thousands > 0
                    else None
                ),
                "position_weight": round(item.position_weight, 6),
                "position_rank": item.position_rank,
                "action": item.action,
                "holding_streak_quarters": item.holding_streak_quarters,
                "manager_type": item.manager_type,
                "manager_type_admin_classified": item.manager_type_admin_classified,
                "manager_signal_weight": round(item.manager_signal_weight, 4),
                "portfolio_concentration": item.portfolio_concentration,
                "portfolio_holding_count": item.portfolio_holding_count,
                "average_holding_period_quarters": item.average_holding_period_quarters,
                "manager_profile_source": item.manager_profile_source,
                "turnover_proxy": round(item.turnover_proxy, 4) if item.turnover_proxy is not None else None,
                "high_turnover": item.high_turnover,
                "filing_date": item.filing_date.isoformat() if item.filing_date else None,
                "accession_no": item.accession_no,
            }
            for item in holdings[:3]
        ],
        "manager_signal_summary": {
            "high_signal_holder_count": sum(1 for item in holdings if item.manager_signal_weight >= 0.75),
            "unknown_manager_type_count": unknown_count,
            "admin_unknown_manager_type_count": admin_unknown_count,
            "high_turnover_holder_count": high_turnover_count,
            "manager_signal_quality_coverage": round(quality_coverage, 4),
            "adders_portfolio_weight_sum": round(adders_portfolio_weight_sum, 6),
            "reducers_portfolio_weight_sum": round(reducers_portfolio_weight_sum, 6),
        },
        "score_explanation": {
            "primary_reasons": _primary_reasons(holdings, median_streak),
            "negative_reasons": [flag["label"] for flag in caution_flags[:2]],
            "conviction_components": conviction_components,
        },
        "caution_flags": caution_flags,
    }


def _position_signal_weight(holding: ManagerHolding) -> float:
    score = min(holding.position_weight * 4, 1.0)
    if holding.position_rank and holding.position_rank <= 10:
        score += 0.4
    if holding.position_weight >= 0.05:
        score += 0.3
    if holding.holding_streak_quarters >= 4:
        score += 0.3
    # MVP5-03 Phase 2: action magnitudes aligned to the persisted
    # constants in ``app/services/oracles_lens/constants.py`` so the
    # legacy in-memory path no longer disagrees with the canonical
    # scorer on which action is the stronger signal. Rationale
    # (SME #6 #1): a brand-new position is a more decisive signal
    # than an incremental add to an existing position, and a full
    # exit is a more decisive signal than a partial reduce.
    if holding.action == "new":
        score += 0.2
    elif holding.action == "add":
        score += 0.1
    elif holding.action == "reduce":
        score -= 0.1
    elif holding.action == "exit":
        score -= 0.2
    return max(score, 0)


def _conviction_components(holdings: list[ManagerHolding]) -> dict[str, int]:
    if not holdings:
        return {
            "position_importance": 0,
            "holding_persistence": 0,
            "manager_quality": 0,
            "recent_action": 0,
            "agreement": 0,
        }
    max_weight = max(item.position_weight for item in holdings)
    top_10_count = sum(1 for item in holdings if item.position_rank and item.position_rank <= 10)
    median_streak = median([item.holding_streak_quarters for item in holdings])
    avg_manager_weight = sum(item.manager_signal_weight for item in holdings) / len(holdings)
    add_context = sum(1 for item in holdings if item.action in {"new", "add"}) / len(holdings)
    agreement = min(len(holdings) / 5, 1)
    return {
        "position_importance": min(30, round(min(max_weight / 0.10, 1) * 20 + min(top_10_count / 2, 1) * 10)),
        "holding_persistence": min(25, round(min(median_streak / 4, 1) * 25)),
        "manager_quality": min(20, round(min(avg_manager_weight, 1) * 20)),
        "recent_action": min(15, round(add_context * 15)),
        "agreement": min(10, round(agreement * 10)),
    }


def _add_intensity(holdings: list[ManagerHolding]) -> float:
    action_scores = {"new": 1.0, "add": 0.7, "flat": 0.0, "reduce": -0.5, "exit": -1.0}
    total_weight = sum(max(item.position_weight, 0.001) for item in holdings)
    if total_weight <= 0:
        return 0
    return sum(action_scores.get(item.action, 0) * max(item.position_weight, 0.001) for item in holdings) / total_weight


def _score_confidence(
    holdings: list[ManagerHolding],
    selected_period: PeriodInfo,
    latest_complete_period: PeriodInfo | None,
) -> str:
    if not holdings:
        return "low"
    unknown_ratio = sum(1 for item in holdings if item.manager_type == "unknown") / len(holdings)
    max_streak = max(item.holding_streak_quarters for item in holdings)
    if latest_complete_period and selected_period.period_end_date < latest_complete_period.period_end_date:
        return "medium"
    if unknown_ratio >= 0.75:
        return "low" if max_streak < 2 else "medium"
    if max_streak >= 4:
        return "high"
    return "medium"


def _caution_flags(
    holdings: list[ManagerHolding],
    *,
    selected_period: PeriodInfo,
    latest_complete_period: PeriodInfo | None,
    conviction_score: int,
    score_confidence: str,
    min_holders: int,
) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    unknown_count = sum(1 for item in holdings if item.manager_type == "unknown")
    if unknown_count / len(holdings) >= 0.5:
        flags.append(
            {
                "key": "unknown_manager_type_heavy",
                "group": "signal_quality",
                "severity": "warning",
                "label": f"{unknown_count} of {len(holdings)} holders have unknown manager type",
            }
        )
    if any(item.high_turnover for item in holdings):
        flags.append(
            {
                "key": "high_turnover_holders",
                "group": "signal_quality",
                "severity": "warning",
                "label": "Signal includes high-turnover holders",
            }
        )
    if conviction_score < 50:
        flags.append(
            {
                "key": "low_conviction",
                "group": "conviction",
                "severity": "warning",
                "label": "Ownership signal has low conviction score",
            }
        )
    if max(item.holding_streak_quarters for item in holdings) < 2:
        flags.append(
            {
                "key": "short_holding_streak",
                "group": "conviction",
                "severity": "info",
                "label": "Holding streak is short",
            }
        )
    if score_confidence == "low":
        flags.append(
            {
                "key": "low_score_confidence",
                "group": "data_coverage",
                "severity": "warning",
                "label": "Score confidence is low due to missing or sparse inputs",
            }
        )
    if latest_complete_period and selected_period.period_end_date < latest_complete_period.period_end_date:
        flags.append(
            {
                "key": "old_period_selected",
                "group": "timing",
                "severity": "info",
                "label": "Selected period is older than the latest complete 13F period",
            }
        )
    if selected_period.manager_count and selected_period.manager_count < min_holders:
        flags.append(
            {
                "key": "partial_period",
                "group": "timing",
                "severity": "warning",
                "label": "Selected period has limited manager coverage",
            }
        )
    return flags


def _primary_reasons(holdings: list[ManagerHolding], median_streak: int) -> list[str]:
    top_10 = sum(1 for item in holdings if item.position_rank and item.position_rank <= 10)
    return [
        f"{len(holdings)} confirmed superinvestor holders",
        f"{top_10} holders rank it as a top 10 position",
        f"Median holding streak is {median_streak} quarters",
    ]


def _quality_overlay_by_stock(
    session: Session,
    stock_ids: list[int],
    *,
    price_as_of_date: date | None = None,
    price_context: str = "latest",
) -> dict[int, dict[str, Any]]:
    unique_stock_ids = list(dict.fromkeys(stock_ids))
    if not unique_stock_ids:
        return {}

    facts = (
        session.query(MetricFact)
        .filter(MetricFact.stock_id.in_(unique_stock_ids))
        .filter(MetricFact.metric_key.in_(QUALITY_METRIC_KEYS.values()))
        .filter(MetricFact.is_current.is_(True))
        .filter(MetricFact.value_numeric.isnot(None))
        .order_by(MetricFact.stock_id.asc(), MetricFact.period_end_date.desc(), MetricFact.created_at.desc())
        .all()
    )
    facts_by_stock: dict[int, dict[str, MetricFact]] = {stock_id: {} for stock_id in unique_stock_ids}
    reverse_keys = {metric_key: label for label, metric_key in QUALITY_METRIC_KEYS.items()}
    for fact in facts:
        label = reverse_keys.get(fact.metric_key)
        if label and label not in facts_by_stock[fact.stock_id]:
            facts_by_stock[fact.stock_id][label] = fact

    latest_prices = _latest_prices_by_stock(session, unique_stock_ids, as_of_date=price_as_of_date)
    return {
        stock_id: _quality_payload(
            facts_by_stock.get(stock_id, {}),
            latest_prices.get(stock_id),
            price_context=price_context,
        )
        for stock_id in unique_stock_ids
    }


def _latest_prices_by_stock(
    session: Session,
    stock_ids: list[int],
    *,
    as_of_date: date | None = None,
) -> dict[int, StockPrice]:
    query = (
        session.query(StockPrice)
        .filter(StockPrice.stock_id.in_(stock_ids))
    )
    if as_of_date is not None:
        query = query.filter(StockPrice.price_date <= as_of_date)
    prices = (
        query.order_by(StockPrice.stock_id.asc(), StockPrice.price_date.desc(), StockPrice.created_at.desc()).all()
    )
    result: dict[int, StockPrice] = {}
    for price in prices:
        if price.stock_id not in result:
            result[price.stock_id] = price
    return result


def _quality_payload(
    facts: dict[str, MetricFact],
    latest_price: StockPrice | None,
    *,
    price_context: str = "latest",
) -> dict[str, Any]:
    price = float(latest_price.close) if latest_price and latest_price.close is not None else None
    owners_earnings = _fact_value(facts.get("owners_earnings"))
    owner_yield = owners_earnings / price if owners_earnings is not None and price else None
    values = {
        "piotroski_total": _fact_value(facts.get("piotroski_total")),
        "return_on_total_capital": _fact_value(facts.get("return_on_total_capital")),
        "return_on_equity": _fact_value(facts.get("return_on_equity")),
        "net_profit_margin": _fact_value(facts.get("net_profit_margin")),
        "debt_to_capital": _fact_value(facts.get("debt_to_capital")),
        "owner_earnings_yield": owner_yield,
        "latest_price": price,
        "price_date": latest_price.price_date.isoformat() if latest_price else None,
        "price_context": price_context,
    }
    available_metrics = sum(
        1
        for key in [
            "piotroski_total",
            "return_on_total_capital",
            "return_on_equity",
            "net_profit_margin",
            "debt_to_capital",
            "owner_earnings_yield",
        ]
        if values[key] is not None
    )
    unavailable: list[str] = []
    if not facts:
        unavailable.append("missing Value Line facts")
    if price is None:
        unavailable.append("missing price")
    if owners_earnings is None:
        unavailable.append("missing normalized owner earnings")
    elif owner_yield is None:
        unavailable.append("owner earnings yield unavailable without price")

    return {
        **values,
        "coverage": {
            "value_line": any(key in facts for key in QUALITY_METRIC_KEYS if key != "owners_earnings"),
            "price": price is not None,
            "owner_earnings": owners_earnings is not None,
            "available_metrics": available_metrics,
            "expected_metrics": 6,
        },
        "unavailable_reasons": unavailable,
        "provenance": _quality_provenance(facts),
    }


def _quality_provenance(facts: dict[str, MetricFact]) -> dict[str, Any]:
    fact_rows = []
    source_document_ids = set()
    for label in QUALITY_METRIC_KEYS:
        fact = facts.get(label)
        if fact is None:
            continue
        if fact.source_document_id is not None:
            source_document_ids.add(fact.source_document_id)
        fact_rows.append(
            {
                "label": label,
                "metric_key": fact.metric_key,
                "source_document_id": fact.source_document_id,
                "source_type": fact.source_type,
                "period_type": fact.period_type,
                "period_end_date": fact.period_end_date.isoformat() if fact.period_end_date else None,
            }
        )
    sorted_document_ids = sorted(source_document_ids)
    return {
        "primary_source_document_id": sorted_document_ids[0] if sorted_document_ids else None,
        "source_document_ids": sorted_document_ids,
        "facts": fact_rows,
    }


def _fact_value(fact: MetricFact | None) -> float | None:
    return float(fact.value_numeric) if fact and fact.value_numeric is not None else None


def _empty_quality_overlay() -> dict[str, Any]:
    return _quality_payload({}, None)


def _valuation_reference_by_stock(
    session: Session,
    holder_ranges_by_stock: dict[int, tuple[float | None, float | None]],
    *,
    price_as_of_date: date | None = None,
    price_context: str = "latest",
) -> dict[int, dict[str, Any]]:
    stock_ids = list(holder_ranges_by_stock)
    if not stock_ids:
        return {}

    facts = (
        session.query(MetricFact)
        .filter(MetricFact.stock_id.in_(stock_ids))
        .filter(MetricFact.metric_key.in_(VALUATION_REFERENCE_KEYS))
        .filter(MetricFact.is_current.is_(True))
        .filter(MetricFact.value_numeric.isnot(None))
        .order_by(MetricFact.stock_id.asc(), MetricFact.created_at.desc())
        .all()
    )
    facts_by_stock: dict[int, dict[str, MetricFact]] = {stock_id: {} for stock_id in stock_ids}
    for fact in facts:
        if fact.metric_key == MANUAL_VALUATION_REFERENCE_KEY and fact.source_type != "manual":
            continue
        if fact.metric_key not in facts_by_stock[fact.stock_id]:
            facts_by_stock[fact.stock_id][fact.metric_key] = fact

    latest_prices = _latest_prices_by_stock(session, stock_ids, as_of_date=price_as_of_date)
    return {
        stock_id: _valuation_payload(
            facts_by_stock.get(stock_id, {}),
            latest_prices.get(stock_id),
            holder_ranges_by_stock.get(stock_id, (None, None)),
            price_context=price_context,
        )
        for stock_id in stock_ids
    }


def _valuation_payload(
    facts: dict[str, MetricFact],
    latest_price: StockPrice | None,
    holder_range: tuple[float | None, float | None],
    *,
    price_context: str = "latest",
) -> dict[str, Any]:
    price = float(latest_price.close) if latest_price and latest_price.close is not None else None
    holder_low, holder_high = holder_range
    manual = facts.get(MANUAL_VALUATION_REFERENCE_KEY)
    target = facts.get(VALUE_LINE_VALUATION_REFERENCE_KEY)
    reference = None
    reference_label = None
    reference_type = "missing"
    reference_confidence = "unavailable"
    if manual and manual.value_numeric is not None:
        reference = float(manual.value_numeric)
        reference_label = "User-entered valuation reference"
        reference_type = "manual_intrinsic_value"
        reference_confidence = "user_supplied"
    elif target and target.value_numeric is not None:
        reference = float(target.value_numeric)
        reference_label = "Value Line 18-month target midpoint"
        reference_type = "analyst_target_reference"
        reference_confidence = "medium"

    discount_to_reference = None
    if price is not None and reference:
        discount_to_reference = round((reference - price) / reference, 6)

    unavailable: list[str] = []
    if price is None:
        unavailable.append("missing price")
    if reference is None:
        unavailable.append("missing valuation reference")
    if holder_low is None or holder_high is None:
        unavailable.append("missing holder price estimate")

    return {
        "current_price": price,
        "current_price_date": latest_price.price_date.isoformat() if latest_price else None,
        "price_context": price_context,
        "valuation_reference": reference,
        "valuation_reference_label": reference_label,
        "valuation_reference_type": reference_type,
        "valuation_reference_confidence": reference_confidence,
        "discount_to_reference": discount_to_reference,
        "valuation_state": {
            "below_holder_estimate": bool(price is not None and holder_low is not None and price < holder_low),
            "below_selected_valuation_reference": bool(
                price is not None and reference is not None and price < reference
            ),
        },
        "valuation_unavailable_reasons": unavailable,
    }


def _empty_valuation_reference() -> dict[str, Any]:
    return _valuation_payload({}, None, (None, None))


def _coverage(
    session: Session,
    period_end: date,
    *,
    superinvestor_only: bool,
    quality_by_stock: dict[int, dict[str, Any]] | None = None,
    valuation_by_stock: dict[int, dict[str, Any]] | None = None,
    price_context: str = "latest",
    price_target_date: date | None = None,
) -> dict[str, Any]:
    query = (
        session.query(Holding13F, Filing13F, InstitutionManager)
        .join(Filing13F, Filing13F.id == Holding13F.filing_id)
        .join(InstitutionManager, InstitutionManager.id == Filing13F.manager_id)
        .filter(Filing13F.period_of_report == period_end)
        .filter(Filing13F.is_latest_for_period.is_(True))
        .filter(InstitutionManager.match_status == "confirmed")
        .filter(InstitutionManager.cik.isnot(None))
    )
    if superinvestor_only:
        query = query.filter(InstitutionManager.is_superinvestor.is_(True))
    rows = query.all()
    manager_ids = {filing.manager_id for _, filing, _ in rows}
    linked_count = sum(1 for holding, _, _ in rows if holding.stock_id is not None)
    candidate_count = len(quality_by_stock or {})
    price_coverage_count = sum(
        1 for item in (quality_by_stock or {}).values() if item["coverage"]["price"]
    )
    price_missing_count = max(candidate_count - price_coverage_count, 0)
    price_backfill_required = price_context == "historical_snapshot" and price_missing_count > 0
    return {
        "manager_count": len(manager_ids),
        "holding_count": len(rows),
        "linked_holding_count": linked_count,
        "candidate_count": candidate_count,
        "manager_signal_quality_coverage": 0,
        "price_context": price_context,
        "price_target_date": price_target_date.isoformat() if price_target_date else None,
        "price_coverage_count": price_coverage_count,
        "price_missing_count": price_missing_count,
        "price_coverage_ratio": round(price_coverage_count / candidate_count, 4) if candidate_count else 0,
        "price_backfill_required": price_backfill_required,
        "price_backfill_hint": (
            "docker compose exec api python -m scripts.backfill_13f_period_prices "
            f"--period {period_end.isoformat()}"
            if price_backfill_required
            else None
        ),
        "value_line_coverage_count": sum(
            1 for item in (quality_by_stock or {}).values() if item["coverage"]["value_line"]
        ),
        "valuation_reference_coverage_count": sum(
            1 for item in (valuation_by_stock or {}).values() if item["valuation_reference"] is not None
        ),
    }


def _empty_coverage() -> dict[str, Any]:
    return {
        "manager_count": 0,
        "holding_count": 0,
        "linked_holding_count": 0,
        "candidate_count": 0,
        "manager_signal_quality_coverage": 0,
        "price_context": "latest",
        "price_target_date": None,
        "price_coverage_count": 0,
        "price_missing_count": 0,
        "price_coverage_ratio": 0,
        "price_backfill_required": False,
        "price_backfill_hint": None,
        "value_line_coverage_count": 0,
        "valuation_reference_coverage_count": 0,
    }


def _sort_key(sort: str):
    key_map = {
        "signal_weighted_consensus": "signal_weighted_consensus_score",
        "conviction": "conviction_score",
        "distinctive_consensus": "distinctive_consensus_score",
        "add_intensity": "add_intensity",
        "aggregate_weight": "aggregate_weight",
        "quality": "score_confidence",
    }
    key = key_map.get(sort, "signal_weighted_consensus_score")
    return lambda item: item.get(key) or 0


def _period_label(period_end: date) -> str:
    quarter = ((period_end.month - 1) // 3) + 1
    return f"{period_end.year}-Q{quarter}"


def _period_label_to_end_date(label: str) -> date:
    try:
        year_part, quarter_part = label.upper().split("-Q")
        year = int(year_part)
        quarter = int(quarter_part)
    except (ValueError, AttributeError):
        raise ValueError("period must be YYYY-Qn")
    if quarter == 1:
        return date(year, 3, 31)
    if quarter == 2:
        return date(year, 6, 30)
    if quarter == 3:
        return date(year, 9, 30)
    if quarter == 4:
        return date(year, 12, 31)
    raise ValueError("period must be YYYY-Qn")
