"""Safe user-facing 13F API response builders.

These builders preserve the PRD §7.3 query contract for Oracle's Lens:
product holdings are sourced only from active HR/HR-A filings with a current
parse run. 13F-NT and unavailable future features return explicit structured
reasons instead of empty holdings that could be misread as "no positions."
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from app.models.institutions import Filing13F, Holding13F, InstitutionManager, OwnershipChange13F
from app.models.stocks import Stock
from app.services.thirteenf_holdings_query import HR_FORM_TYPES, active_hr_holdings_query


NT_CAVEAT = "This manager filed a 13F Notice; its 13(f) holdings are reported by other manager(s)."
COMBINATION_CAVEAT = (
    "This is a 13F Combination Report. Some holdings are reported by other manager(s) "
    "and are not included here."
)
CONFIDENTIAL_CAVEAT = (
    "Some holdings may be omitted from this filing due to confidential treatment. "
    "Additional holdings may be disclosed in a future amendment."
)
FILING_WINDOW_CAVEAT = (
    "The filing window for this quarter may still be open. The snapshot can change until "
    "the official filing deadline passes."
)
VALUE_MANAGER_TYPES = {"fundamental_long", "activist"}
CONSENSUS_EXCLUDED_MANAGER_TYPES = {"index_like", "quant"}
RECENT_CHANGE_STATUSES = {"new_position", "increased", "reduced", "exited_position"}


def build_user_managers(session: Session) -> dict[str, Any]:
    managers = (
        session.query(InstitutionManager)
        .filter(InstitutionManager.status == "active")
        .filter(InstitutionManager.cik.isnot(None))
        .order_by(InstitutionManager.is_featured.desc(), InstitutionManager.display_name, InstitutionManager.canonical_name)
        .all()
    )
    return {"items": [_manager_payload(manager) for manager in managers]}


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


def build_user_manager_holdings(session: Session, manager_id: int, quarter: str | None = None) -> dict[str, Any]:
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
    if active_filing.form_type == "13F-NT":
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
    if not holdings:
        return _unavailable_holdings(
            manager,
            active_filing.report_quarter or quarter,
            code="NO_CURRENT_HOLDINGS",
            message="No current parsed holdings are available for this manager and quarter.",
            caveats=caveats,
            filing=active_filing,
        )

    common = [_holding_payload(item, active_filing) for item in holdings if not item.put_call]
    options = [_holding_payload(item, active_filing) for item in holdings if item.put_call]
    material_caveats = {item["code"] for item in caveats} & {"COMBINATION_REPORT", "CONFIDENTIAL_TREATMENT"}
    return {
        "status": "available_with_caveat" if material_caveats else "available",
        "manager": _manager_payload(manager),
        "quarter": active_filing.report_quarter or quarter,
        "quarter_end_date": _iso(active_filing.quarter_end_date),
        "filing": _filing_payload(active_filing),
        "caveats": caveats,
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

    items = [_manager_change_payload(change, stock) for change, stock in changes]
    has_caveats = any(
        item["caveat_codes"] or item["unavailable_reason"] or item["confidence_level"] in {"low_confidence", "unavailable"}
        for item in items
    )
    return {
        "status": "available_with_caveat" if has_caveats else "available",
        "manager": _manager_payload(manager),
        "quarter": as_of_quarter,
        "reason": None,
        "items": items,
    }


def build_user_stock_holders(
    session: Session,
    stock_id: int,
    quarter: str | None = None,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    stock = session.get(Stock, stock_id)
    if not stock:
        raise ValueError("Stock not found")
    as_of_quarter = quarter or _latest_stock_holder_quarter(session, stock_id)
    if not as_of_quarter:
        return {
            "status": "unavailable",
            "stock_id": stock_id,
            "as_of_quarter": quarter,
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
    direct_holdings = (
        base_query.filter(Holding13F.holding_attribution_status == "direct")
        .options(joinedload(Holding13F.filing).joinedload(Filing13F.manager))
        .order_by(Holding13F.portfolio_weight_pct.desc().nullslast(), Holding13F.value_usd.desc().nullslast())
        .all()
    )
    consensus_holdings = [
        holding for holding in direct_holdings if holding.filing.manager.manager_type not in CONSENSUS_EXCLUDED_MANAGER_TYPES
    ]
    attribution_caveat_count = (
        base_query.filter(Holding13F.holding_attribution_status.in_(["shared", "unresolved"]))
        .with_entities(Holding13F.manager_id)
        .distinct()
        .count()
    )
    data_caveats = _stock_holder_data_caveats(direct_holdings)
    recent_changes = _stock_recent_changes(session, stock_id=stock_id, quarter=as_of_quarter)
    return {
        "status": "available_with_caveat" if data_caveats or attribution_caveat_count else "available",
        "stock_id": stock_id,
        "ticker": stock.ticker,
        "exchange": stock.exchange,
        "company_name": stock.company_name,
        "as_of_quarter": as_of_quarter,
        "direct_holder_count": len({holding.manager_id for holding in consensus_holdings}),
        "value_manager_direct_count": len(
            {
                holding.manager_id
                for holding in consensus_holdings
                if holding.filing.manager.manager_type in VALUE_MANAGER_TYPES
            }
        ),
        "featured_holder_count": len(
            {holding.manager_id for holding in consensus_holdings if holding.filing.manager.is_featured}
        ),
        "top_holders": [_top_holder_payload(holding) for holding in consensus_holdings[:limit]],
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
        .order_by(OwnershipChange13F.quarter_end_date.desc(), OwnershipChange13F.report_quarter.desc())
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


def _manager_payload(manager: InstitutionManager) -> dict[str, Any]:
    return {
        "id": manager.id,
        "canonical_name": manager.canonical_name,
        "display_name": manager.display_name or manager.canonical_name,
        "cik": manager.cik,
        "is_featured": manager.is_featured,
        "manager_type": manager.manager_type,
    }


def _top_holder_payload(holding: Holding13F) -> dict[str, Any]:
    return {
        "manager": _manager_payload(holding.filing.manager),
        "holding_id": holding.id,
        "accession_number": holding.accession_number,
        "report_quarter": holding.report_quarter,
        "value_usd": holding.value_usd,
        "ssh_prnamt": holding.ssh_prnamt,
        "portfolio_weight_pct": float(holding.portfolio_weight_pct) if holding.portfolio_weight_pct is not None else None,
        "confidence": {
            "attribution_status": holding.holding_attribution_status,
            "cusip_mapping_status": holding.cusip_mapping_status,
        },
    }


def _manager_change_payload(change: OwnershipChange13F, stock: Stock | None) -> dict[str, Any]:
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
        "value_delta_usd": change.value_delta_usd,
        "value_delta_pct": float(change.value_delta_pct) if change.value_delta_pct is not None else None,
        "current_shares": change.current_shares,
        "previous_shares": change.previous_shares,
        "share_delta": change.share_delta,
        "share_change_pct": float(change.share_change_pct) if change.share_change_pct is not None else None,
        "current_portfolio_weight_pct": (
            float(change.current_portfolio_weight_pct)
            if change.current_portfolio_weight_pct is not None
            else None
        ),
        "previous_portfolio_weight_pct": (
            float(change.previous_portfolio_weight_pct)
            if change.previous_portfolio_weight_pct is not None
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


def _stock_recent_changes(session: Session, *, stock_id: int, quarter: str) -> list[dict[str, Any]]:
    rows = (
        session.query(OwnershipChange13F, InstitutionManager)
        .join(InstitutionManager, InstitutionManager.id == OwnershipChange13F.manager_id)
        .filter(
            OwnershipChange13F.stock_id == stock_id,
            OwnershipChange13F.report_quarter == quarter,
            OwnershipChange13F.is_primary_signal_eligible.is_(True),
            OwnershipChange13F.change_status.in_(RECENT_CHANGE_STATUSES),
            InstitutionManager.manager_type.notin_(CONSENSUS_EXCLUDED_MANAGER_TYPES),
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
            "current_shares": change.current_shares,
            "previous_shares": change.previous_shares,
            "share_delta": change.share_delta,
        }
        for change, manager in rows
    ]


def _stock_holder_data_caveats(holdings: list[Holding13F]) -> list[dict[str, str]]:
    by_code: dict[str, dict[str, str]] = {}
    for holding in holdings:
        for caveat in _filing_caveats(holding.filing):
            if caveat["code"] in {"COMBINATION_REPORT", "CONFIDENTIAL_TREATMENT", "FILING_WINDOW_OPEN"}:
                by_code[caveat["code"]] = caveat
    return list(by_code.values())


def _quarter_payload(filing: Filing13F) -> dict[str, Any]:
    if filing.form_type == "13F-NT":
        status = "reported_elsewhere"
    elif filing.form_type in HR_FORM_TYPES and filing.parse_status == "succeeded":
        status = "available"
    else:
        status = "unavailable"
    return {
        "quarter": filing.report_quarter,
        "quarter_end_date": _iso(filing.quarter_end_date),
        "status": status,
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


def _holding_payload(holding: Holding13F, filing: Filing13F) -> dict[str, Any]:
    is_option = bool(holding.put_call)
    return {
        "id": holding.id,
        "stock_id": holding.stock_id,
        "accession_number": holding.accession_number,
        "report_quarter": holding.report_quarter,
        "cusip": holding.cusip,
        "issuer_name": holding.name_of_issuer or holding.issuer_name,
        "title_of_class": holding.title_of_class,
        "value_usd": holding.value_usd,
        "ssh_prnamt": holding.ssh_prnamt,
        "ssh_prnamt_type": holding.ssh_prnamt_type,
        "put_call": holding.put_call,
        "investment_discretion": holding.investment_discretion,
        "cusip_mapping_status": holding.cusip_mapping_status,
        "portfolio_weight_pct": _portfolio_weight_payload(holding, filing, is_option=is_option),
    }


def _portfolio_weight_payload(holding: Holding13F, filing: Filing13F, *, is_option: bool) -> dict[str, Any]:
    if is_option:
        return {"value": None, "unavailable_reason": "OPTIONS_EXCLUDED_FROM_COMMON_WEIGHT"}
    if filing.coverage_completeness == "partial":
        return {"value": None, "unavailable_reason": "PARTIAL_COVERAGE"}
    if holding.portfolio_weight_pct is None:
        return {"value": None, "unavailable_reason": "NOT_COMPUTED"}
    return {"value": float(holding.portfolio_weight_pct), "unavailable_reason": None}


def _filing_caveats(filing: Filing13F) -> list[dict[str, str]]:
    caveats: list[dict[str, str]] = []
    if filing.form_type == "13F-NT" or filing.coverage_type == "notice_reported_elsewhere":
        caveats.append({"code": "NOTICE_REPORTED_ELSEWHERE", "message": NT_CAVEAT})
    if filing.coverage_completeness == "partial" or filing.coverage_type == "combination_partial":
        caveats.append({"code": "COMBINATION_REPORT", "message": COMBINATION_CAVEAT})
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
