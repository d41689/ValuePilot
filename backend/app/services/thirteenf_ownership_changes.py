"""MVP 2 ownership change precompute service.

This module writes the `ownership_changes` read model. It intentionally does
not expose API response shapes or stock-holder aggregation; those are later MVP
2 tasks that consume this table.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

from sqlalchemy.orm import Session

from app.models.institutions import Filing13F, Holding13F, OwnershipChange13F
from app.services.thirteenf_holdings_query import HR_FORM_TYPES, active_hr_holdings_query


DIRECT_ATTRIBUTION_STATUS = "direct"
MISSING_PRIOR_REASON = "missing_prior_quarter"
PRIOR_NT_REASON = "prior_quarter_13f_nt"
PRIOR_INCOMPLETE_REASON = "prior_quarter_incomplete"
CURRENT_INCOMPLETE_REASON = "current_quarter_incomplete"
MAPPING_BLOCK_REASON = "mapping_threshold_failed"
MAPPING_WARNING_CAVEAT = "mapping_below_ready_threshold"
MAPPING_BLOCK_THRESHOLD = 0.50
MAPPING_READY_THRESHOLD = 0.70


@dataclass(frozen=True)
class _HoldingKey:
    security_key: str
    ssh_prnamt_type: str
    position_type: str


@dataclass(frozen=True)
class _Pair:
    key: _HoldingKey
    current: Holding13F | None
    previous: Holding13F | None


def previous_report_quarter(report_quarter: str) -> str:
    """Return the immediately preceding quarter label for `YYYY-QN`."""
    year_part, quarter_part = report_quarter.split("-Q", 1)
    year = int(year_part)
    quarter = int(quarter_part)
    if quarter == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{quarter - 1}"


def compute_ownership_changes_for_manager_quarter(
    session: Session,
    *,
    manager_id: int,
    report_quarter: str,
) -> dict[str, int | str]:
    """Compute and replace ownership-change rows for one manager/quarter."""
    deleted = (
        session.query(OwnershipChange13F)
        .filter(
            OwnershipChange13F.manager_id == manager_id,
            OwnershipChange13F.report_quarter == report_quarter,
        )
        .delete(synchronize_session=False)
    )
    session.flush()

    current_filing = _active_filing(session, manager_id=manager_id, report_quarter=report_quarter)
    if not current_filing:
        return {"created": 0, "deleted": deleted, "status": "unavailable"}

    current_holdings = _direct_active_hr_holdings(
        session,
        manager_id=manager_id,
        report_quarter=report_quarter,
    )
    prior_quarter = previous_report_quarter(report_quarter)
    previous_filing = _active_filing(session, manager_id=manager_id, report_quarter=prior_quarter)

    mapping_ratio = _linked_common_mapping_ratio(current_holdings)
    unavailable_reason = _unavailable_reason(current_filing, previous_filing, mapping_ratio=mapping_ratio)
    if unavailable_reason:
        change_status = "unresolvable" if unavailable_reason == MAPPING_BLOCK_REASON else "no_prior_data"
        rows = [
            _build_change_row(
                manager_id=manager_id,
                report_quarter=report_quarter,
                quarter_end_date=current_filing.quarter_end_date,
                previous_report_quarter=prior_quarter,
                previous_quarter_end_date=previous_filing.quarter_end_date if previous_filing else None,
                current_filing=current_filing,
                previous_filing=previous_filing,
                current_holding=holding,
                previous_holding=None,
                change_status=change_status,
                confidence_level="unavailable",
                is_primary_signal_eligible=False,
                caveat_codes=[unavailable_reason],
                unavailable_reason=unavailable_reason,
            )
            for holding in current_holdings
        ]
        session.add_all(rows)
        session.flush()
        return {"created": len(rows), "deleted": deleted, "status": "succeeded"}

    previous_holdings = _direct_active_hr_holdings(
        session,
        manager_id=manager_id,
        report_quarter=prior_quarter,
    )
    rows = _compute_rows(
        manager_id=manager_id,
        report_quarter=report_quarter,
        previous_report_quarter=prior_quarter,
        current_filing=current_filing,
        previous_filing=previous_filing,
        current_holdings=current_holdings,
        previous_holdings=previous_holdings,
        mapping_warning=mapping_ratio is not None
        and MAPPING_BLOCK_THRESHOLD <= mapping_ratio < MAPPING_READY_THRESHOLD,
    )
    session.add_all(rows)
    session.flush()
    return {"created": len(rows), "deleted": deleted, "status": "succeeded"}


def _active_filing(session: Session, *, manager_id: int, report_quarter: str) -> Filing13F | None:
    return (
        session.query(Filing13F)
        .filter(
            Filing13F.manager_id == manager_id,
            Filing13F.report_quarter == report_quarter,
            Filing13F.is_active_for_manager_period.is_(True),
        )
        .one_or_none()
    )


def _direct_active_hr_holdings(
    session: Session,
    *,
    manager_id: int,
    report_quarter: str,
) -> list[Holding13F]:
    return (
        active_hr_holdings_query(session)
        .filter(
            Holding13F.manager_id == manager_id,
            Holding13F.report_quarter == report_quarter,
            Holding13F.holding_attribution_status == DIRECT_ATTRIBUTION_STATUS,
        )
        .all()
    )


def _unavailable_reason(
    current_filing: Filing13F,
    previous_filing: Filing13F | None,
    *,
    mapping_ratio: float | None,
) -> str | None:
    if current_filing.form_type not in HR_FORM_TYPES or current_filing.coverage_completeness != "complete":
        return CURRENT_INCOMPLETE_REASON
    if mapping_ratio is not None and mapping_ratio < MAPPING_BLOCK_THRESHOLD:
        return MAPPING_BLOCK_REASON
    if not previous_filing:
        return MISSING_PRIOR_REASON
    if previous_filing.form_type == "13F-NT":
        return PRIOR_NT_REASON
    if previous_filing.form_type not in HR_FORM_TYPES or previous_filing.coverage_completeness != "complete":
        return PRIOR_INCOMPLETE_REASON
    return None


def _compute_rows(
    *,
    manager_id: int,
    report_quarter: str,
    previous_report_quarter: str,
    current_filing: Filing13F,
    previous_filing: Filing13F,
    current_holdings: Sequence[Holding13F],
    previous_holdings: Sequence[Holding13F],
    mapping_warning: bool,
) -> list[OwnershipChange13F]:
    rows: list[OwnershipChange13F] = []
    for pair in _matched_pairs(current_holdings, previous_holdings):
        status, confidence, primary, caveats = _classify_change(current=pair.current, previous=pair.previous)
        if mapping_warning and status in {"new_position", "exited_position", "increased", "reduced"}:
            confidence = "low_confidence"
            primary = False
            caveats = [*caveats, MAPPING_WARNING_CAVEAT]
        confidence, primary, caveats = _adjust_for_filing_caveats(
            confidence=confidence,
            primary=primary,
            caveats=caveats,
            current_filing=current_filing,
            previous_filing=previous_filing,
        )
        rows.append(
            _build_change_row(
                manager_id=manager_id,
                report_quarter=report_quarter,
                quarter_end_date=current_filing.quarter_end_date,
                previous_report_quarter=previous_report_quarter,
                previous_quarter_end_date=previous_filing.quarter_end_date,
                current_filing=current_filing,
                previous_filing=previous_filing,
                current_holding=pair.current,
                previous_holding=pair.previous,
                key=pair.key,
                change_status=status,
                confidence_level=confidence,
                is_primary_signal_eligible=primary,
                caveat_codes=caveats,
                unavailable_reason=None,
            )
        )
    return rows


def _matched_pairs(current_holdings: Sequence[Holding13F], previous_holdings: Sequence[Holding13F]) -> list[_Pair]:
    """Match by stock identity first, then CUSIP for stragglers.

    PRD §7.4 requires CUSIP fallback when either side lacks `stock_id`.
    This prevents a holding that gained a stock mapping between quarters from
    becoming a false exited_position + new_position pair.
    """
    current_by_stock = {_stock_key(holding): holding for holding in current_holdings if holding.stock_id}
    previous_by_stock = {_stock_key(holding): holding for holding in previous_holdings if holding.stock_id}
    pairs: list[_Pair] = []
    matched_current_ids: set[int] = set()
    matched_previous_ids: set[int] = set()

    for key in sorted(current_by_stock.keys() & previous_by_stock.keys(), key=lambda item: item.security_key):
        current = current_by_stock[key]
        previous = previous_by_stock[key]
        pairs.append(_Pair(key=key, current=current, previous=previous))
        matched_current_ids.add(current.id)
        matched_previous_ids.add(previous.id)

    current_remaining = [holding for holding in current_holdings if holding.id not in matched_current_ids]
    previous_remaining = [holding for holding in previous_holdings if holding.id not in matched_previous_ids]
    current_by_cusip = {_cusip_key(holding): holding for holding in current_remaining}
    previous_by_cusip = {_cusip_key(holding): holding for holding in previous_remaining}

    for key in sorted(current_by_cusip.keys() | previous_by_cusip.keys(), key=lambda item: item.security_key):
        current = current_by_cusip.get(key)
        previous = previous_by_cusip.get(key)
        pairs.append(_Pair(key=_pair_key(current, previous), current=current, previous=previous))
    return pairs


def _classify_change(
    *,
    current: Holding13F | None,
    previous: Holding13F | None,
) -> tuple[str, str, bool, list[str]]:
    if current and previous and current.stock_id and current.stock_id == previous.stock_id and current.cusip != previous.cusip:
        return "cusip_changed", "medium_confidence", True, ["cusip_changed"]
    if current and not previous:
        return "new_position", "high_confidence", True, []
    if previous and not current:
        return "exited_position", "high_confidence", True, []
    current_shares = _shares(current)
    previous_shares = _shares(previous)
    if current_shares is not None and previous_shares is not None:
        if current_shares > previous_shares:
            return "increased", "high_confidence", True, []
        if current_shares < previous_shares:
            return "reduced", "high_confidence", True, []
    return "unchanged", "high_confidence", True, []


def _build_change_row(
    *,
    manager_id: int,
    report_quarter: str,
    quarter_end_date: date,
    previous_report_quarter: str | None,
    previous_quarter_end_date: date | None,
    current_filing: Filing13F | None,
    previous_filing: Filing13F | None,
    current_holding: Holding13F | None,
    previous_holding: Holding13F | None,
    change_status: str,
    confidence_level: str,
    is_primary_signal_eligible: bool,
    caveat_codes: list[str],
    unavailable_reason: str | None,
    key: _HoldingKey | None = None,
) -> OwnershipChange13F:
    representative = current_holding or previous_holding
    key = key or _holding_key(representative)
    current_value = _value_usd(current_holding)
    previous_value = _value_usd(previous_holding)
    current_shares = _shares(current_holding)
    previous_shares = _shares(previous_holding)
    return OwnershipChange13F(
        manager_id=manager_id,
        stock_id=representative.stock_id,
        report_quarter=report_quarter,
        quarter_end_date=quarter_end_date,
        previous_report_quarter=previous_report_quarter,
        previous_quarter_end_date=previous_quarter_end_date,
        current_filing_id=current_filing.id if current_filing else None,
        previous_filing_id=previous_filing.id if previous_filing else None,
        current_holding_id=current_holding.id if current_holding else None,
        previous_holding_id=previous_holding.id if previous_holding else None,
        current_parse_run_id=current_holding.parse_run_id if current_holding else None,
        previous_parse_run_id=previous_holding.parse_run_id if previous_holding else None,
        security_key=key.security_key,
        current_cusip=current_holding.cusip if current_holding else None,
        previous_cusip=previous_holding.cusip if previous_holding else None,
        ssh_prnamt_type=key.ssh_prnamt_type,
        put_call=_normalized_put_call(representative),
        position_type=key.position_type,
        change_status=change_status,
        confidence_level=confidence_level,
        is_primary_signal_eligible=is_primary_signal_eligible,
        caveat_codes=caveat_codes,
        unavailable_reason=unavailable_reason,
        current_value_usd=current_value,
        previous_value_usd=previous_value,
        value_delta_usd=_delta(current_value, previous_value),
        value_delta_pct=_delta_pct(current_value, previous_value),
        current_shares=current_shares,
        previous_shares=previous_shares,
        share_delta=_delta(current_shares, previous_shares),
        share_change_pct=_delta_pct(current_shares, previous_shares),
        current_portfolio_weight_pct=current_holding.portfolio_weight_pct if current_holding else None,
        previous_portfolio_weight_pct=previous_holding.portfolio_weight_pct if previous_holding else None,
        mapping_confidence="linked" if representative.stock_id else "unresolved",
        attribution_status=representative.holding_attribution_status,
        has_confidential_treatment_caveat=_has_confidential_caveat(current_filing)
        or _has_confidential_caveat(previous_filing),
        has_combination_report_caveat=_has_combination_caveat(current_filing)
        or _has_combination_caveat(previous_filing),
        has_pending_amendment_caveat=_has_pending_amendment_caveat(current_filing)
        or _has_pending_amendment_caveat(previous_filing),
    )


def _holding_key(holding: Holding13F) -> _HoldingKey:
    return _stock_key(holding) if holding.stock_id else _cusip_key(holding)


def _stock_key(holding: Holding13F) -> _HoldingKey:
    return _HoldingKey(
        security_key=f"stock:{holding.stock_id}",
        ssh_prnamt_type=holding.ssh_prnamt_type or "SH",
        position_type=_position_type(holding),
    )


def _cusip_key(holding: Holding13F) -> _HoldingKey:
    return _HoldingKey(
        security_key=f"cusip:{holding.cusip}",
        ssh_prnamt_type=holding.ssh_prnamt_type or "SH",
        position_type=_position_type(holding),
    )


def _pair_key(current: Holding13F | None, previous: Holding13F | None) -> _HoldingKey:
    representative = current or previous
    if current and previous and current.stock_id and previous.stock_id:
        return _stock_key(current)
    return _cusip_key(representative)


def _linked_common_mapping_ratio(holdings: Sequence[Holding13F]) -> float | None:
    common_holdings = [
        holding
        for holding in holdings
        if _position_type(holding) == "common" and holding.holding_attribution_status == DIRECT_ATTRIBUTION_STATUS
    ]
    if not common_holdings:
        return None
    linked = [holding for holding in common_holdings if holding.stock_id is not None]
    return len(linked) / len(common_holdings)


def _position_type(holding: Holding13F) -> str:
    put_call = _normalized_put_call(holding)
    if put_call == "PUT":
        return "put_option"
    if put_call == "CALL":
        return "call_option"
    return "common"


def _normalized_put_call(holding: Holding13F | None) -> str | None:
    if not holding or not holding.put_call:
        return None
    value = holding.put_call.upper()
    if value.startswith("P"):
        return "PUT"
    if value.startswith("C"):
        return "CALL"
    return value


def _shares(holding: Holding13F | None) -> int | None:
    if not holding:
        return None
    return holding.ssh_prnamt if holding.ssh_prnamt is not None else holding.shares


def _value_usd(holding: Holding13F | None) -> int | None:
    if not holding:
        return None
    return holding.value_usd


def _delta(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return current - previous


def _delta_pct(current: int | None, previous: int | None) -> Decimal | None:
    if current is None or previous in (None, 0):
        return None
    return Decimal(current - previous) / Decimal(abs(previous))


def _has_confidential_caveat(filing: Filing13F | None) -> bool:
    if not filing:
        return False
    return bool(filing.has_confidential_treatment) or filing.confidential_treatment_status not in (None, "none")


def _has_combination_caveat(filing: Filing13F | None) -> bool:
    if not filing:
        return False
    return filing.report_type == "combination_report" or filing.coverage_completeness == "partial"


def _has_pending_amendment_caveat(filing: Filing13F | None) -> bool:
    if not filing:
        return False
    return filing.amendment_status in {"amendments_pending", "amendment_failed"}


def _adjust_for_filing_caveats(
    *,
    confidence: str,
    primary: bool,
    caveats: list[str],
    current_filing: Filing13F | None,
    previous_filing: Filing13F | None,
) -> tuple[str, bool, list[str]]:
    adjusted = list(caveats)
    if _has_confidential_caveat(current_filing) or _has_confidential_caveat(previous_filing):
        adjusted.append("confidential_treatment")
        confidence = "medium_confidence" if confidence == "high_confidence" else confidence
        primary = False
    if _has_combination_caveat(current_filing) or _has_combination_caveat(previous_filing):
        adjusted.append("combination_report")
        confidence = "low_confidence"
        primary = False
    if _has_pending_amendment_caveat(current_filing) or _has_pending_amendment_caveat(previous_filing):
        adjusted.append("pending_amendment")
        confidence = "low_confidence"
        primary = False
    return confidence, primary, _dedupe_codes(adjusted)


def _dedupe_codes(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
