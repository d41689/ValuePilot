from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import distinct
from sqlalchemy.orm import Session

from app.models.institutions import Filing13F, Holding13F, InstitutionManager, QualityFinding13F
from app.services.thirteenf_holdings_query import HR_FORM_TYPES, active_hr_holdings_query, nt_only_manager_ids


READY_COVERAGE_THRESHOLD = 0.80
READY_PARSE_SUCCESS_THRESHOLD = 0.95
READY_CUSIP_MAPPING_THRESHOLD = 0.70

# MVP3-09: cross-task QualityFinding rule_codes that the readiness service
# treats as warnings (never blockers). Sourced from the MVP3-06 corporate-action
# mapping service and the MVP3-07 historical backfill service respectively.
_RECOMPUTE_FINDING_RULE_CODE = "OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION"
_BACKFILL_FINDING_RULE_CODE = "HISTORICAL_BACKFILL_NEEDS_VALIDATION"
RECOMPUTE_WARNING_CODE = "OWNERSHIP_CHANGES_NEEDS_RECOMPUTE"
BACKFILL_WARNING_CODE = "HISTORICAL_BACKFILL_NEEDS_VALIDATION"


def build_readiness_summary(
    session: Session,
    *,
    today: date | None = None,
    nt_detection_supported: bool = True,
) -> dict[str, Any]:
    today = today or date.today()
    quarters = _active_filing_quarters(session)
    latest_closed_quarter = _latest_closed_quarter(session, quarters, today=today)
    quarter = latest_closed_quarter or (quarters[0] if quarters else None)

    metrics = _metrics_for_quarter(
        session,
        quarter,
        nt_detection_supported=nt_detection_supported,
    )
    quarter_lists = _quarter_lists(session, quarters)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if metrics["active_manager_count"] == 0:
        blockers.append(_message("NO_ACTIVE_MANAGERS", "No active managers with confirmed CIKs exist."))
    if quarters and latest_closed_quarter is None:
        blockers.append(_message("NO_CLOSED_FILING_WINDOW", "No quarter with an official filing deadline has closed yet."))
    if metrics["expected_filer_count"] and _ratio_value(metrics["manager_coverage_ratio"]) < READY_COVERAGE_THRESHOLD:
        blockers.append(_message("COVERAGE_BELOW_READY_THRESHOLD", "Expected filer coverage is below the ready threshold."))
    if _ratio_value(metrics["filing_parse_success_ratio"]) < READY_PARSE_SUCCESS_THRESHOLD:
        blockers.append(_message("PARSE_SUCCESS_BELOW_READY_THRESHOLD", "Filing parse success is below the ready threshold."))
    linked_common = metrics["linked_common_holding_ratio"]["value"]
    if linked_common is not None and linked_common < READY_CUSIP_MAPPING_THRESHOLD:
        blockers.append(_message("CUSIP_MAPPING_BELOW_READY_THRESHOLD", "Common share CUSIP mapping is below the ready threshold."))
    if metrics["linked_common_holding_ratio"]["unavailable_reason"]:
        blockers.append(_message(metrics["linked_common_holding_ratio"]["unavailable_reason"], "No active common holdings denominator exists."))

    if not nt_detection_supported:
        warnings.append(_message("NT_DETECTION_UNSUPPORTED", "13F-NT detection is not supported; coverage ratio is estimated."))
    if quarter_lists["confidential_quarters"]:
        warnings.append(_message("CONFIDENTIAL_TREATMENT", "Latest usable data includes confidential treatment caveats."))
    if quarter_lists["partial_coverage_quarters"]:
        warnings.append(_message("PARTIAL_COVERAGE", "Latest usable data includes combination or partial coverage filings."))
    if quarter_lists["amendment_pending_quarters"]:
        warnings.append(_message("AMENDMENTS_PENDING", "Amendments are pending for a usable quarter."))
    if quarter_lists["amendment_failed_quarters"]:
        warnings.append(_message("AMENDMENT_FAILED", "An amendment failed for a usable quarter."))
    # MVP3-09: cross-task findings. Warnings only — neither code makes a quarter
    # unavailable. The recompute warning signals that corporate-action mapping
    # changes (MVP3-06) have not been applied to ownership_changes yet, so the
    # quarter's change deltas may be stale. The backfill warning signals that
    # MVP3-07 historical backfill ingested filings the validation gate has not
    # cleared.
    if quarter_lists["ownership_changes_needs_recompute_quarters"]:
        warnings.append(
            _message(
                RECOMPUTE_WARNING_CODE,
                "Recent corporate-action mapping changes; ownership-change deltas may be stale until recompute completes.",
            )
        )
    if quarter_lists["historical_backfill_needs_validation_quarters"]:
        warnings.append(
            _message(
                BACKFILL_WARNING_CODE,
                "Backfilled filings awaiting validation gate.",
            )
        )

    readiness_level = _readiness_level(
        blockers=blockers,
        warnings=warnings,
        has_closed_quarter=latest_closed_quarter is not None,
        has_holdings=metrics["active_common_holding_count"] > 0 or metrics["active_holding_count"] > 0,
    )

    return {
        "feature": "oracles_lens",
        "readiness_level": readiness_level,
        "latest_usable_quarter": latest_closed_quarter,
        "as_of_quarter": latest_closed_quarter,
        "current_evaluated_quarter": quarter,
        "nt_detection_supported": nt_detection_supported,
        "metrics": metrics,
        "quarter_lists": quarter_lists,
        "blockers": blockers,
        "warnings": warnings,
        "unavailable_reasons": [item["code"] for item in blockers],
        "thresholds": {
            "manager_coverage_ready": READY_COVERAGE_THRESHOLD,
            "filing_parse_success_ready": READY_PARSE_SUCCESS_THRESHOLD,
            "cusip_mapping_ready": READY_CUSIP_MAPPING_THRESHOLD,
        },
    }


