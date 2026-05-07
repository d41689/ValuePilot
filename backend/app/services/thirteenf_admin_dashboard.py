from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.institutions import Filing13F, Holding13F, InstitutionManager, JobRun, RawSourceDocument
from app.services.thirteenf_job_worker import list_worker_heartbeats


ACTIVE_JOB_STATUSES = {"queued", "running", "cancel_requested"}
READY_LINK_RATIO = 0.80
WARNING_LINK_RATIO = 0.50


@dataclass(frozen=True)
class QuarterWindow:
    label: str
    start: date
    end: date
    deadline: date


def current_quarter(today: date | None = None) -> QuarterWindow:
    today = today or date.today()
    qtr = (today.month - 1) // 3 + 1
    return quarter_window(f"{today.year}-Q{qtr}")


def quarter_window(quarter: str) -> QuarterWindow:
    year_text, qtr_text = quarter.upper().split("-Q", 1)
    year = int(year_text)
    qtr = int(qtr_text)
    start_month = (qtr - 1) * 3 + 1
    end_month = qtr * 3
    start = date(year, start_month, 1)
    end = date(year, end_month, calendar.monthrange(year, end_month)[1])
    return QuarterWindow(label=f"{year}-Q{qtr}", start=start, end=end, deadline=end + timedelta(days=45))


def quarter_label_for_date(value: date) -> str:
    return f"{value.year}-Q{((value.month - 1) // 3) + 1}"


def previous_quarter_label(quarter: str) -> str:
    window = quarter_window(quarter)
    qtr = int(quarter.split("-Q", 1)[1])
    if qtr == 1:
        return f"{window.start.year - 1}-Q4"
    return f"{window.start.year}-Q{qtr - 1}"


def latest_usable_quarter_label(today: date | None = None) -> str:
    today = today or date.today()
    label = current_quarter(today).label
    for _ in range(12):
        window = quarter_window(label)
        if today >= window.deadline:
            return label
        label = previous_quarter_label(label)
    return label


