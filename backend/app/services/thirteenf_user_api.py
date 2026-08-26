"""Safe user-facing 13F API response builders.

These builders preserve the PRD §7.3 query contract for Oracle's Lens:
product holdings are sourced only from active HR/HR-A filings with a current
parse run. 13F-NT and unavailable future features return explicit structured
reasons instead of empty holdings that could be misread as "no positions."
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    OwnershipChange13F,
    ParseRun13F,
)
from app.models.stocks import Stock, StockPrice
from app.services.market_data_service import (
    ET,
    compute_target_date,
    read_canonical_eod_series,
)
from app.services.thirteenf_holdings_query import HR_FORM_TYPES, NT_FORM_TYPES, active_hr_holdings_query


NT_CAVEAT = "This manager filed a 13F Notice; its 13(f) holdings are reported by other manager(s)."
COMBINATION_CAVEAT = (
    "This is a 13F Combination Report: holdings include positions the filer "
    "reports jointly with its included managers (e.g. subsidiaries)."
)
CONFIDENTIAL_CAVEAT = (
    "Some holdings may be omitted from this filing due to confidential treatment. "
    "Additional holdings may be disclosed in a future amendment."
)
FILING_WINDOW_CAVEAT = (
    "The filing window for this quarter may still be open. The snapshot can change until "
    "the official filing deadline passes."
)
SHARED_DISCRETION_CAVEAT = (
    "This report includes positions held under shared/defined discretion with other "
    "managers (which may include affiliates, subsidiaries, or a manager whose holdings "
    "are aggregated into this filing) — not necessarily independent sole-manager positions."
)
RECENT_CHANGE_STATUSES = {"new_position", "increased", "reduced", "exited_position"}
# Legacy MVP2 export retained for callers/tests that still describe the old
# manager_type-based consumer scope. New investor surfaces use
# VALUE_STYLE_PRIMARY below; do not use this alias for V2 default filtering.
VALUE_MANAGER_TYPES = {"long_term_fundamental", "activist"}
VALUE_STYLE_PRIMARY = {"value_deep", "value_concentrated", "quality_compounder"}
MANAGER_SCOPES = {"value", "value_plus_activist", "all"}


def _load_curated_manager_profiles() -> dict[str, dict[str, Any]]:
    """Return the human-reviewed seed metadata keyed by normalized CIK.

    ``classification_rationale`` deliberately remains curated evidence rather
    than generated prose. Managers outside the confirmed seed simply receive a
    null rationale in the consumer response.
    """
    seed_path = Path(__file__).resolve().parent / "seed_data" / "confirmed_managers.json"
    try:
        entries = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(entry.get("cik") or "").zfill(10): entry
        for entry in entries
        if entry.get("cik")
    }


CURATED_MANAGER_PROFILES = _load_curated_manager_profiles()


def build_user_managers(session: Session) -> dict[str, Any]:
    managers = (
        session.query(InstitutionManager)
        .filter(InstitutionManager.status == "active")
        .filter(InstitutionManager.cik.isnot(None))
        .order_by(InstitutionManager.is_featured.desc(), InstitutionManager.display_name, InstitutionManager.canonical_name)
        .all()
    )
    manager_ids = [manager.id for manager in managers]
    latest_by_manager: dict[int, Filing13F] = {}
    if manager_ids:
        filings = (
            session.query(Filing13F)
            .filter(Filing13F.manager_id.in_(manager_ids))
            .filter(Filing13F.is_active_for_manager_period.is_(True))
            .order_by(
                Filing13F.quarter_end_date.desc().nullslast(),
                Filing13F.report_quarter.desc().nullslast(),
                Filing13F.accepted_at.desc().nullslast(),
            )
            .all()
        )
        for filing in filings:
            latest_by_manager.setdefault(filing.manager_id, filing)
    return {
        "items": [
            _manager_payload(manager, latest_filing=latest_by_manager.get(manager.id))
            for manager in managers
        ]
    }


def build_user_manager_quarters(session: Session, manager_id: int) -> dict[str, Any]:
    _require_manager(session, manager_id)
    filings = (
        session.query(Filing13F)
        .filter(Filing13F.manager_id == manager_id)
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .order_by(Filing13F.quarter_end_date.desc().nullslast(), Filing13F.report_quarter.desc().nullslast())
        .all()
    )
    return {
        "manager_id": manager_id,
        "items": [_quarter_payload(filing) for filing in filings],
    }


def build_user_manager_holdings(
    session: Session,
    manager_id: int,
    quarter: str | None = None,
    *,
    include_market_context: bool = True,
) -> dict[str, Any]:
    manager = _require_manager(session, manager_id)
    active_filing = _active_filing(session, manager_id, quarter)
    if not active_filing:
        return _unavailable_holdings(
            manager,
            quarter,
            code="NO_ACTIVE_FILING",
            message="No active 13F filing is available for this manager and quarter.",
        )

    caveats = _filing_caveats(active_filing)
    if active_filing.form_type in NT_FORM_TYPES:
        return _unavailable_holdings(
            manager,
            active_filing.report_quarter or quarter,
            code="NOTICE_REPORTED_ELSEWHERE",
            message=NT_CAVEAT,
            caveats=caveats or [{"code": "NOTICE_REPORTED_ELSEWHERE", "message": NT_CAVEAT}],
            filing=active_filing,
        )

    holdings_q = active_hr_holdings_query(session).filter(Holding13F.manager_id == manager_id)
    if active_filing.report_quarter:
        holdings_q = holdings_q.filter(Holding13F.report_quarter == active_filing.report_quarter)
    elif quarter:
        holdings_q = holdings_q.filter(Holding13F.report_quarter == quarter)
    holdings = holdings_q.order_by(Holding13F.source_row_index, Holding13F.id).all()
    verified_empty = not holdings and (
        session.query(ParseRun13F.id)
        .filter(
            ParseRun13F.accession_number == active_filing.accession_number,
            ParseRun13F.is_current.is_(True),
            ParseRun13F.status == "succeeded",
            ParseRun13F.holdings_count == 0,
        )
        .first()
        is not None
    )
    if not holdings and not verified_empty:
        return _unavailable_holdings(
            manager,
            active_filing.report_quarter or quarter,
            code="NO_CURRENT_HOLDINGS",
            message="No current parsed holdings are available for this manager and quarter.",
            caveats=caveats,
            filing=active_filing,
        )

    # T3 review follow-up: a complete holdings_report may still hold shared/defined
    # discretion positions with no cover-page included-managers list (sub-threshold
    # shared discretion, no Column 7). `_filing_caveats` can't see that from the
    # filing alone, so derive it here from the displayed holdings' discretion.
    if any(h.investment_discretion in ("DFND", "OTR") for h in holdings) and not any(
        c["code"] == "SHARED_DISCRETION" for c in caveats
    ):
        caveats = [*caveats, {"code": "SHARED_DISCRETION", "message": SHARED_DISCRETION_CAVEAT}]

    common, options = _manager_position_payloads(
        session,
        manager_id=manager_id,
        filing=active_filing,
        holdings=holdings,
    )
    _attach_implied_report_prices(common)
    if include_market_context:
        _attach_market_context(session, common)
    if verified_empty:
        reported_common_value = 0
    elif (
        active_filing.total_13f_common_value_usd is not None
        and active_filing.total_13f_common_value_usd > 0
    ):
        reported_common_value = int(active_filing.total_13f_common_value_usd)
    else:
        reported_common_value = _sum_all_known(item["value_usd"] for item in common)
    material_caveats = {item["code"] for item in caveats} & {"COMBINATION_REPORT", "CONFIDENTIAL_TREATMENT", "SHARED_DISCRETION"}
    return {
        "status": "available_with_caveat" if material_caveats else "available",
        "manager": _manager_payload(manager),
        "quarter": active_filing.report_quarter or quarter,
        "quarter_end_date": _iso(active_filing.quarter_end_date),
        "filing": _filing_payload(active_filing),
        "caveats": caveats,
        "summary": {
            "common_position_count": len(common),
            "reported_common_value_usd": reported_common_value,
        },
        "common_holdings": common,
        "options": options,
    }


def build_user_manager_holding_changes(
    session: Session,
    manager_id: int,
    quarter: str | None = None,
) -> dict[str, Any]:
    manager = _require_manager(session, manager_id)
    as_of_quarter = quarter or _latest_manager_change_quarter(session, manager_id)
    if not as_of_quarter:
        return _unavailable_holding_changes(
            manager,
            quarter,
            code="NO_COMPUTED_CHANGES",
            message="No precomputed 13F holding changes are available for this manager.",
        )

    changes = (
        session.query(OwnershipChange13F, Stock)
        .outerjoin(Stock, Stock.id == OwnershipChange13F.stock_id)
        .filter(
            OwnershipChange13F.manager_id == manager_id,
            OwnershipChange13F.report_quarter == as_of_quarter,
        )
        .order_by(
            OwnershipChange13F.is_primary_signal_eligible.desc(),
            OwnershipChange13F.change_status,
            Stock.ticker.nullslast(),
            OwnershipChange13F.security_key,
        )
        .all()
    )
    if not changes:
        return _unavailable_holding_changes(
            manager,
            as_of_quarter,
            code="NO_COMPUTED_CHANGES",
            message="No precomputed 13F holding changes are available for this manager and quarter.",
        )

    # Series-review P1 (defense in depth): materialized rows are only current
    # while the quarter still has an active HR-family filing. An authority
    # freeze (tie / missing acceptance / none eligible) deactivates the filing
    # immediately, but the compute stage that clears the rows runs later —
    # between the two, rendering the rows would present disputed data as
    # available ("unknown is not zero"). The next compute run deletes them.
    active = _active_filing(session, manager_id, as_of_quarter)
    if active is None or active.form_type not in HR_FORM_TYPES:
        return _unavailable_holding_changes(
            manager,
            as_of_quarter,
            code="NO_ACTIVE_FILING",
            message=(
                "This quarter's 13F filing is currently unavailable or under "
                "review; previously computed holding changes are withheld "
                "until an active filing is restored."
            ),
        )

    filing_denominators = _manager_quarter_common_denominators(
        session,
        manager_id=manager_id,
        quarters={
            quarter
            for change, _ in changes
            for quarter in (change.report_quarter, change.previous_report_quarter)
            if quarter
        },
    )
    items = [
        _manager_change_payload(
            change,
            stock,
            current_denominator=filing_denominators.get(change.report_quarter),
            previous_denominator=filing_denominators.get(change.previous_report_quarter),
        )
        for change, stock in changes
    ]
    has_caveats = any(
        item["caveat_codes"] or item["unavailable_reason"] or item["confidence_level"] in {"low_confidence", "unavailable"}
        for item in items
    )
    return {
        "status": "available_with_caveat" if has_caveats else "available",
        "manager": _manager_payload(manager),
        "quarter": as_of_quarter,
        "quarter_end_date": _iso(changes[0][0].quarter_end_date),
        "reason": None,
        "items": items,
    }


def build_user_manager_history(session: Session, manager_id: int) -> dict[str, Any]:
    """Build a read-only multi-quarter manager research surface.

    Active filings remain the authority for every quarter. Materialized change
    rows are included only while their quarter still has an active HR-family
    filing, matching the single-quarter changes endpoint's freeze behavior.
    """
    manager = _require_manager(session, manager_id)
    filings = (
        session.query(Filing13F)
        .filter(
            Filing13F.manager_id == manager_id,
            Filing13F.is_active_for_manager_period.is_(True),
        )
        .order_by(
            Filing13F.quarter_end_date.desc().nullslast(),
            Filing13F.report_quarter.desc().nullslast(),
            Filing13F.accepted_at.desc().nullslast(),
        )
        .all()
    )
    if not filings:
        return {
            "status": "unavailable",
            "manager": _manager_payload(manager),
            "reason": {
                "code": "NO_ACTIVE_FILING",
                "message": "No active 13F filing history is available for this manager.",
            },
            "quarters": [],
            "activity": [],
        }

    quarters: list[dict[str, Any]] = []
    active_hr_quarters: set[str] = set()
    for filing in filings:
        quarter = filing.report_quarter
        product_status = _filing_product_status(filing)
        caveats = _filing_caveats(filing)
        common: list[dict[str, Any]] = []
        options: list[dict[str, Any]] = []
        if quarter and filing.form_type in HR_FORM_TYPES and product_status == "available":
            holdings = (
                active_hr_holdings_query(session)
                .filter(Holding13F.filing_id == filing.id)
                .order_by(Holding13F.source_row_index, Holding13F.id)
                .all()
            )
            if holdings:
                common, options = _manager_position_payloads(
                    session,
                    manager_id=manager_id,
                    filing=filing,
                    holdings=holdings,
                )
                active_hr_quarters.add(quarter)

        reported_common_value = (
            int(filing.total_13f_common_value_usd)
            if filing.total_13f_common_value_usd is not None
            and filing.total_13f_common_value_usd > 0
            else _sum_all_known(item["value_usd"] for item in common)
        )
        weights = [item["portfolio_weight_pct"]["value"] for item in common]
        concentration_available = (
            filing.coverage_completeness == "complete"
            and bool(weights)
            and all(weight is not None for weight in weights)
        )

        def concentration(limit: int) -> float | None:
            if not concentration_available:
                return None
            return round(sum(float(weight) for weight in weights[:limit] if weight is not None), 6)

        quarters.append(
            {
                "quarter": quarter,
                "quarter_end_date": _iso(filing.quarter_end_date),
                "status": product_status,
                "filing": _filing_payload(filing),
                "caveats": caveats,
                "reported_common_value_usd": reported_common_value,
                "common_position_count": len(common) if common else None,
                "option_position_count": len(options) if options else 0,
                "concentration": {
                    "top_1_pct": concentration(1),
                    "top_5_pct": concentration(5),
                    "top_10_pct": concentration(10),
                },
                "top_holdings": common[:20],
            }
        )

    activity: list[dict[str, Any]] = []
    if active_hr_quarters:
        changes = (
            session.query(OwnershipChange13F, Stock)
            .outerjoin(Stock, Stock.id == OwnershipChange13F.stock_id)
            .filter(
                OwnershipChange13F.manager_id == manager_id,
                OwnershipChange13F.report_quarter.in_(sorted(active_hr_quarters)),
            )
            .order_by(
                OwnershipChange13F.quarter_end_date.desc().nullslast(),
                OwnershipChange13F.report_quarter.desc(),
                OwnershipChange13F.is_primary_signal_eligible.desc(),
                OwnershipChange13F.change_status,
                Stock.ticker.nullslast(),
                OwnershipChange13F.security_key,
            )
            .all()
        )
        denominators = _manager_quarter_common_denominators(
            session,
            manager_id=manager_id,
            quarters={
                quarter
                for change, _ in changes
                for quarter in (change.report_quarter, change.previous_report_quarter)
                if quarter
            },
        )
        activity = [
            _manager_change_payload(
                change,
                stock,
                current_denominator=denominators.get(change.report_quarter),
                previous_denominator=denominators.get(change.previous_report_quarter),
            )
            for change, stock in changes
        ]

    return {
        "status": "available",
        "manager": _manager_payload(manager, latest_filing=filings[0]),
        "reason": None,
        "quarters": quarters,
        "activity": activity,
    }


def build_user_manager_position_history(
    session: Session,
    manager_id: int,
    stock_id: int,
) -> dict[str, Any]:
    """Return the manager's quarter-by-quarter evidence for one linked stock."""
    manager = _require_manager(session, manager_id)
    stock = session.get(Stock, stock_id)
    if not stock:
        raise ValueError("Stock not found")

    filings = (
        session.query(Filing13F)
        .filter(
            Filing13F.manager_id == manager_id,
            Filing13F.is_active_for_manager_period.is_(True),
            Filing13F.form_type.in_(HR_FORM_TYPES),
        )
        .order_by(Filing13F.quarter_end_date.desc().nullslast(), Filing13F.report_quarter.desc().nullslast())
        .all()
    )
    filing_by_quarter = {
        filing.report_quarter: filing
        for filing in filings
        if filing.report_quarter
    }
    active_quarters = set(filing_by_quarter)
    holdings = (
        active_hr_holdings_query(session)
        .filter(
            Holding13F.manager_id == manager_id,
            Holding13F.stock_id == stock_id,
            Holding13F.put_call.is_(None),
        )
        .order_by(Holding13F.quarter_end_date.desc().nullslast(), Holding13F.source_row_index, Holding13F.id)
        .all()
    )
    holdings_by_quarter: dict[str, list[Holding13F]] = {}
    for holding in holdings:
        if holding.report_quarter in active_quarters:
            holdings_by_quarter.setdefault(holding.report_quarter, []).append(holding)

    changes = (
        session.query(OwnershipChange13F)
        .filter(
            OwnershipChange13F.manager_id == manager_id,
            OwnershipChange13F.stock_id == stock_id,
            OwnershipChange13F.report_quarter.in_(sorted(active_quarters)),
        )
        .order_by(OwnershipChange13F.quarter_end_date.desc().nullslast(), OwnershipChange13F.id.desc())
        .all()
        if active_quarters
        else []
    )
    change_by_quarter = {
        change.report_quarter: change
        for change in changes
        if change.report_quarter
    }
    denominator_quarters = {
        quarter
        for change in changes
        for quarter in (change.report_quarter, change.previous_report_quarter)
        if quarter
    } | set(holdings_by_quarter)
    denominators = _manager_quarter_common_denominators(
        session,
        manager_id=manager_id,
        quarters=denominator_quarters,
    )

    rows: list[dict[str, Any]] = []
    relevant_quarters = set(holdings_by_quarter) | set(change_by_quarter)
    for quarter in sorted(
        relevant_quarters,
        key=lambda item: (
            filing_by_quarter.get(item).quarter_end_date
            if filing_by_quarter.get(item) and filing_by_quarter[item].quarter_end_date
            else date.min,
            item,
        ),
        reverse=True,
    ):
        group = holdings_by_quarter.get(quarter, [])
        change = change_by_quarter.get(quarter)
        representative = max(group, key=lambda item: (item.value_usd or 0, item.id)) if group else None
        value_usd = _sum_all_known(item.value_usd for item in group) if group else 0
        shares = _sum_all_known(item.ssh_prnamt for item in group) if group else 0
        stored_weights = [item.portfolio_weight_pct for item in group]
        if group and all(weight is not None for weight in stored_weights):
            weight_pct = round(
                float(sum(Decimal(weight) for weight in stored_weights if weight is not None)),
                6,
            )
        elif group:
            weight_pct = _computed_weight_pct(value_usd, denominators.get(quarter))
        else:
            weight_pct = 0.0 if change and change.change_status == "exited_position" else None
        implied_report_price = (
            round(float(value_usd) / float(shares), 6)
            if representative
            and representative.ssh_prnamt_type == "SH"
            and value_usd is not None
            and shares
            and shares > 0
            else None
        )
        filing = filing_by_quarter.get(quarter)
        rows.append(
            {
                "quarter": quarter,
                "quarter_end_date": _iso(filing.quarter_end_date if filing else (change.quarter_end_date if change else None)),
                "shares": shares,
                "portfolio_weight_pct": weight_pct,
                "reported_value_usd": value_usd,
                "implied_report_price": implied_report_price,
                "activity": (
                    _manager_change_payload(
                        change,
                        stock,
                        current_denominator=denominators.get(change.report_quarter),
                        previous_denominator=denominators.get(change.previous_report_quarter),
                    )
                    if change
                    else None
                ),
                "caveats": _filing_caveats(filing) if filing else [],
            }
        )

    return {
        "status": "available" if rows else "unavailable",
        "manager": _manager_payload(manager, latest_filing=filings[0] if filings else None),
        "stock": {
            "id": stock.id,
            "ticker": stock.ticker,
            "exchange": stock.exchange,
            "company_name": stock.company_name,
        },
        "reason": (
            None
            if rows
            else {
                "code": "NO_POSITION_HISTORY",
                "message": "No active 13F holding history is available for this manager and stock.",
            }
        ),
        "items": rows,
    }


