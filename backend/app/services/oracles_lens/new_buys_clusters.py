"""Value-investor-first aggregation of quarterly 13F new-position clusters.

The materialized ``ownership_changes`` table is the evidence source. A row is
only exposed while its referenced current filing remains the active HR-family
filing for that manager/quarter. Cluster ranking uses independent managers that
are primary-signal eligible and caveat-free; excluded evidence remains visible
so uncertainty is never silently converted to zero.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.institutions import Filing13F, InstitutionManager, OwnershipChange13F
from app.models.stocks import Stock
from app.services.oracles_lens.manager_taxonomy import resolve_manager_type
from app.services.thirteenf_holdings_query import HR_FORM_TYPES, active_hr_holdings_query
from app.services.thirteenf_user_api import (
    MANAGER_SCOPES,
    _manager_in_scope,
    _manager_payload,
)


SCORE_CONFIDENCE_LEVELS = {"high_confidence", "medium_confidence"}


def build_new_buys_clusters(
    session: Session,
    *,
    quarter: str | None = None,
    min_cluster_size: int = 2,
    superinvestors_only: bool = True,
    manager_scope: str = "value",
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Return stock clusters formed by managers opening common positions.

    ``cluster_size`` is the number of distinct buyers included in score, not
    the number of raw evidence rows. This prevents a caveated or low-confidence
    row from manufacturing a cluster while keeping that row in ``buyers``.
    """
    if manager_scope not in MANAGER_SCOPES:
        raise ValueError(f"Unsupported manager_scope: {manager_scope}")
    if not 1 <= min_cluster_size <= 50:
        raise ValueError("min_cluster_size must be between 1 and 50")

    selected_quarter = quarter or _latest_cluster_quarter(session)
    if selected_quarter is None:
        return {
            "quarter": None,
            "manager_scope": manager_scope,
            "superinvestors_only": superinvestors_only,
            "min_cluster_size": min_cluster_size,
            "filing_window_open": False,
            "official_filing_deadline": None,
            "coverage": {"reported_manager_count": 0, "tracked_manager_count": 0},
            "periods": [],
            "items": [],
        }

    rows = (
        session.query(OwnershipChange13F, InstitutionManager, Stock, Filing13F)
        .join(InstitutionManager, InstitutionManager.id == OwnershipChange13F.manager_id)
        .join(Stock, Stock.id == OwnershipChange13F.stock_id)
        .join(Filing13F, Filing13F.id == OwnershipChange13F.current_filing_id)
        .filter(
            OwnershipChange13F.report_quarter == selected_quarter,
            OwnershipChange13F.change_status == "new_position",
            OwnershipChange13F.position_type == "common",
            Filing13F.is_active_for_manager_period.is_(True),
            Filing13F.form_type.in_(HR_FORM_TYPES),
            Filing13F.report_quarter == selected_quarter,
            InstitutionManager.status == "active",
        )
        .all()
    )
    rows = [
        row
        for row in rows
        if _manager_in_scope(row[1], manager_scope)
        and (not superinvestors_only or row[1].is_superinvestor)
    ]

    denominators = _common_value_denominators(
        session,
        {filing.id: filing for _, _, _, filing in rows},
    )
    clusters: dict[int, dict[str, Any]] = {}
    for change, manager, stock, filing in rows:
        cluster = clusters.setdefault(
            stock.id,
            {
                "stock": {
                    "id": stock.id,
                    "ticker": stock.ticker,
                    "company_name": stock.company_name,
                    "exchange": stock.exchange,
                },
                "buyers": [],
            },
        )
        exclusion_reasons = _score_exclusion_reasons(change)
        resolution = resolve_manager_type(manager)
        denominator = denominators.get(filing.id)
        portfolio_weight_pct = (
            float(change.current_portfolio_weight_pct)
            if change.current_portfolio_weight_pct is not None
            else (
                round((change.current_value_usd / denominator) * 100, 6)
                if change.current_value_usd is not None and denominator
                else None
            )
        )
        cluster["buyers"].append(
            {
                "manager": _manager_payload(manager),
                "change_id": change.id,
                "current_value_usd": change.current_value_usd,
                "current_shares": change.current_shares,
                "portfolio_weight_pct": portfolio_weight_pct,
                "confidence_level": change.confidence_level,
                "caveat_codes": change.caveat_codes or [],
                "included_in_score": not exclusion_reasons,
                "score_exclusion_reasons": exclusion_reasons,
                "manager_signal_weight": float(resolution.weight),
                "manager_type_source": resolution.source,
            }
        )

    items: list[dict[str, Any]] = []
    for cluster in clusters.values():
        buyers = _dedupe_manager_buyers(cluster["buyers"])
        eligible = [buyer for buyer in buyers if buyer["included_in_score"]]
        if len(eligible) < min_cluster_size:
            continue
        score = sum(
            (Decimal(str(buyer["manager_signal_weight"])) for buyer in eligible),
            Decimal("0"),
        )
        buyers.sort(
            key=lambda buyer: (
                not buyer["included_in_score"],
                -buyer["manager_signal_weight"],
                -(buyer["portfolio_weight_pct"] or -1),
                buyer["manager"]["display_name"],
            )
        )
        items.append(
            {
                **cluster,
                "buyers": buyers,
                "cluster_size": len(eligible),
                "visible_buyer_count": len(buyers),
                "quality_weighted_cluster_score": float(score),
                "has_excluded_evidence": len(eligible) != len(buyers),
            }
        )

    items.sort(
        key=lambda item: (
            -item["quality_weighted_cluster_score"],
            -item["cluster_size"],
            item["stock"]["ticker"],
        )
    )
    deadline = _official_deadline(session, selected_quarter)
    today = as_of_date or date.today()
    return {
        "quarter": selected_quarter,
        "manager_scope": manager_scope,
        "superinvestors_only": superinvestors_only,
        "min_cluster_size": min_cluster_size,
        "filing_window_open": deadline is not None and today <= deadline,
        "official_filing_deadline": deadline.isoformat() if deadline else None,
        "coverage": _coverage(
            session,
            selected_quarter,
            manager_scope=manager_scope,
            superinvestors_only=superinvestors_only,
        ),
        "periods": _periods(session),
        "items": items,
    }