def _active_filing_quarters(session: Session) -> list[str]:
    rows = (
        session.query(Filing13F.report_quarter)
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .filter(Filing13F.report_quarter.isnot(None))
        .distinct()
        .all()
    )
    return sorted({row.report_quarter for row in rows if row.report_quarter}, reverse=True)


def _latest_closed_quarter(session: Session, quarters: list[str], *, today: date) -> str | None:
    for quarter in quarters:
        deadlines = [
            row.official_filing_deadline
            for row in (
                session.query(Filing13F.official_filing_deadline)
                .filter(Filing13F.report_quarter == quarter)
                .filter(Filing13F.is_active_for_manager_period.is_(True))
                .filter(Filing13F.official_filing_deadline.isnot(None))
                .all()
            )
        ]
        if deadlines and max(deadlines) <= today:
            return quarter
    return None


def _metrics_for_quarter(
    session: Session,
    quarter: str | None,
    *,
    nt_detection_supported: bool,
) -> dict[str, Any]:
    active_manager_count = (
        session.query(InstitutionManager)
        .filter(InstitutionManager.status == "active")
        .filter(InstitutionManager.cik.isnot(None))
        .count()
    )
    if quarter is None:
        return {
            "active_manager_count": active_manager_count,
            "expected_filer_count": 0,
            "filed_manager_count": 0,
            "nt_filer_count": 0,
            "active_filing_count": 0,
            "active_holding_count": 0,
            "active_common_holding_count": 0,
            "manager_coverage_ratio": _ratio(None, estimated=not nt_detection_supported, unavailable_reason="NO_EVALUATED_QUARTER"),
            "coverage_ratio": _ratio(None, estimated=not nt_detection_supported, unavailable_reason="NO_EVALUATED_QUARTER"),
            "filing_parse_success_ratio": _ratio(None, unavailable_reason="NO_EVALUATED_QUARTER"),
            "linked_common_holding_ratio": _ratio(None, unavailable_reason="NO_ACTIVE_COMMON_HOLDINGS"),
            "linked_all_holding_ratio": _ratio(None, unavailable_reason="NO_ACTIVE_HOLDINGS"),
            "cusip_mapping_ratio": _ratio(None, unavailable_reason="NO_ACTIVE_COMMON_HOLDINGS"),
        }

    nt_ids = nt_only_manager_ids(session, quarter)
    expected_filer_count = max(active_manager_count - len(nt_ids), 0)
    active_hr_filings = (
        session.query(Filing13F)
        .filter(Filing13F.report_quarter == quarter)
        .filter(Filing13F.form_type.in_(HR_FORM_TYPES))
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .all()
    )
    filed_manager_count = len({filing.manager_id for filing in active_hr_filings})
    parse_success_count = sum(1 for filing in active_hr_filings if filing.parse_status == "succeeded")

    holdings_query = active_hr_holdings_query(session).filter(Holding13F.report_quarter == quarter)
    active_holding_count = holdings_query.count()
    active_common_query = holdings_query.filter(Holding13F.put_call.is_(None))
    active_common_count = active_common_query.count()
    linked_common_count = active_common_query.filter(Holding13F.stock_id.isnot(None)).count()
    linked_all_count = holdings_query.filter(Holding13F.stock_id.isnot(None)).count()

    coverage_value = filed_manager_count / expected_filer_count if expected_filer_count else None
    parse_value = parse_success_count / len(active_hr_filings) if active_hr_filings else None
    linked_common_value = linked_common_count / active_common_count if active_common_count else None
    linked_all_value = linked_all_count / active_holding_count if active_holding_count else None

    return {
        "active_manager_count": active_manager_count,
        "expected_filer_count": expected_filer_count,
        "filed_manager_count": filed_manager_count,
        "nt_filer_count": len(nt_ids),
        "active_filing_count": len(active_hr_filings),
        "active_holding_count": active_holding_count,
        "active_common_holding_count": active_common_count,
        "manager_coverage_ratio": _ratio(
            coverage_value,
            estimated=not nt_detection_supported,
            unavailable_reason=None if expected_filer_count else "NO_EXPECTED_FILERS",
        ),
        "coverage_ratio": _ratio(
            coverage_value,
            estimated=not nt_detection_supported,
            unavailable_reason=None if expected_filer_count else "NO_EXPECTED_FILERS",
        ),
        "filing_parse_success_ratio": _ratio(
            parse_value,
            unavailable_reason=None if active_hr_filings else "NO_ACTIVE_HR_FILINGS",
        ),
        "linked_common_holding_ratio": _ratio(
            linked_common_value,
            unavailable_reason=None if active_common_count else "NO_ACTIVE_COMMON_HOLDINGS",
        ),
        "linked_all_holding_ratio": _ratio(
            linked_all_value,
            unavailable_reason=None if active_holding_count else "NO_ACTIVE_HOLDINGS",
        ),
        "cusip_mapping_ratio": _ratio(
            linked_common_value,
            unavailable_reason=None if active_common_count else "NO_ACTIVE_COMMON_HOLDINGS",
        ),
    }