def build_user_stock_holders(
    session: Session,
    stock_id: int,
    quarter: str | None = None,
    *,
    limit: int = 10,
    manager_scope: str = "value",
) -> dict[str, Any]:
    if manager_scope not in MANAGER_SCOPES:
        raise ValueError(f"manager_scope must be one of: {', '.join(sorted(MANAGER_SCOPES))}")
    stock = session.get(Stock, stock_id)
    if not stock:
        raise ValueError("Stock not found")
    as_of_quarter = quarter or _latest_stock_holder_quarter(session, stock_id)
    if not as_of_quarter:
        return {
            "status": "unavailable",
            "stock_id": stock_id,
            "as_of_quarter": quarter,
            "manager_scope": manager_scope,
            "reason": {"code": "NO_ACTIVE_HOLDERS", "message": "No active 13F holders are available for this stock."},
            "direct_holder_count": 0,
            "value_manager_direct_count": 0,
            "featured_holder_count": 0,
            "top_holders": [],
            "recent_changes": [],
            "attribution_caveat_count": 0,
            "data_caveats": [],
        }

    base_query = active_hr_holdings_query(session).join(
        InstitutionManager,
        InstitutionManager.id == Holding13F.manager_id,
    ).filter(
        Holding13F.stock_id == stock_id,
        Holding13F.report_quarter == as_of_quarter,
        Holding13F.put_call.is_(None),
    )
    scoped_query = base_query
    if manager_scope == "value":
        scoped_query = scoped_query.filter(
            InstitutionManager.style_primary.in_(sorted(VALUE_STYLE_PRIMARY))
        )
    elif manager_scope == "value_plus_activist":
        scoped_query = scoped_query.filter(
            InstitutionManager.style_primary.in_(sorted({*VALUE_STYLE_PRIMARY, "activist"}))
        )
    direct_holdings = (
        scoped_query.filter(Holding13F.holding_attribution_status == "direct")
        .options(joinedload(Holding13F.filing).joinedload(Filing13F.manager))
        .order_by(Holding13F.portfolio_weight_pct.desc().nullslast(), Holding13F.value_usd.desc().nullslast())
        .all()
    )
    scoped_holdings = direct_holdings
    attribution_caveat_count = (
        scoped_query.filter(Holding13F.holding_attribution_status.in_(["shared", "unresolved"]))
        .with_entities(Holding13F.manager_id)
        .distinct()
        .count()
    )
    data_caveats = _stock_holder_data_caveats(direct_holdings)
    recent_changes = _stock_recent_changes(
        session,
        stock_id=stock_id,
        quarter=as_of_quarter,
        manager_scope=manager_scope,
    )
    top_holders = _stock_holder_position_payloads(session, scoped_holdings)
    return {
        "status": "available_with_caveat" if data_caveats or attribution_caveat_count else "available",
        "stock_id": stock_id,
        "ticker": stock.ticker,
        "exchange": stock.exchange,
        "company_name": stock.company_name,
        "as_of_quarter": as_of_quarter,
        "manager_scope": manager_scope,
        "direct_holder_count": len({holding.manager_id for holding in scoped_holdings}),
        "value_manager_direct_count": len(
            {
                holding.manager_id
                for holding in direct_holdings
                if holding.filing.manager.style_primary in VALUE_STYLE_PRIMARY
            }
        ),
        "featured_holder_count": len(
            {holding.manager_id for holding in scoped_holdings if holding.filing.manager.is_featured}
        ),
        "top_holders": top_holders[:limit],
        "recent_changes": recent_changes,
        "attribution_caveat_count": attribution_caveat_count,
        "data_caveats": data_caveats,
    }