def _latest_cluster_quarter(session: Session) -> str | None:
    row = (
        session.query(OwnershipChange13F.report_quarter)
        .join(Filing13F, Filing13F.id == OwnershipChange13F.current_filing_id)
        .filter(
            OwnershipChange13F.change_status == "new_position",
            Filing13F.is_active_for_manager_period.is_(True),
            Filing13F.form_type.in_(HR_FORM_TYPES),
        )
        .order_by(OwnershipChange13F.quarter_end_date.desc())
        .first()
    )
    return row[0] if row else None


def _score_exclusion_reasons(change: OwnershipChange13F) -> list[str]:
    reasons: list[str] = []
    if change.confidence_level not in SCORE_CONFIDENCE_LEVELS:
        reasons.append("LOW_CONFIDENCE")
    if not change.is_primary_signal_eligible:
        reasons.append("NOT_PRIMARY_SIGNAL_ELIGIBLE")
    reasons.extend(str(code) for code in (change.caveat_codes or []))
    if change.unavailable_reason:
        reasons.append(change.unavailable_reason)
    return list(dict.fromkeys(reasons))


def _dedupe_manager_buyers(buyers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one economic buyer per manager if source rows ever fragment."""
    by_manager: dict[int, dict[str, Any]] = {}
    for buyer in buyers:
        manager_id = int(buyer["manager"]["id"])
        existing = by_manager.get(manager_id)
        if existing is None or (
            buyer["included_in_score"],
            buyer["current_value_usd"] or -1,
        ) > (
            existing["included_in_score"],
            existing["current_value_usd"] or -1,
        ):
            by_manager[manager_id] = buyer
    return list(by_manager.values())


def _common_value_denominators(
    session: Session,
    filings: dict[int, Filing13F],
) -> dict[int, int | None]:
    result: dict[int, int | None] = {}
    unresolved_ids: list[int] = []
    for filing_id, filing in filings.items():
        if filing.coverage_completeness != "complete":
            result[filing_id] = None
        elif filing.total_13f_common_value_usd:
            result[filing_id] = int(filing.total_13f_common_value_usd)
        else:
            unresolved_ids.append(filing_id)
    if unresolved_ids:
        holdings = active_hr_holdings_query(session).filter(
            Filing13F.id.in_(unresolved_ids)
        ).all()
        by_filing: dict[int, list[int | None]] = {filing_id: [] for filing_id in unresolved_ids}
        for holding in holdings:
            if holding.put_call is None:
                by_filing[holding.filing_id].append(holding.value_usd)
        for filing_id, values in by_filing.items():
            result[filing_id] = (
                sum(int(value) for value in values if value is not None)
                if values and all(value is not None for value in values)
                else None
            )
    return result


def _official_deadline(session: Session, quarter: str) -> date | None:
    row = (
        session.query(Filing13F.official_filing_deadline)
        .filter(
            Filing13F.report_quarter == quarter,
            Filing13F.is_active_for_manager_period.is_(True),
            Filing13F.official_filing_deadline.isnot(None),
        )
        .order_by(Filing13F.official_filing_deadline.desc())
        .first()
    )
    return row[0] if row else None


def _coverage(
    session: Session,
    quarter: str,
    *,
    manager_scope: str,
    superinvestors_only: bool,
) -> dict[str, int]:
    tracked = (
        session.query(InstitutionManager)
        .filter(InstitutionManager.status == "active", InstitutionManager.cik.isnot(None))
        .all()
    )
    tracked = [
        manager
        for manager in tracked
        if _manager_in_scope(manager, manager_scope)
        and (not superinvestors_only or manager.is_superinvestor)
    ]
    tracked_ids = {manager.id for manager in tracked}
    reported = {
        manager_id
        for (manager_id,) in session.query(Filing13F.manager_id)
        .filter(
            Filing13F.report_quarter == quarter,
            Filing13F.is_active_for_manager_period.is_(True),
            Filing13F.form_type.in_(HR_FORM_TYPES),
        )
        .all()
        if manager_id in tracked_ids
    }
    return {
        "reported_manager_count": len(reported),
        "tracked_manager_count": len(tracked_ids),
    }


def _periods(session: Session) -> list[str]:
    return [
        quarter
        for (quarter,) in session.query(OwnershipChange13F.report_quarter)
        .filter(OwnershipChange13F.change_status == "new_position")
        .distinct()
        .order_by(OwnershipChange13F.report_quarter.desc())
        .all()
    ]