def build_admin_readiness(session: Session, *, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    current = current_quarter(today)
    latest_usable = latest_usable_quarter_label(today)
    current_summary = _quarter_summary(session, current.label, today=today)
    usable_summary = _quarter_summary(session, latest_usable, today=today)
    counts = _global_counts(session, latest_usable)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if counts["confirmed_managers"] == 0:
        blockers.append(
            {
                "code": "NO_CONFIRMED_MANAGER_CIK_WHITELIST",
                "message": "No confirmed manager / CIK whitelist exists.",
            }
        )
    if usable_summary["linked_holding_ratio"] is not None and usable_summary["linked_holding_ratio"] < READY_LINK_RATIO:
        warnings.append(
            {
                "code": "LOW_STOCK_LINK_COVERAGE",
                "message": f"{round(usable_summary['linked_holding_ratio'] * 100)}% of holdings are linked to stocks.",
            }
        )
    if current_summary["quarter_phase"] == "filing_window_open":
        warnings.append(
            {
                "code": "CURRENT_QUARTER_PARTIAL",
                "message": f"{current.label} is still inside the 13F filing window.",
            }
        )

    historical_depth = _historical_depth_quarters(session, latest_usable)
    capabilities = _historical_capabilities(historical_depth)
    amendment_status = usable_summary["amendment_status"]
    readiness_level = _readiness_level(
        confirmed_managers=counts["confirmed_managers"],
        holdings_count=usable_summary["holdings_count"],
        linked_holding_ratio=usable_summary["linked_holding_ratio"],
        amendment_status=amendment_status,
        historical_depth=historical_depth,
    )
    frontend_behavior = _frontend_behavior(readiness_level, current_summary)
    tasks = build_admin_tasks(session, today=today)

    return {
        "feature": "oracles_lens",
        "readiness_level": readiness_level,
        "frontend_behavior": frontend_behavior,
        "latest_usable_quarter": latest_usable,
        "current_quarter": {
            "quarter": current.label,
            "phase": current_summary["quarter_phase"],
            "health": current_summary["quarter_health"],
            "is_partial_expected": current_summary["quarter_phase"] == "filing_window_open",
            "filing_deadline": current.deadline.isoformat(),
        },
        "blockers": blockers,
        "warnings": warnings,
        "unavailable_reasons": [item["code"] for item in blockers],
        "counts": counts | {
            "filed_managers": usable_summary["filed_managers"],
            "filings": usable_summary["filings_count"],
            "holdings": usable_summary["holdings_count"],
            "linked_holdings_ratio": usable_summary["linked_holding_ratio"],
            "failed_filings": usable_summary["failed_filings"],
        },
        "historical_depth_quarters": historical_depth,
        "historical_depth_capabilities": capabilities,
        "amendment_status": amendment_status,
        "last_successful_job_at": _last_successful_job_at(session),
        "top_task": tasks[0] if tasks else None,
        "scheduler_enabled": settings.EDGAR_SCHEDULER_ENABLED,
    }


def build_consumer_readiness(session: Session, *, today: date | None = None) -> dict[str, Any]:
    readiness = build_admin_readiness(session, today=today)
    return {
        "readiness_level": readiness["readiness_level"],
        "frontend_behavior": readiness["frontend_behavior"],
        "latest_usable_quarter": readiness["latest_usable_quarter"],
        "current_quarter": readiness["current_quarter"],
        "warnings": readiness["warnings"],
        "historical_depth_quarters": readiness["historical_depth_quarters"],
        "historical_depth_capabilities": readiness["historical_depth_capabilities"],
        "amendment_status": readiness["amendment_status"],
    }


def build_status(session: Session, *, today: date | None = None) -> dict[str, Any]:
    readiness = build_admin_readiness(session, today=today)
    return {
        "scheduler_enabled": readiness["scheduler_enabled"],
        "readiness_level": readiness["readiness_level"],
        "frontend_behavior": readiness["frontend_behavior"],
        "latest_usable_quarter": readiness["latest_usable_quarter"],
        "current_quarter": readiness["current_quarter"],
        "top_task": readiness["top_task"],
    }


def build_quarters(session: Session, *, today: date | None = None, limit: int = 8) -> list[dict[str, Any]]:
    today = today or date.today()
    labels = _quarter_labels_for_display(session, today=today, limit=limit)
    return [_quarter_summary(session, label, today=today) for label in labels]


def build_admin_tasks(session: Session, *, today: date | None = None) -> list[dict[str, Any]]:
    today = today or date.today()
    latest = latest_usable_quarter_label(today)
    summary = _quarter_summary(session, latest, today=today)
    counts = _global_counts(session, latest)
    tasks: list[dict[str, Any]] = []

    if counts["confirmed_managers"] == 0:
        tasks.append(_task("P0", "NO_CONFIRMED_MANAGER_CIK_WHITELIST", "No confirmed manager / CIK whitelist", "Bootstrap whitelist, match CIK, review candidates"))
    if counts["candidate_managers"] > 0:
        tasks.append(_task("P1", "CIK_CANDIDATES_NEED_REVIEW", "CIK candidates need review", "Confirm or reject candidate"))
    if summary["form_idx_fetched"] and summary["filings_count"] == 0:
        tasks.append(_task("P1", "QUARTER_INDEX_FETCHED_NO_FILINGS", "Quarter index fetched but no filings", "Check whitelist and form parser"))
    if summary["failed_filings"] > 0:
        tasks.append(_task("P1", "FILING_PARSE_FAILURES", "Filing parse failures", "Retry failed filings or inspect EDGAR document"))
    if summary["amendment_status"] in {"amendments_pending", "amendment_failed"}:
        tasks.append(_task("P1", "AMENDMENT_PENDING_OR_FAILED", "Amendment pending or failed", "Run Reprocess amendment for each pending or failed 13F/A accession"))
    if summary["linked_holding_ratio"] is not None and summary["linked_holding_ratio"] < READY_LINK_RATIO:
        tasks.append(_task("P2", "LOW_STOCK_LINK_COVERAGE", "Low stock link coverage", "Run CUSIP enrichment, review unmatched CUSIPs"))
    historical_depth = _historical_depth_quarters(session, latest)
    if counts["confirmed_managers"] > 0 and historical_depth < 4:
        tasks.append(_task("P2", "HISTORICAL_COVERAGE_BELOW_TARGET", "Historical coverage below product target", "Run historical backfill and show feature-depth warning"))
    if counts["confirmed_managers"] > 0 and historical_depth < 8:
        tasks.append(_task("P3", "EXTENDED_BACKFILL_RECOMMENDED", "Extended backfill recommended", "Run historical backfill when rate-limit budget allows"))

    return sorted(tasks, key=lambda item: {"P0": 0, "P1": 1, "P2": 2, "P3": 3}[item["priority"]])


def build_managers(session: Session) -> list[dict[str, Any]]:
    managers = session.query(InstitutionManager).order_by(InstitutionManager.legal_name.asc()).all()
    return [
        {
            "id": item.id,
            "cik": item.cik,
            "legal_name": item.legal_name,
            "display_name": item.display_name,
            "match_status": item.match_status,
            "is_superinvestor": item.is_superinvestor,
            "dataroma_code": item.dataroma_code,
            "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
        }
        for item in managers
    ]


def confirm_manager_cik(session: Session, manager_id: int, *, cik: str | None = None, note: str | None = None) -> dict[str, Any]:
    manager = session.get(InstitutionManager, manager_id)
    if manager is None:
        raise ValueError("Manager not found")
    if cik:
        manager.cik = cik.zfill(10)
    if not manager.cik:
        raise ValueError("CIK is required to confirm a manager")
    manager.match_status = "confirmed"
    session.add(manager)
    session.commit()
    session.refresh(manager)
    return {"id": manager.id, "cik": manager.cik, "match_status": manager.match_status, "review_note": note}


def reject_manager_cik(session: Session, manager_id: int, *, note: str | None = None) -> dict[str, Any]:
    manager = session.get(InstitutionManager, manager_id)
    if manager is None:
        raise ValueError("Manager not found")
    manager.match_status = "rejected"
    session.add(manager)
    session.commit()
    session.refresh(manager)
    return {"id": manager.id, "cik": manager.cik, "match_status": manager.match_status, "review_note": note}


def list_jobs(session: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    jobs = session.query(JobRun).order_by(JobRun.created_at.desc()).limit(limit).all()
    return [_job_payload(job) for job in jobs]


def get_job(session: Session, job_id: int) -> dict[str, Any]:
    job = session.get(JobRun, job_id)
    if job is None:
        raise ValueError("Job not found")
    return _job_payload(job)


def list_workers(session: Session) -> list[dict[str, Any]]:
    return list_worker_heartbeats(session)


def trigger_job(session: Session, *, requested_by_user_id: int | None, payload: dict[str, Any]) -> dict[str, Any]:
    job_type = payload.get("job_type")
    if job_type not in _JOB_LOCK_BUILDERS:
        raise ValueError(f"Unsupported job_type: {job_type}")
    lock_key = _JOB_LOCK_BUILDERS[job_type](payload)
    active = (
        session.query(JobRun)
        .filter(JobRun.lock_key == lock_key)
        .filter(JobRun.status.in_(ACTIVE_JOB_STATUSES))
        .one_or_none()
    )
    if active:
        return {"conflict": True, "active_job_id": active.id, "lock_key": lock_key}
    if payload.get("dry_run"):
        return {
            "dry_run": True,
            "job_type": job_type,
            "lock_key": lock_key,
            "dedupe_key": lock_key,
            "input_json": payload,
        }

    job = JobRun(
        job_type=job_type,
        status="queued",
        requested_by_user_id=requested_by_user_id,
        trigger_source=payload.get("trigger_source") or "manual",
        dedupe_key=lock_key,
        lock_key=lock_key,
        quarter=payload.get("quarter"),
        input_json=payload,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return _job_payload(job)


def cancel_job(session: Session, job_id: int) -> dict[str, Any]:
    job = session.get(JobRun, job_id)
    if job is None:
        raise ValueError("Job not found")
    if job.status == "queued":
        job.status = "canceled"
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        session.refresh(job)
    elif job.status in {"running", "cancel_requested"}:
        job.status = "cancel_requested"
        session.add(job)
        session.commit()
        session.refresh(job)
    return _job_payload(job)


def execute_job_payload(session: Session, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _execute_job(session, job_type, payload)


def _quarter_summary(session: Session, quarter: str, *, today: date) -> dict[str, Any]:
    window = quarter_window(quarter)
    confirmed_managers = _confirmed_manager_count(session)
    filings = (
        session.query(Filing13F)
        .filter(Filing13F.period_of_report.between(window.start, window.end))
        .all()
    )
    latest_filing_ids = [filing.id for filing in filings if filing.is_latest_for_period]
    holdings_query = session.query(Holding13F)
    if latest_filing_ids:
        holdings_query = holdings_query.filter(Holding13F.filing_id.in_(latest_filing_ids))
    else:
        holdings_query = holdings_query.filter(False)
    holdings_count = holdings_query.count()
    linked_holdings_count = holdings_query.filter(Holding13F.stock_id.isnot(None)).count()
    filed_managers = len({filing.manager_id for filing in filings if filing.is_latest_for_period})
    failed_filings = _failed_filing_count(session, window)
    form_idx_fetched = _form_idx_fetched(session, window)
    linked_ratio = linked_holdings_count / holdings_count if holdings_count else None
    amendment_status = _amendment_status(session, filings)
    phase = _quarter_phase(window, today)
    health = _quarter_health(
        confirmed_managers=confirmed_managers,
        form_idx_fetched=form_idx_fetched,
        filings_count=len(filings),
        holdings_count=holdings_count,
        failed_filings=failed_filings,
        linked_ratio=linked_ratio,
        amendment_status=amendment_status,
        phase=phase,
    )
    return {
        "quarter": quarter,
        "quarter_start_date": window.start.isoformat(),
        "quarter_end_date": window.end.isoformat(),
        "filing_deadline": window.deadline.isoformat(),
        "quarter_phase": phase,
        "quarter_health": health,
        "tracked_managers": confirmed_managers,
        "filed_managers": filed_managers,
        "pending_managers": max(confirmed_managers - filed_managers, 0),
        "filings_count": len(filings),
        "form_idx_fetched": form_idx_fetched,
        "holdings_count": holdings_count,
        "linked_holdings_count": linked_holdings_count,
        "linked_holding_ratio": round(linked_ratio, 4) if linked_ratio is not None else None,
        "failed_filings": failed_filings,
        "amendment_status": amendment_status,
        "quality_status": "needs_review" if failed_filings or amendment_status in {"amendments_pending", "amendment_failed"} else "not_checked",
        "last_successful_job_at": _last_successful_job_at(session),
    }


def _quarter_phase(window: QuarterWindow, today: date) -> str:
    if today < window.end:
        return "pre_window"
    if today < window.deadline:
        return "filing_window_open"
    return "post_deadline"


def _quarter_health(*, confirmed_managers: int, form_idx_fetched: bool, filings_count: int, holdings_count: int, failed_filings: int, linked_ratio: float | None, amendment_status: str, phase: str) -> str:
    if confirmed_managers == 0:
        return "setup_required"
    if failed_filings:
        return "failed"
    if amendment_status in {"amendments_pending", "amendment_failed"}:
        return "needs_review"
    if not form_idx_fetched and filings_count == 0:
        return "not_started" if phase == "post_deadline" else "partial"
    if form_idx_fetched and filings_count == 0:
        return "index_fetched"
    if holdings_count == 0:
        return "partial"
    if linked_ratio is not None and linked_ratio < WARNING_LINK_RATIO:
        return "needs_review"
    if phase == "filing_window_open":
        return "partial"
    return "complete"


def _readiness_level(*, confirmed_managers: int, holdings_count: int, linked_holding_ratio: float | None, amendment_status: str, historical_depth: int) -> str:
    if confirmed_managers == 0 or holdings_count == 0:
        return "unavailable"
    if amendment_status in {"amendments_pending", "amendment_failed"}:
        return "experimental"
    if linked_holding_ratio is None or linked_holding_ratio < WARNING_LINK_RATIO:
        return "experimental"
    if historical_depth < 2:
        return "experimental"
    if linked_holding_ratio < READY_LINK_RATIO or historical_depth < 4:
        return "usable_with_warning"
    return "ready"


def _frontend_behavior(readiness_level: str, current_summary: dict[str, Any]) -> str:
    if readiness_level in {"unavailable", "experimental"}:
        return "show_setup_required"
    if readiness_level == "usable_with_warning":
        return "show_partial_warning" if current_summary["quarter_phase"] == "filing_window_open" else "show_with_warning"
    return "show_normally"


def _global_counts(session: Session, latest_quarter: str) -> dict[str, Any]:
    return {
        "managers": session.query(InstitutionManager).count(),
        "confirmed_managers": _confirmed_manager_count(session),
        "candidate_managers": session.query(InstitutionManager).filter(InstitutionManager.match_status == "candidate").count(),
        "raw_documents": session.query(RawSourceDocument).count(),
        "filings_total": session.query(Filing13F).count(),
        "holdings_total": session.query(Holding13F).count(),
        "latest_usable_quarter": latest_quarter,
    }


def _confirmed_manager_count(session: Session) -> int:
    return (
        session.query(InstitutionManager)
        .filter(InstitutionManager.match_status == "confirmed")
        .filter(InstitutionManager.cik.isnot(None))
        .count()
    )


def _form_idx_fetched(session: Session, window: QuarterWindow) -> bool:
    year = window.start.year
    qtr = int(window.label.split("-Q", 1)[1])
    return (
        session.query(RawSourceDocument)
        .filter(RawSourceDocument.source_system == "edgar")
        .filter(RawSourceDocument.document_type == "form_idx")
        .filter(RawSourceDocument.source_url.contains(f"/{year}/QTR{qtr}/"))
        .first()
        is not None
    )


def _failed_filing_count(session: Session, window: QuarterWindow) -> int:
    return (
        session.query(RawSourceDocument)
        .join(Filing13F, or_(Filing13F.raw_primary_doc_id == RawSourceDocument.id, Filing13F.raw_infotable_doc_id == RawSourceDocument.id))
        .filter(Filing13F.period_of_report.between(window.start, window.end))
        .filter(RawSourceDocument.parse_status == "failed")
        .count()
    )


def _amendment_status(session: Session, filings: list[Filing13F]) -> str:
    amendments = [filing for filing in filings if filing.form_type.endswith("/A") or filing.amends_accession_no]
    if not amendments:
        return "no_amendments"
    amendment_ids = [filing.id for filing in amendments]
    failed = (
        session.query(RawSourceDocument)
        .join(Filing13F, or_(Filing13F.raw_primary_doc_id == RawSourceDocument.id, Filing13F.raw_infotable_doc_id == RawSourceDocument.id))
        .filter(Filing13F.id.in_(amendment_ids))
        .filter(RawSourceDocument.parse_status == "failed")
        .count()
    )
    if failed:
        return "amendment_failed"
    for filing in amendments:
        if filing.is_latest_for_period:
            holdings_count = session.query(Holding13F).filter(Holding13F.filing_id == filing.id).count()
            if filing.raw_infotable_doc_id is None or holdings_count == 0:
                return "amendments_pending"
    return "amendments_applied"


def _historical_depth_quarters(session: Session, latest_quarter: str) -> int:
    depth = 0
    quarter = latest_quarter
    for _ in range(12):
        window = quarter_window(quarter)
        has_holdings = (
            session.query(Holding13F)
            .join(Filing13F, Filing13F.id == Holding13F.filing_id)
            .filter(Filing13F.period_of_report.between(window.start, window.end))
            .filter(Filing13F.is_latest_for_period.is_(True))
            .first()
            is not None
        )
        if not has_holdings:
            break
        depth += 1
        quarter = previous_quarter_label(quarter)
    return depth


def _historical_capabilities(depth: int) -> list[str]:
    if depth >= 8:
        return ["snapshot", "position_changes", "annual_trend", "holding_streak", "cyclical_patterns"]
    if depth >= 4:
        return ["snapshot", "position_changes", "annual_trend", "holding_streak"]
    if depth >= 2:
        return ["snapshot", "position_changes"]
    if depth >= 1:
        return ["snapshot"]
    return []


def _quarter_labels_for_display(session: Session, *, today: date, limit: int) -> list[str]:
    labels: list[str] = []
    current = current_quarter(today).label
    labels.append(current)
    quarter = current
    for _ in range(limit - 1):
        quarter = previous_quarter_label(quarter)
        labels.append(quarter)
    filing_quarters = [
        quarter_label_for_date(row[0])
        for row in session.query(Filing13F.period_of_report).distinct().all()
        if row[0]
    ]
    for label in filing_quarters:
        if label not in labels:
            labels.append(label)
    return labels[:limit]


def _last_successful_job_at(session: Session) -> str | None:
    job = (
        session.query(JobRun)
        .filter(JobRun.status.in_(["succeeded", "partial_success"]))
        .order_by(JobRun.finished_at.desc().nullslast(), JobRun.created_at.desc())
        .first()
    )
    value = job.finished_at or job.created_at if job else None
    return value.isoformat() if value else None


def _task(priority: str, code: str, title: str, recommended_action: str) -> dict[str, Any]:
    return {
        "priority": priority,
        "code": code,
        "title": title,
        "problem": title,
        "why_it_matters": "This affects whether 13F data is usable for Oracle's Lens.",
        "evidence": code,
        "recommended_action": recommended_action,
    }


def _job_payload(job: JobRun) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "requested_by_user_id": job.requested_by_user_id,
        "trigger_source": job.trigger_source,
        "dedupe_key": job.dedupe_key,
        "lock_key": job.lock_key,
        "quarter": job.quarter,
        "worker_id": job.worker_id,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "input_json": job.input_json,
        "summary_json": job.summary_json,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def _required(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not value:
        raise ValueError(f"{key} is required")
    return str(value)


_JOB_LOCK_BUILDERS = {
    "fetch_quarter_index": lambda payload: f"fetch_quarter_index:{_required(payload, 'quarter')}",
    "ingest_holdings": lambda payload: f"ingest_holdings:{_required(payload, 'quarter')}",
    "ingest_accession": lambda payload: f"ingest_accession:{_required(payload, 'accession_no')}",
    "backfill_quarters": lambda payload: f"backfill_quarters:{payload.get('start_quarter') or 'latest'}:{_required(payload, 'quarters')}",
    "enrich_cusip": lambda payload: f"enrich_cusip:{_required(payload, 'quarter')}",
    "bootstrap_stocks": lambda payload: "bootstrap_stocks",
    "enrich_stocks_edgar": lambda payload: "enrich_stocks_edgar",
    "bootstrap_whitelist": lambda payload: "bootstrap_whitelist",
    "match_cik": lambda payload: "match_cik",
    "quality_check": lambda payload: f"quality_check:{_required(payload, 'quarter')}",
    "reprocess_amendment": lambda payload: f"reprocess_amendment:{_required(payload, 'accession_no')}",
}


def _execute_job(session: Session, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if job_type == "quality_check":
        from app.services.edgar_quality import run_quality_checks

        report = run_quality_checks(session, payload.get("quarter"))
        return {
            "status": "failed" if report.errors else "succeeded",
            "quality_errors": len(report.errors),
            "quality_warnings": len(report.warnings),
            "issues": [
                {
                    "check": issue.check,
                    "severity": issue.severity,
                    "accession_no": issue.accession_no,
                    "detail": issue.detail,
                }
                for issue in report.issues[:50]
            ],
        }
    if job_type == "bootstrap_whitelist":
        from app.services.edgar_ingestion import bootstrap_whitelist

        return {"managers_seen": bootstrap_whitelist(session), "status": "succeeded"}
    if job_type == "match_cik":
        from app.services.edgar_ingestion import match_cik_candidates

        return {"managers_confirmed_or_candidate": match_cik_candidates(session), "status": "succeeded"}
    if job_type == "fetch_quarter_index":
        from app.services.edgar_ingestion import ingest_quarter_index

        quarter = _required(payload, "quarter")
        return {"quarter": quarter, "filings_inserted": ingest_quarter_index(session, quarter), "status": "succeeded"}
    if job_type == "backfill_quarters":
        from app.services.edgar_ingestion import backfill_quarters

        results = backfill_quarters(session, int(_required(payload, "quarters")))
        return {
            "quarters": results,
            "filings_inserted": sum(value for value in results.values() if value > 0),
            "status": "partial_success" if any(value < 0 for value in results.values()) else "succeeded",
        }
    if job_type in {"ingest_holdings", "ingest_accession", "reprocess_amendment"}:
        return _execute_ingest_job(session, job_type, payload)
    if job_type == "enrich_cusip":
        from app.services.cusip_enrichment import enrich_from_dataroma

        return {"mappings_created": enrich_from_dataroma(session), "status": "succeeded"}
    if job_type == "bootstrap_stocks":
        from app.services.cusip_enrichment import bootstrap_stocks_from_cusip_map, backfill_stock_ids

        created = bootstrap_stocks_from_cusip_map(session)
        linked = backfill_stock_ids(session)
        return {"new_stocks": created, "holdings_linked": linked, "status": "succeeded"}
    if job_type == "enrich_stocks_edgar":
        from app.services.cusip_enrichment import enrich_stocks_from_edgar_tickers

        result = enrich_stocks_from_edgar_tickers(session)
        return {**result, "status": "succeeded"}
    raise ValueError(f"Unsupported job_type: {job_type}")


def _execute_ingest_job(session: Session, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.edgar_ingestion import ingest_filing_holdings

    if job_type in {"ingest_accession", "reprocess_amendment"}:
        accession_no = _required(payload, "accession_no")
        filing = session.query(Filing13F).filter(Filing13F.accession_no == accession_no).one_or_none()
        if filing is None:
            raise ValueError(f"Filing {accession_no} not found")
        count = ingest_filing_holdings(
            session,
            filing,
            force_refresh=job_type == "reprocess_amendment",
            replace_holdings=True,
        )
        return {"filings_processed": 1, "holdings_inserted": count, "status": "succeeded"}

    quarter = _required(payload, "quarter")
    window = quarter_window(quarter)
    filings = (
        session.query(Filing13F)
        .filter(Filing13F.period_of_report.between(window.start, window.end))
        .filter(Filing13F.raw_infotable_doc_id.is_(None))
        .order_by(Filing13F.filed_at.asc(), Filing13F.accession_no.asc())
        .all()
    )
    holdings_inserted = 0
    failures: list[dict[str, str]] = []
    for filing in filings:
        try:
            holdings_inserted += ingest_filing_holdings(session, filing)
            session.commit()
        except Exception as exc:
            session.rollback()
            failures.append({"accession_no": filing.accession_no, "error": str(exc)})
    return {
        "filings_processed": len(filings),
        "filings_failed": len(failures),
        "failed_accessions": failures,
        "holdings_inserted": holdings_inserted,
        "status": "partial_success" if failures else "succeeded",
    }