def _unavailable_holding_changes(
    manager: InstitutionManager,
    quarter: str | None,
    *,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "manager": _manager_payload(manager),
        "quarter": quarter,
        "reason": {"code": code, "message": message},
        "items": None,
    }


def _require_manager(session: Session, manager_id: int) -> InstitutionManager:
    manager = session.get(InstitutionManager, manager_id)
    if not manager or manager.status != "active" or not manager.cik:
        raise ValueError("Manager not found")
    return manager


def _latest_stock_holder_quarter(session: Session, stock_id: int) -> str | None:
    row = (
        active_hr_holdings_query(session)
        .filter(
            Holding13F.stock_id == stock_id,
            Holding13F.put_call.is_(None),
            Holding13F.holding_attribution_status == "direct",
        )
        .order_by(Holding13F.quarter_end_date.desc().nullslast(), Holding13F.report_quarter.desc().nullslast())
        .first()
    )
    return row.report_quarter if row else None


def _latest_manager_change_quarter(session: Session, manager_id: int) -> str | None:
    row = (
        session.query(OwnershipChange13F.report_quarter)
        .filter(OwnershipChange13F.manager_id == manager_id)
        .order_by(OwnershipChange13F.quarter_end_date.desc().nullslast(), OwnershipChange13F.report_quarter.desc())
        .first()
    )
    return row[0] if row else None