def _quarter_lists(session: Session, quarters: list[str]) -> dict[str, list[str]]:
    return {
        "historical_coverage_quarters": quarters,
        "data_gap_quarters": _data_gap_quarters(session, quarters),
        "nt_quarters": _quarters_matching(session, Filing13F.coverage_type == "notice_reported_elsewhere"),
        "confidential_quarters": _quarters_matching(session, Filing13F.has_confidential_treatment.is_(True)),
        "partial_coverage_quarters": _quarters_matching(session, Filing13F.coverage_completeness == "partial"),
        "amendment_pending_quarters": _quarters_matching(session, Filing13F.amendment_status == "amendments_pending"),
        "amendment_failed_quarters": _quarters_matching(session, Filing13F.amendment_status == "amendment_failed"),
        # MVP3-09: read-only consumers of the MVP3-06 / MVP3-07 audit trail.
        "ownership_changes_needs_recompute_quarters": _quarters_with_open_finding(
            session, _RECOMPUTE_FINDING_RULE_CODE
        ),
        "historical_backfill_needs_validation_quarters": _quarters_with_open_finding(
            session, _BACKFILL_FINDING_RULE_CODE
        ),
    }


def _quarters_with_open_finding(session: Session, rule_code: str) -> list[str]:
    rows = (
        session.query(QualityFinding13F.quarter)
        .filter(QualityFinding13F.rule_code == rule_code)
        .filter(QualityFinding13F.status == "open")
        .filter(QualityFinding13F.quarter.isnot(None))
        .distinct()
        .all()
    )
    return sorted({row.quarter for row in rows if row.quarter})


def _quarters_matching(session: Session, condition: Any) -> list[str]:
    rows = (
        session.query(Filing13F.report_quarter)
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .filter(Filing13F.report_quarter.isnot(None))
        .filter(condition)
        .distinct()
        .all()
    )
    return sorted({row.report_quarter for row in rows if row.report_quarter})


def _data_gap_quarters(session: Session, quarters: list[str]) -> list[str]:
    gaps: list[str] = []
    active_manager_ids = {
        row.id
        for row in (
            session.query(InstitutionManager.id)
            .filter(InstitutionManager.status == "active")
            .filter(InstitutionManager.cik.isnot(None))
            .all()
        )
    }
    for quarter in quarters:
        expected_ids = active_manager_ids - nt_only_manager_ids(session, quarter)
        filed_ids = {
            row.manager_id
            for row in (
                session.query(distinct(Filing13F.manager_id).label("manager_id"))
                .filter(Filing13F.report_quarter == quarter)
                .filter(Filing13F.form_type.in_(HR_FORM_TYPES))
                .filter(Filing13F.is_active_for_manager_period.is_(True))
                .all()
            )
        }
        if expected_ids - filed_ids:
            gaps.append(quarter)
    return sorted(gaps)


def _readiness_level(
    *,
    blockers: list[dict[str, str]],
    warnings: list[dict[str, str]],
    has_closed_quarter: bool,
    has_holdings: bool,
) -> str:
    blocker_codes = {item["code"] for item in blockers}
    if "NO_ACTIVE_MANAGERS" in blocker_codes or (not has_holdings and has_closed_quarter):
        return "unavailable"
    if blockers:
        return "experimental"
    if warnings:
        return "usable_with_warning"
    return "ready"


def _ratio(value: float | None, *, estimated: bool = False, unavailable_reason: str | None = None) -> dict[str, Any]:
    return {
        "value": round(value, 4) if value is not None else None,
        "estimated": estimated,
        "unavailable_reason": unavailable_reason,
    }


def _ratio_value(ratio: dict[str, Any]) -> float:
    value = ratio.get("value")
    return float(value) if value is not None else 0.0


def _message(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