def _active_filing(session: Session, manager_id: int, quarter: str | None = None) -> Filing13F | None:
    query = (
        session.query(Filing13F)
        .filter(Filing13F.manager_id == manager_id)
        .filter(Filing13F.is_active_for_manager_period.is_(True))
    )
    if quarter:
        query = query.filter(Filing13F.report_quarter == quarter)
    return query.order_by(Filing13F.quarter_end_date.desc().nullslast(), Filing13F.accepted_at.desc().nullslast()).first()


def _manager_payload(
    manager: InstitutionManager,
    *,
    latest_filing: Filing13F | None = None,
) -> dict[str, Any]:
    profile = CURATED_MANAGER_PROFILES.get(str(manager.cik or "").zfill(10), {})
    payload = {
        "id": manager.id,
        "canonical_name": manager.canonical_name,
        "display_name": manager.display_name or manager.canonical_name,
        "cik": manager.cik,
        "is_featured": manager.is_featured,
        "manager_type": manager.manager_type,
        "style_primary": manager.style_primary,
        "capital_structure": manager.capital_structure,
        "market_cap_focus": manager.market_cap_focus,
        "geo_focus": manager.geo_focus,
        "historical_turnover": manager.historical_turnover,
        "position_concentration_top10_pct": (
            float(manager.position_concentration_top10_pct)
            if manager.position_concentration_top10_pct is not None
            else None
        ),
        "ideology_tags": manager.ideology_tags or [],
        "classification_rationale": profile.get("classification_rationale"),
    }
    if latest_filing is not None:
        payload["latest_filing"] = {
            "quarter": latest_filing.report_quarter,
            "quarter_end_date": _iso(latest_filing.quarter_end_date),
            "form_type": latest_filing.form_type,
            "status": _filing_product_status(latest_filing),
            "accepted_at": latest_filing.accepted_at.isoformat() if latest_filing.accepted_at else None,
        }
    else:
        payload["latest_filing"] = None
    return payload


def _manager_in_scope(manager: InstitutionManager, manager_scope: str) -> bool:
    if manager_scope == "all":
        return True
    if manager.style_primary in VALUE_STYLE_PRIMARY:
        return True
    return manager_scope == "value_plus_activist" and manager.style_primary == "activist"


def _stock_holder_position_payloads(
    session: Session,
    holdings: list[Holding13F],
) -> list[dict[str, Any]]:
    """Collapse repeated raw rows into one holder position per manager.

    A combination filing or multiple security lots can produce more than one
    raw row for the same linked stock. Holder counts already use distinct
    managers; the displayed rows must follow the same economic-position unit.
    """
    by_manager: dict[int, list[Holding13F]] = {}
    for holding in holdings:
        by_manager.setdefault(int(holding.manager_id), []).append(holding)

    denominator_by_filing = _common_value_denominators(
        session,
        {holding.filing_id for holding in holdings},
    )
    payloads: list[dict[str, Any]] = []
    for group in by_manager.values():
        representative = max(group, key=lambda item: (item.value_usd or 0, item.id))
        streaks = _holding_streaks_for_manager(
            session,
            manager_id=int(representative.manager_id),
            stock_ids={int(representative.stock_id)},
            selected_quarter=representative.report_quarter,
        )
        values = [item.value_usd for item in group]
        shares = [item.ssh_prnamt for item in group]
        value_usd = sum(int(value) for value in values) if all(value is not None for value in values) else None
        share_total = sum(int(value) for value in shares) if all(value is not None for value in shares) else None
        stored_weights = [item.portfolio_weight_pct for item in group]
        if all(value is not None for value in stored_weights):
            weight_pct = float(sum(Decimal(value) for value in stored_weights if value is not None))
        else:
            denominator = denominator_by_filing.get(representative.filing_id)
            weight_pct = (
                round((value_usd / denominator) * 100, 6)
                if value_usd is not None and denominator and denominator > 0
                else None
            )
        payloads.append(
            {
                "manager": _manager_payload(representative.filing.manager),
                "holding_id": representative.id,
                "holding_ids": sorted(item.id for item in group),
                "constituent_row_count": len(group),
                "accession_number": representative.accession_number,
                "report_quarter": representative.report_quarter,
                "value_usd": value_usd,
                "ssh_prnamt": share_total,
                "portfolio_weight_pct": weight_pct,
                "holding_streak_quarters": streaks.get(
                    int(representative.stock_id), 0
                ),
                "confidence": {
                    "attribution_status": _single_or_mixed(
                        [item.holding_attribution_status for item in group]
                    ),
                    "cusip_mapping_status": _single_or_mixed(
                        [item.cusip_mapping_status for item in group]
                    ),
                },
            }
        )
    return sorted(
        payloads,
        key=lambda item: (
            item["portfolio_weight_pct"] is not None,
            item["portfolio_weight_pct"] or 0,
            item["value_usd"] or 0,
        ),
        reverse=True,
    )


def _manager_change_payload(
    change: OwnershipChange13F,
    stock: Stock | None,
    *,
    current_denominator: int | None = None,
    previous_denominator: int | None = None,
) -> dict[str, Any]:
    current_weight = (
        float(change.current_portfolio_weight_pct)
        if change.current_portfolio_weight_pct is not None
        else _computed_weight_pct(change.current_value_usd, current_denominator)
    )
    previous_weight = (
        float(change.previous_portfolio_weight_pct)
        if change.previous_portfolio_weight_pct is not None
        else _computed_weight_pct(change.previous_value_usd, previous_denominator)
    )
    return {
        "id": change.id,
        "stock": _stock_payload(stock, change),
        "report_quarter": change.report_quarter,
        "quarter_end_date": _iso(change.quarter_end_date),
        "previous_report_quarter": change.previous_report_quarter,
        "previous_quarter_end_date": _iso(change.previous_quarter_end_date),
        "change_status": change.change_status,
        "confidence_level": change.confidence_level,
        "is_primary_signal_eligible": change.is_primary_signal_eligible,
        "caveat_codes": change.caveat_codes or [],
        "unavailable_reason": change.unavailable_reason,
        "security_key": change.security_key,
        "position_type": change.position_type,
        "ssh_prnamt_type": change.ssh_prnamt_type,
        "put_call": change.put_call,
        "current_cusip": change.current_cusip,
        "previous_cusip": change.previous_cusip,
        "current_value_usd": change.current_value_usd,
        "previous_value_usd": change.previous_value_usd,
        "value_delta_usd": _display_delta(
            change.current_value_usd,
            change.previous_value_usd,
            change.value_delta_usd,
            change.change_status,
        ),
        "value_delta_pct": float(change.value_delta_pct) if change.value_delta_pct is not None else None,
        "current_shares": change.current_shares,
        "previous_shares": change.previous_shares,
        "share_delta": _display_delta(
            change.current_shares,
            change.previous_shares,
            change.share_delta,
            change.change_status,
        ),
        "share_change_pct": float(change.share_change_pct) if change.share_change_pct is not None else None,
        "current_portfolio_weight_pct": current_weight,
        "previous_portfolio_weight_pct": previous_weight,
        "portfolio_weight_delta_pct": (
            round(current_weight - previous_weight, 6)
            if current_weight is not None and previous_weight is not None
            else None
        ),
        "mapping_confidence": change.mapping_confidence,
        "attribution_status": change.attribution_status,
    }


def _stock_payload(stock: Stock | None, change: OwnershipChange13F) -> dict[str, Any]:
    return {
        "id": stock.id if stock else change.stock_id,
        "ticker": stock.ticker if stock else None,
        "exchange": stock.exchange if stock else None,
        "company_name": stock.company_name if stock else None,
    }


def _stock_recent_changes(
    session: Session,
    *,
    stock_id: int,
    quarter: str,
    manager_scope: str,
) -> list[dict[str, Any]]:
    rows = (
        session.query(OwnershipChange13F, InstitutionManager)
        .join(InstitutionManager, InstitutionManager.id == OwnershipChange13F.manager_id)
        .filter(
            OwnershipChange13F.stock_id == stock_id,
            OwnershipChange13F.report_quarter == quarter,
            OwnershipChange13F.is_primary_signal_eligible.is_(True),
            OwnershipChange13F.change_status.in_(RECENT_CHANGE_STATUSES),
        )
        .order_by(OwnershipChange13F.change_status, InstitutionManager.display_name, InstitutionManager.canonical_name)
        .all()
    )
    return [
        {
            "manager": _manager_payload(manager),
            "change_status": change.change_status,
            "confidence_level": change.confidence_level,
            "caveat_codes": change.caveat_codes or [],
            "current_value_usd": change.current_value_usd,
            "previous_value_usd": change.previous_value_usd,
            "value_delta_usd": _display_delta(
                change.current_value_usd,
                change.previous_value_usd,
                change.value_delta_usd,
                change.change_status,
            ),
            "current_shares": change.current_shares,
            "previous_shares": change.previous_shares,
            "share_delta": _display_delta(
                change.current_shares,
                change.previous_shares,
                change.share_delta,
                change.change_status,
            ),
        }
        for change, manager in rows
        if _manager_in_scope(manager, manager_scope)
    ]


def _display_delta(
    current: int | None,
    previous: int | None,
    explicit_delta: int | None,
    change_status: str,
) -> int | None:
    """Make one-sided new/exit evidence intuitive without mutating the read model."""
    if explicit_delta is not None:
        return int(explicit_delta)
    if change_status == "new_position" and current is not None:
        return int(current)
    if change_status == "exited_position" and previous is not None:
        return -int(previous)
    return None


def _stock_holder_data_caveats(holdings: list[Holding13F]) -> list[dict[str, str]]:
    by_code: dict[str, dict[str, str]] = {}
    for holding in holdings:
        for caveat in _filing_caveats(holding.filing):
            if caveat["code"] in {"COMBINATION_REPORT", "CONFIDENTIAL_TREATMENT", "FILING_WINDOW_OPEN", "SHARED_DISCRETION"}:
                by_code[caveat["code"]] = caveat
        # Holdings-derived shared discretion (sub-threshold, no cover-page list):
        # `_filing_caveats` can't see it from the filing alone.
        if holding.investment_discretion in ("DFND", "OTR"):
            by_code["SHARED_DISCRETION"] = {"code": "SHARED_DISCRETION", "message": SHARED_DISCRETION_CAVEAT}
    return list(by_code.values())


def _quarter_payload(filing: Filing13F) -> dict[str, Any]:
    return {
        "quarter": filing.report_quarter,
        "quarter_end_date": _iso(filing.quarter_end_date),
        "status": _filing_product_status(filing),
        "filing": _filing_payload(filing),
        "caveats": _filing_caveats(filing),
    }


def _filing_payload(filing: Filing13F) -> dict[str, Any]:
    return {
        "accession_number": filing.accession_number,
        "form_type": filing.form_type,
        "report_type": filing.report_type,
        "coverage_completeness": filing.coverage_completeness,
        "coverage_type": filing.coverage_type,
        "accepted_at": filing.accepted_at.isoformat() if filing.accepted_at else None,
        "official_filing_deadline": _iso(filing.official_filing_deadline),
        "parse_status": filing.parse_status,
        "amendment_status": filing.amendment_status,
    }


def _manager_position_payloads(
    session: Session,
    *,
    manager_id: int,
    filing: Filing13F,
    holdings: list[Holding13F],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stock_ids = {int(item.stock_id) for item in holdings if item.stock_id is not None}
    stocks_by_id = {
        stock.id: stock
        for stock in (
            session.query(Stock).filter(Stock.id.in_(stock_ids)).all()
            if stock_ids
            else []
        )
    }
    streaks = _holding_streaks_for_manager(
        session,
        manager_id=manager_id,
        stock_ids=stock_ids,
        selected_quarter=filing.report_quarter,
    )

    common_rows = [item for item in holdings if not item.put_call]
    denominator = (
        int(filing.total_13f_common_value_usd)
        if filing.total_13f_common_value_usd is not None
        and filing.total_13f_common_value_usd > 0
        else _sum_all_known(item.value_usd for item in common_rows)
    )

    grouped: dict[tuple[Any, ...], list[Holding13F]] = {}
    for holding in holdings:
        identity = (
            ("stock", int(holding.stock_id))
            if holding.stock_id is not None
            else ("cusip", holding.cusip)
        )
        grouped.setdefault(
            (*identity, holding.ssh_prnamt_type or "unknown", holding.put_call or "common"),
            [],
        ).append(holding)

    common: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []
    for group in grouped.values():
        representative = max(group, key=lambda item: (item.value_usd or 0, item.id))
        value_usd = _sum_all_known(item.value_usd for item in group)
        shares = _sum_all_known(item.ssh_prnamt for item in group)
        stored_weights = [item.portfolio_weight_pct for item in group]
        if representative.put_call:
            weight = {"value": None, "unavailable_reason": "OPTIONS_EXCLUDED_FROM_COMMON_WEIGHT"}
        elif filing.coverage_completeness != "complete":
            weight = {"value": None, "unavailable_reason": "PARTIAL_COVERAGE"}
        elif all(item is not None for item in stored_weights):
            weight = {
                "value": round(
                    float(sum(Decimal(item) for item in stored_weights if item is not None)),
                    6,
                ),
                "unavailable_reason": None,
            }
        elif value_usd is None:
            weight = {"value": None, "unavailable_reason": "VALUE_UNIT_UNAVAILABLE"}
        elif not denominator:
            weight = {"value": None, "unavailable_reason": "COMMON_PORTFOLIO_DENOMINATOR_UNAVAILABLE"}
        else:
            weight = {
                "value": round((value_usd / denominator) * 100, 6),
                "unavailable_reason": None,
            }
        stock = stocks_by_id.get(representative.stock_id)
        payload = {
            "id": representative.id,
            "holding_ids": sorted(item.id for item in group),
            "constituent_row_count": len(group),
            "stock_id": representative.stock_id,
            "stock": {
                "id": stock.id if stock else representative.stock_id,
                "ticker": stock.ticker if stock else None,
                "exchange": stock.exchange if stock else None,
                "company_name": stock.company_name if stock else None,
            },
            "accession_number": representative.accession_number,
            "report_quarter": representative.report_quarter,
            "cusip": representative.cusip,
            "cusips": sorted({item.cusip for item in group}),
            "issuer_name": representative.name_of_issuer or representative.issuer_name,
            "title_of_class": representative.title_of_class,
            "value_usd": value_usd,
            "ssh_prnamt": shares,
            "ssh_prnamt_type": representative.ssh_prnamt_type,
            "put_call": representative.put_call,
            "investment_discretion": _single_or_mixed(
                [item.investment_discretion for item in group]
            ),
            "cusip_mapping_status": _single_or_mixed(
                [item.cusip_mapping_status for item in group]
            ),
            "portfolio_weight_pct": weight,
            "holding_streak_quarters": (
                streaks.get(int(representative.stock_id), 0)
                if representative.stock_id is not None
                else None
            ),
        }
        (options if representative.put_call else common).append(payload)

    common.sort(key=lambda item: (item["value_usd"] is not None, item["value_usd"] or 0), reverse=True)
    options.sort(key=lambda item: (item["value_usd"] is not None, item["value_usd"] or 0), reverse=True)
    for rank, item in enumerate(common, start=1):
        item["position_rank"] = rank
    for rank, item in enumerate(options, start=1):
        item["position_rank"] = rank
    return common, options


def _attach_market_context(session: Session, positions: list[dict[str, Any]]) -> None:
    """Attach dated local-price context to manager positions in place.

    The implied report price is a quarter-end valuation (`value / shares`),
    never a transaction or cost-basis estimate. Market context is intentionally
    absent when the linked stock has no local price history.
    """
    stock_ids = {
        int(position["stock_id"])
        for position in positions
        if position.get("stock_id") is not None
    }
    through = compute_target_date(datetime.now(timezone.utc).astimezone(ET))
    prices_by_stock = read_canonical_eod_series(
        session,
        stock_ids=sorted(stock_ids),
        through=through,
        from_date=through - timedelta(days=370),
    )

    for position in positions:
        implied_report_price = position.get("implied_report_price")
        rows = prices_by_stock.get(int(position["stock_id"])) if position.get("stock_id") is not None else None
        if not rows:
            position["market_context"] = None
            continue
        latest = rows[0]
        cutoff = latest.price_date - timedelta(days=365)
        trailing = [row for row in rows if row.price_date >= cutoff]
        latest_price = float(latest.close)
        position["market_context"] = {
            "latest_price": latest_price,
            "latest_price_date": latest.price_date.isoformat(),
            "change_since_report_pct": (
                round(((latest_price / implied_report_price) - 1) * 100, 6)
                if implied_report_price and implied_report_price > 0
                else None
            ),
            "week_52_low": min(float(row.low) for row in trailing),
            "week_52_high": max(float(row.high) for row in trailing),
            "source": latest.source,
        }


def _attach_implied_report_prices(positions: list[dict[str, Any]]) -> None:
    """Attach filing-derived value ÷ shares without loading market data."""
    for position in positions:
        shares = position.get("ssh_prnamt")
        value = position.get("value_usd")
        position["implied_report_price"] = (
            round(float(value) / float(shares), 6)
            if position.get("ssh_prnamt_type") == "SH"
            and isinstance(value, int)
            and isinstance(shares, int)
            and shares > 0
            else None
        )


def _common_value_denominators(
    session: Session,
    filing_ids: set[int],
) -> dict[int, int]:
    if not filing_ids:
        return {}
    rows = (
        active_hr_holdings_query(session)
        .filter(Holding13F.filing_id.in_(filing_ids))
        .filter(Holding13F.put_call.is_(None))
        .all()
    )
    values: dict[int, list[int | None]] = {}
    for row in rows:
        values.setdefault(row.filing_id, []).append(row.value_usd)
    return {
        filing_id: total
        for filing_id, items in values.items()
        if (total := _sum_all_known(items)) is not None
    }


def _manager_quarter_common_denominators(
    session: Session,
    *,
    manager_id: int,
    quarters: set[str],
) -> dict[str, int]:
    if not quarters:
        return {}
    filings = (
        session.query(Filing13F)
        .filter(
            Filing13F.manager_id == manager_id,
            Filing13F.report_quarter.in_(sorted(quarters)),
            Filing13F.is_active_for_manager_period.is_(True),
            Filing13F.form_type.in_(HR_FORM_TYPES),
            Filing13F.coverage_completeness == "complete",
        )
        .all()
    )
    summed = _common_value_denominators(session, {filing.id for filing in filings})
    result: dict[str, int] = {}
    for filing in filings:
        denominator = (
            int(filing.total_13f_common_value_usd)
            if filing.total_13f_common_value_usd is not None
            and filing.total_13f_common_value_usd > 0
            else summed.get(filing.id)
        )
        if filing.report_quarter and denominator and denominator > 0:
            result[filing.report_quarter] = denominator
    return result


def _computed_weight_pct(value_usd: int | None, denominator: int | None) -> float | None:
    if value_usd is None or not denominator or denominator <= 0:
        return None
    return round((value_usd / denominator) * 100, 6)


def _holding_streaks_for_manager(
    session: Session,
    *,
    manager_id: int,
    stock_ids: set[int],
    selected_quarter: str | None,
) -> dict[int, int]:
    if not stock_ids or not selected_quarter:
        return {}
    rows = (
        active_hr_holdings_query(session)
        .filter(Holding13F.manager_id == manager_id)
        .filter(Holding13F.stock_id.in_(stock_ids))
        .filter(Holding13F.put_call.is_(None))
        .filter(Holding13F.holding_attribution_status == "direct")
        .with_entities(Holding13F.stock_id, Holding13F.report_quarter)
        .distinct()
        .all()
    )
    quarters_by_stock: dict[int, set[str]] = {}
    for stock_id, quarter in rows:
        if stock_id is not None and quarter:
            quarters_by_stock.setdefault(int(stock_id), set()).add(quarter)
    result: dict[int, int] = {}
    for stock_id, quarters in quarters_by_stock.items():
        streak = 0
        cursor = selected_quarter
        while cursor in quarters:
            streak += 1
            cursor = _previous_quarter(cursor)
        result[stock_id] = streak
    return result


def _previous_quarter(quarter: str) -> str:
    year_text, quarter_text = quarter.split("-Q", 1)
    year = int(year_text)
    number = int(quarter_text)
    return f"{year - 1}-Q4" if number == 1 else f"{year}-Q{number - 1}"


def _sum_all_known(values) -> int | None:
    items = list(values)
    if not items or any(item is None for item in items):
        return None
    return sum(int(item) for item in items)


def _single_or_mixed(values) -> str | None:
    distinct = {value for value in values if value is not None}
    if not distinct:
        return None
    if len(distinct) == 1:
        return next(iter(distinct))
    return "mixed"


def _filing_product_status(filing: Filing13F) -> str:
    if filing.form_type in NT_FORM_TYPES:
        return "reported_elsewhere"
    if filing.form_type in HR_FORM_TYPES and filing.parse_status == "succeeded":
        return "available"
    return "unavailable"


def _filing_caveats(filing: Filing13F) -> list[dict[str, str]]:
    caveats: list[dict[str, str]] = []
    if filing.form_type in NT_FORM_TYPES or filing.coverage_type == "notice_reported_elsewhere":
        caveats.append({"code": "NOTICE_REPORTED_ELSEWHERE", "message": NT_CAVEAT})
    if filing.coverage_completeness == "partial" or filing.coverage_type == "combination_partial":
        caveats.append({"code": "COMBINATION_REPORT", "message": COMBINATION_CAVEAT})
    # T3: a complete holdings_report can still aggregate positions across cover-page
    # included managers (e.g. Berkshire); surface that regardless of report_type so
    # its holdings are not shown as uncaveated independent sole-manager positions.
    if filing.other_managers_included:
        caveats.append({"code": "SHARED_DISCRETION", "message": SHARED_DISCRETION_CAVEAT})
    if filing.has_confidential_treatment or filing.confidential_treatment_status not in {None, "none"}:
        caveats.append({"code": "CONFIDENTIAL_TREATMENT", "message": CONFIDENTIAL_CAVEAT})
    if filing.official_filing_deadline and date.today() <= filing.official_filing_deadline:
        caveats.append({"code": "FILING_WINDOW_OPEN", "message": FILING_WINDOW_CAVEAT})
    return caveats


def _unavailable_holdings(
    manager: InstitutionManager,
    quarter: str | None,
    *,
    code: str,
    message: str,
    caveats: list[dict[str, str]] | None = None,
    filing: Filing13F | None = None,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "manager": _manager_payload(manager),
        "quarter": quarter,
        "reason": {"code": code, "message": message},
        "filing": _filing_payload(filing) if filing else None,
        "caveats": caveats or [],
        "common_holdings": None,
        "options": None,
    }


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None
