from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManagerCikReviewEvent,
    InstitutionManager,
    JobRun,
    JobWorkerHeartbeat,
    QualityReport13F,
    RawSourceDocument,
)
from app.services.edgar_quality import persist_quality_report, run_quality_checks
from app.services.thirteenf_job_worker import list_worker_heartbeats


ACTIVE_JOB_STATUSES = {"queued", "running", "cancel_requested"}
READY_LINK_RATIO = 0.80
WARNING_LINK_RATIO = 0.50
STUCK_QUEUED_JOB_AFTER_SECONDS = 10 * 60


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
    if not settings.EDGAR_SCHEDULER_ENABLED:
        blockers.append(
            {
                "code": "EDGAR_SCHEDULER_DISABLED",
                "message": "EDGAR scheduler is disabled.",
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
            "linked_holding_unavailable_reason": usable_summary["linked_holding_unavailable_reason"],
            "failed_filings": usable_summary["failed_filings"],
        },
        "historical_depth_quarters": historical_depth,
        "historical_depth_capabilities": capabilities,
        "setup_checklist": _setup_checklist(
            scheduler_enabled=settings.EDGAR_SCHEDULER_ENABLED,
            counts=counts,
            usable_summary=usable_summary,
            historical_depth=historical_depth,
        ),
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


def get_quarter_detail(session: Session, quarter: str, *, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    window = quarter_window(quarter)
    filings = (
        session.query(Filing13F)
        .filter(Filing13F.period_of_report.between(window.start, window.end))
        .order_by(Filing13F.filed_at.asc(), Filing13F.accession_no.asc())
        .all()
    )
    filing_rows = [_filing_detail_payload(session, filing) for filing in filings]
    pending_filings = [row for row in filing_rows if row["status"] == "pending"]
    failed_filings = [row for row in filing_rows if row["status"] == "failed"]
    amendments = [
        _amendment_payload(session, filing)
        for filing in filings
        if filing.form_type.endswith("/A") or filing.amends_accession_no
    ]
    quality_report = _latest_quality_report(session, quarter)
    return {
        "summary": _quarter_summary(session, quarter, today=today),
        "filings": filing_rows,
        "pending_filings": pending_filings,
        "failed_filings": failed_filings,
        "amendments": amendments,
        "quality_report": _quality_report_payload(quality_report) if quality_report else None,
        "suggested_actions": _quarter_suggested_actions(
            quarter=quarter,
            pending_filings=pending_filings,
            failed_filings=failed_filings,
            amendments=amendments,
            quality_report=quality_report,
        ),
    }


def build_quality_reports(session: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    reports = session.query(QualityReport13F).order_by(QualityReport13F.checked_at.desc()).limit(limit).all()
    return [_quality_report_payload(report) for report in reports]


def build_amendments(session: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    amendments = (
        session.query(Filing13F)
        .filter(or_(Filing13F.form_type.endswith("/A"), Filing13F.amends_accession_no.isnot(None)))
        .order_by(Filing13F.filed_at.desc(), Filing13F.accession_no.desc())
        .limit(limit)
        .all()
    )
    payloads = [_amendment_payload(session, filing) for filing in amendments]
    priority = {"failed": 0, "pending": 1, "applied": 2, "superseded": 3}
    return sorted(payloads, key=lambda item: (priority.get(item["status"], 9), item["filed_at"] or ""), reverse=False)


def get_amendment(session: Session, accession_no: str) -> dict[str, Any]:
    filing = (
        session.query(Filing13F)
        .filter(Filing13F.accession_no == accession_no)
        .filter(or_(Filing13F.form_type.endswith("/A"), Filing13F.amends_accession_no.isnot(None)))
        .one_or_none()
    )
    if filing is None:
        raise ValueError("Amendment not found")
    return _amendment_payload(session, filing)


def get_quality_report_for_quarter(session: Session, quarter: str) -> dict[str, Any]:
    report = _latest_quality_report(session, quarter)
    if report is None:
        raise ValueError("Quality report not found")
    return _quality_report_payload(report)


def build_admin_tasks(session: Session, *, today: date | None = None) -> list[dict[str, Any]]:
    today = today or date.today()
    latest = latest_usable_quarter_label(today)
    summary = _quarter_summary(session, latest, today=today)
    counts = _global_counts(session, latest)
    tasks: list[dict[str, Any]] = []

    if not settings.EDGAR_SCHEDULER_ENABLED:
        tasks.append(_task("P0", "EDGAR_SCHEDULER_DISABLED", "EDGAR scheduler disabled", "Enable EDGAR_SCHEDULER_ENABLED and redeploy the API service"))
    if counts["confirmed_managers"] == 0:
        tasks.append(_task("P0", "NO_CONFIRMED_MANAGER_CIK_WHITELIST", "No confirmed manager / CIK whitelist", "Bootstrap whitelist, match CIK, review candidates"))
    if counts["candidate_managers"] > 0:
        tasks.append(_task("P1", "CIK_CANDIDATES_NEED_REVIEW", "CIK candidates need review", "Confirm or reject candidate"))
    tasks.extend(_revoked_cik_repair_tasks(session))
    tasks.extend(_recent_job_alert_tasks(session))
    tasks.extend(_worker_operational_tasks(session))
    if summary["form_idx_fetched"] and summary["filings_count"] == 0:
        tasks.append(_task("P1", "QUARTER_INDEX_FETCHED_NO_FILINGS", "Quarter index fetched but no filings", "Check whitelist and form parser"))
    if summary["failed_filings"] > 0:
        tasks.append(_task("P1", "FILING_PARSE_FAILURES", "Filing parse failures", "Retry failed filings or inspect EDGAR document"))
    if summary["amendment_status"] in {"amendments_pending", "amendment_failed"}:
        tasks.append(_task("P1", "AMENDMENT_PENDING_OR_FAILED", "Amendment pending or failed", "Run Reprocess amendment for each pending or failed 13F/A accession"))
    if summary["linked_holding_ratio"] is not None and summary["linked_holding_ratio"] < READY_LINK_RATIO:
        tasks.append(_task("P2", "LOW_STOCK_LINK_COVERAGE", "Low stock link coverage", "Run CUSIP enrichment, review unmatched CUSIPs"))
    if summary["quality_status"] == "failed":
        tasks.append(_task("P1", "QUALITY_ERRORS", "Quality errors", "Inspect latest quality report and rerun quality check after fixes"))
    if summary["quality_status"] == "warning":
        tasks.append(_task("P2", "QUALITY_WARNINGS", "Quality warnings", "Review quality warnings and accept or fix"))
    historical_depth = _historical_depth_quarters(session, latest)
    if counts["confirmed_managers"] > 0 and historical_depth < 4:
        tasks.append(_task("P2", "HISTORICAL_COVERAGE_BELOW_TARGET", "Historical coverage below product target", "Run historical backfill and show feature-depth warning"))
    if counts["confirmed_managers"] > 0 and historical_depth < 8:
        tasks.append(_task("P3", "EXTENDED_BACKFILL_RECOMMENDED", "Extended backfill recommended", "Run historical backfill when rate-limit budget allows"))

    return sorted(tasks, key=lambda item: {"P0": 0, "P1": 1, "P2": 2, "P3": 3}[item["priority"]])


def build_managers(session: Session) -> list[dict[str, Any]]:
    managers = session.query(InstitutionManager).order_by(InstitutionManager.legal_name.asc()).all()
    return [_manager_payload(item) for item in managers]


def list_manager_cik_review_events(session: Session, manager_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    manager = session.get(InstitutionManager, manager_id)
    if manager is None:
        raise ValueError("Manager not found")
    events = (
        session.query(InstitutionManagerCikReviewEvent)
        .filter(InstitutionManagerCikReviewEvent.manager_id == manager_id)
        .order_by(InstitutionManagerCikReviewEvent.created_at.desc(), InstitutionManagerCikReviewEvent.id.desc())
        .limit(limit)
        .all()
    )
    return [_cik_review_event_payload(event) for event in events]


def confirm_manager_cik(
    session: Session,
    manager_id: int,
    *,
    cik: str | None = None,
    note: str | None = None,
    reviewed_by_user_id: int | None = None,
) -> dict[str, Any]:
    manager = session.get(InstitutionManager, manager_id)
    if manager is None:
        raise ValueError("Manager not found")
    old_cik = manager.cik
    old_status = manager.match_status
    confirmed_cik = cik or manager.candidate_cik
    if confirmed_cik:
        manager.cik = confirmed_cik.zfill(10)
    if not manager.cik:
        raise ValueError("CIK is required to confirm a manager")
    if manager.candidate_legal_name:
        manager.legal_name = manager.candidate_legal_name
    manager.match_status = "confirmed"
    manager.reviewed_by_user_id = reviewed_by_user_id
    manager.reviewed_at = datetime.now(timezone.utc)
    manager.review_note = note
    session.add(manager)
    session.flush()
    session.add(
        _cik_review_event(
            manager,
            event_type="confirm_candidate_cik",
            old_cik=old_cik,
            old_match_status=old_status,
            reviewed_by_user_id=reviewed_by_user_id,
            note=note,
            evidence_json=_manager_candidate_evidence(manager),
        )
    )
    session.commit()
    session.refresh(manager)
    return _manager_payload(manager)


def reject_manager_cik(
    session: Session,
    manager_id: int,
    *,
    note: str | None = None,
    reviewed_by_user_id: int | None = None,
) -> dict[str, Any]:
    manager = session.get(InstitutionManager, manager_id)
    if manager is None:
        raise ValueError("Manager not found")
    old_cik = manager.cik
    old_status = manager.match_status
    prior = list(manager.prior_rejected_candidates or [])
    if manager.candidate_cik or manager.candidate_legal_name:
        prior.append(
            {
                "cik": manager.candidate_cik,
                "legal_name": manager.candidate_legal_name,
                "similarity_score": manager.candidate_similarity_score,
                "source": manager.candidate_source,
                "evidence_url": manager.candidate_evidence_url,
                "review_note": note,
                "reviewed_by_user_id": reviewed_by_user_id,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    manager.match_status = "rejected"
    manager.reviewed_by_user_id = reviewed_by_user_id
    manager.reviewed_at = datetime.now(timezone.utc)
    manager.review_note = note
    manager.prior_rejected_candidates = prior
    session.add(manager)
    session.flush()
    session.add(
        _cik_review_event(
            manager,
            event_type="reject_candidate_cik",
            old_cik=old_cik,
            old_match_status=old_status,
            reviewed_by_user_id=reviewed_by_user_id,
            note=note,
            evidence_json=_manager_candidate_evidence(manager),
        )
    )
    session.commit()
    session.refresh(manager)
    return _manager_payload(manager)


def revoke_manager_cik(
    session: Session,
    manager_id: int,
    *,
    note: str | None = None,
    reviewed_by_user_id: int | None = None,
) -> dict[str, Any]:
    manager = session.get(InstitutionManager, manager_id)
    if manager is None:
        raise ValueError("Manager not found")
    if manager.match_status != "confirmed" or not manager.cik:
        raise ValueError("Only confirmed managers with a CIK can be revoked")
    if not note or not note.strip():
        raise ValueError("note is required to revoke a confirmed CIK")

    old_cik = manager.cik
    old_status = manager.match_status
    affected = _affected_filing_scope(session, manager.id)
    manager.cik = None
    manager.match_status = "revoked"
    manager.reviewed_by_user_id = reviewed_by_user_id
    manager.reviewed_at = datetime.now(timezone.utc)
    manager.review_note = note.strip()
    session.add(manager)
    session.flush()
    event = _cik_review_event(
        manager,
        event_type="revoke_confirmed_cik",
        old_cik=old_cik,
        old_match_status=old_status,
        reviewed_by_user_id=reviewed_by_user_id,
        note=note.strip(),
        evidence_json={
            "reason": "confirmed_cik_revoked",
            "downstream_policy": "existing_filings_and_holdings_preserved_for_audit",
        },
        affected_filings_count=affected["filings_count"],
        affected_quarters=affected["quarters"],
        requires_downstream_review=affected["filings_count"] > 0,
    )
    session.add(event)
    session.commit()
    session.refresh(manager)
    return _manager_payload(manager)


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
            "preview": _job_preview(session, job_type, payload, lock_key),
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


def smart_retry_failed_jobs(session: Session, *, today: date | None = None) -> list[dict[str, Any]]:
    """Identifies partially failed jobs and enqueues targeted retries for their failed accessions.

    Criteria for smart retry:
      - Job status is 'partial_success'
      - Job has 'failed_accessions' in its summary_json
      - Job is at least 24 hours old (to respect SEC rate limits and transient errors)
      - The failed accession hasn't been successfully processed by a newer job
    """
    today_dt = datetime.now(timezone.utc) if today is None else datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    cutoff = today_dt - timedelta(hours=24)

    # Find candidate jobs
    jobs = (
        session.query(JobRun)
        .filter(JobRun.status == "partial_success")
        .filter(JobRun.finished_at <= cutoff)
        .order_by(JobRun.finished_at.desc())
        .all()
    )

    results: list[dict[str, Any]] = []
    seen_accessions: set[str] = set()

    for job in jobs:
        summary = job.summary_json if isinstance(job.summary_json, dict) else {}
        # Support both top-level and nested failed_accessions (from quarterly_pipeline)
        failures = summary.get("failed_accessions")
        if not failures and "holdings_ingestion" in summary:
            failures = summary["holdings_ingestion"].get("failed_accessions")

        if not isinstance(failures, list):
            continue

        for failure in failures:
            if not isinstance(failure, dict):
                continue
            accession_no = failure.get("accession_no")
            if not accession_no or accession_no in seen_accessions:
                continue
            seen_accessions.add(accession_no)

            # Check if this accession has already been successfully retried or is currently being retried
            already_active = (
                session.query(JobRun)
                .filter(JobRun.lock_key == f"ingest_accession:{accession_no}")
                .filter(JobRun.status.in_(ACTIVE_JOB_STATUSES | {"succeeded"}))
                .filter(JobRun.created_at > job.created_at)
                .first()
            )
            if already_active:
                continue

            # Trigger a targeted retry
            try:
                trigger_result = trigger_job(
                    session,
                    requested_by_user_id=None,
                    payload={
                        "job_type": "ingest_accession",
                        "accession_no": accession_no,
                        "trigger_source": "smart_retry",
                    },
                )
                if not trigger_result.get("conflict"):
                    results.append(trigger_result)
            except Exception as exc:
                logger.warning("Failed to trigger smart retry for accession %s: %s", accession_no, exc)

    return results


def execute_job_payload(session: Session, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _execute_job(session, job_type, payload)


def _job_preview(session: Session, job_type: str, payload: dict[str, Any], lock_key: str) -> dict[str, Any]:
    quarter = payload.get("quarter")
    accession_no = payload.get("accession_no")
    warnings = ["13F jobs may call EDGAR and should respect SEC rate limits."]
    preview: dict[str, Any] = {
        "requires_confirmation": True,
        "lock_key": lock_key,
        "target_quarter": quarter,
        "accession_no": accession_no,
        "rate_limit_warning": warnings[0],
        "warnings": warnings,
        "estimated_scope": {},
    }

    if quarter:
        window = quarter_window(str(quarter))
        filings_query = session.query(Filing13F).filter(Filing13F.period_of_report.between(window.start, window.end))
        pending_query = filings_query.filter(Filing13F.raw_infotable_doc_id.is_(None))
        preview["estimated_scope"] = {
            "tracked_managers": _confirmed_manager_count(session),
            "filings_in_quarter": filings_query.count(),
            "pending_filings": pending_query.count(),
            "failed_filings": _failed_filing_count(session, window),
        }
    elif accession_no:
        filing = session.query(Filing13F).filter(Filing13F.accession_no == str(accession_no)).one_or_none()
        preview["estimated_scope"] = {
            "filing_exists": filing is not None,
            "manager_id": filing.manager_id if filing else None,
            "period_of_report": filing.period_of_report.isoformat() if filing else None,
            "form_type": filing.form_type if filing else None,
        }
    elif job_type == "backfill_quarters":
        preview["estimated_scope"] = {
            "start_quarter": payload.get("start_quarter") or "latest",
            "quarters": payload.get("quarters"),
        }
    elif job_type in {"bootstrap_whitelist", "match_cik"}:
        preview["estimated_scope"] = {
            "managers": session.query(InstitutionManager).count(),
            "confirmed_managers": _confirmed_manager_count(session),
            "candidate_managers": session.query(InstitutionManager).filter(InstitutionManager.match_status == "candidate").count(),
        }
    return preview


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
    quality_report = _latest_quality_report(session, quarter)
    quality_status = quality_report.status if quality_report else "not_checked"
    phase = _quarter_phase(window, today)
    active_job = _active_quarter_job(session, quarter)
    has_prior_data = _has_prior_quarter_holdings(session, quarter)
    health = _quarter_health(
        confirmed_managers=confirmed_managers,
        form_idx_fetched=form_idx_fetched,
        filings_count=len(filings),
        holdings_count=holdings_count,
        failed_filings=failed_filings,
        linked_ratio=linked_ratio,
        amendment_status=amendment_status,
        quality_status=quality_status,
        phase=phase,
        active_job=active_job is not None,
        has_prior_data=has_prior_data,
    )
    linked_holding_unavailable_reason = "NO_HOLDINGS_PARSED" if linked_ratio is None else None
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
        "linked_holding_unavailable_reason": linked_holding_unavailable_reason,
        "failed_filings": failed_filings,
        "amendment_status": amendment_status,
        "quality_status": quality_status,
        "quality_errors": quality_report.error_count if quality_report else None,
        "quality_warnings": quality_report.warning_count if quality_report else None,
        "quality_checked_at": quality_report.checked_at.isoformat() if quality_report else None,
        "quality_report_id": quality_report.id if quality_report else None,
        "last_successful_job_at": _last_successful_job_at(session),
        "active_job_id": active_job.id if active_job else None,
        "active_job_type": active_job.job_type if active_job else None,
    }


def _quarter_phase(window: QuarterWindow, today: date) -> str:
    if today < window.end:
        return "pre_window"
    if today < window.deadline:
        return "filing_window_open"
    return "post_deadline"


def _quarter_health(*, confirmed_managers: int, form_idx_fetched: bool, filings_count: int, holdings_count: int, failed_filings: int, linked_ratio: float | None, amendment_status: str, quality_status: str, phase: str, active_job: bool, has_prior_data: bool) -> str:
    if confirmed_managers == 0:
        return "setup_required"
    if failed_filings:
        return "failed"
    if amendment_status in {"amendments_pending", "amendment_failed"}:
        return "needs_review"
    if quality_status in {"failed", "warning"}:
        return "needs_review"
    if active_job:
        return "ingesting"
    if phase == "post_deadline" and not form_idx_fetched and filings_count == 0 and has_prior_data:
        return "stale"
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


def _setup_checklist(
    *,
    scheduler_enabled: bool,
    counts: dict[str, Any],
    usable_summary: dict[str, Any],
    historical_depth: int,
) -> list[dict[str, Any]]:
    def item(code: str, label: str, complete_when: str, complete: bool, admin_action: str, *, warning: bool = False) -> dict[str, Any]:
        status = "complete" if complete else "warning" if warning else "blocked"
        return {
            "code": code,
            "label": label,
            "status": status,
            "complete_when": complete_when,
            "admin_action": admin_action,
        }

    amendment_ok = usable_summary["amendment_status"] in {"no_amendments", "amendments_applied"}
    quality_ok = usable_summary["quality_status"] == "passed" and amendment_ok
    return [
        item(
            "SCHEDULER_CONFIGURED",
            "Scheduler configured",
            "EDGAR_SCHEDULER_ENABLED is true",
            scheduler_enabled,
            "Enable EDGAR_SCHEDULER_ENABLED and redeploy the API service",
        ),
        item(
            "MANAGER_WHITELIST_SEEDED",
            "Manager whitelist seeded",
            "At least one tracked manager exists",
            counts["managers"] > 0,
            "Bootstrap whitelist",
        ),
        item(
            "MANAGER_CIKS_CONFIRMED",
            "Manager CIKs confirmed",
            "At least one manager has a confirmed CIK",
            counts["confirmed_managers"] > 0,
            "Bootstrap whitelist, match CIK, review candidates",
        ),
        item(
            "QUARTER_INDEX_FETCHED",
            "Quarter index fetched",
            "Latest usable quarter has an EDGAR form index document",
            usable_summary["form_idx_fetched"],
            "Fetch quarter index",
        ),
        item(
            "FILINGS_AVAILABLE",
            "Filings available",
            "Latest usable quarter has at least one effective filing",
            usable_summary["filings_count"] > 0,
            "Fetch quarter index or inspect whitelist coverage",
        ),
        item(
            "HOLDINGS_INGESTED",
            "Holdings ingested",
            "Latest usable quarter has parsed holdings",
            usable_summary["holdings_count"] > 0,
            "Ingest holdings",
        ),
        item(
            "CUSIP_ENRICHED",
            "CUSIP enriched",
            "Linked holding ratio is at least the ready threshold",
            usable_summary["linked_holding_ratio"] is not None and usable_summary["linked_holding_ratio"] >= READY_LINK_RATIO,
            "Run CUSIP enrichment and bootstrap stocks",
            warning=usable_summary["linked_holding_ratio"] is not None,
        ),
        item(
            "QUALITY_CHECKED",
            "Quality checked",
            "Latest quality check passed and amendments are applied or absent",
            quality_ok,
            "Run quality check and reprocess pending or failed amendments",
        ),
        item(
            "HISTORICAL_DEPTH_TARGET",
            "Historical depth target",
            "At least four consecutive quarters have holdings",
            historical_depth >= 4,
            "Run historical backfill",
            warning=historical_depth > 0,
        ),
    ]


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


def _active_quarter_job(session: Session, quarter: str) -> JobRun | None:
    return (
        session.query(JobRun)
        .filter(JobRun.status.in_(ACTIVE_JOB_STATUSES))
        .filter(
            or_(
                JobRun.quarter == quarter,
                JobRun.lock_key.in_(
                    [
                        f"fetch_quarter_index:{quarter}",
                        f"ingest_holdings:{quarter}",
                        f"quality_check:{quarter}",
                        f"enrich_cusip:{quarter}",
                    ]
                ),
            )
        )
        .order_by(JobRun.created_at.desc(), JobRun.id.desc())
        .first()
    )


def _has_prior_quarter_holdings(session: Session, quarter: str) -> bool:
    window = quarter_window(quarter)
    return (
        session.query(Holding13F)
        .join(Filing13F, Filing13F.id == Holding13F.filing_id)
        .filter(Filing13F.period_of_report < window.start)
        .filter(Filing13F.is_latest_for_period.is_(True))
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


def _task_with_metadata(priority: str, code: str, title: str, recommended_action: str, metadata: dict[str, Any]) -> dict[str, Any]:
    task = _task(priority, code, title, recommended_action)
    task["metadata"] = metadata
    return task


def _revoked_cik_repair_tasks(session: Session) -> list[dict[str, Any]]:
    events = (
        session.query(InstitutionManagerCikReviewEvent, InstitutionManager)
        .join(InstitutionManager, InstitutionManager.id == InstitutionManagerCikReviewEvent.manager_id)
        .filter(InstitutionManager.match_status == "revoked")
        .filter(InstitutionManagerCikReviewEvent.event_type == "revoke_confirmed_cik")
        .filter(InstitutionManagerCikReviewEvent.requires_downstream_review.is_(True))
        .order_by(InstitutionManagerCikReviewEvent.created_at.desc(), InstitutionManagerCikReviewEvent.id.desc())
        .all()
    )
    latest_by_manager: dict[int, tuple[InstitutionManagerCikReviewEvent, InstitutionManager]] = {}
    for event, manager in events:
        if manager.id not in latest_by_manager:
            latest_by_manager[manager.id] = (event, manager)

    tasks: list[dict[str, Any]] = []
    for event, manager in latest_by_manager.values():
        quarters = event.affected_quarters or []
        quarter_text = ", ".join(quarters[:4]) if quarters else "affected quarters"
        if len(quarters) > 4:
            quarter_text = f"{quarter_text}, +{len(quarters) - 4} more"
        tasks.append(
            _task_with_metadata(
                "P1",
                "REVOKED_CIK_DOWNSTREAM_REVIEW",
                f"Revoked CIK requires downstream review: {manager.legal_name}",
                f"Reconfirm the correct CIK, then reprocess affected quarters ({quarter_text}).",
                {
                    "manager_id": manager.id,
                    "manager_name": manager.legal_name,
                    "old_cik": event.old_cik,
                    "affected_filings_count": event.affected_filings_count,
                    "affected_quarters": quarters,
                    "review_event_id": event.id,
                },
            )
        )
    return tasks


def _recent_job_alert_tasks(session: Session, *, limit: int = 5) -> list[dict[str, Any]]:
    jobs = (
        session.query(JobRun)
        .filter(JobRun.status.in_(["failed", "partial_success"]))
        .order_by(JobRun.finished_at.desc().nullslast(), JobRun.created_at.desc())
        .limit(limit)
        .all()
    )
    tasks: list[dict[str, Any]] = []
    for job in jobs:
        retry_targets = _job_retry_targets(job)
        failed_accessions_count = len(retry_targets)
        code = "RECENT_JOB_FAILED" if job.status == "failed" else "RECENT_JOB_PARTIAL_SUCCESS"
        priority = "P1" if job.status == "failed" else "P2"
        title = f"{job.job_type} job {job.status.replace('_', ' ')}"
        if job.quarter:
            title = f"{title}: {job.quarter}"
        recommended_action = (
            "Review job timeline and retry failed accessions."
            if retry_targets
            else "Review job timeline and rerun the affected job if the failure is transient."
        )
        tasks.append(
            _task_with_metadata(
                priority,
                code,
                title,
                recommended_action,
                {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "status": job.status,
                    "quarter": job.quarter,
                    "accession_no": (job.input_json or {}).get("accession_no") if isinstance(job.input_json, dict) else None,
                    "failed_accessions_count": failed_accessions_count,
                    "retry_targets": retry_targets,
                    "error_message": job.error_message,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                },
            )
        )
    return tasks


def _worker_operational_tasks(session: Session, *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    queued_jobs = (
        session.query(JobRun)
        .filter(JobRun.status == "queued")
        .order_by(JobRun.created_at.asc(), JobRun.id.asc())
        .all()
    )
    if not queued_jobs:
        return []

    stale_cutoff = now - timedelta(seconds=settings.THIRTEENF_JOB_WORKER_HEARTBEAT_STALE_S)
    workers = session.query(JobWorkerHeartbeat).all()
    active_workers = [
        worker
        for worker in workers
        if worker.status not in {"stopped", "error"} and worker.last_heartbeat_at >= stale_cutoff
    ]
    oldest = queued_jobs[0]
    oldest_seconds = int((now - oldest.created_at).total_seconds()) if oldest.created_at else None
    metadata = {
        "queued_jobs_count": len(queued_jobs),
        "oldest_queued_job_id": oldest.id,
        "oldest_queued_job_type": oldest.job_type,
        "oldest_queued_job_status": oldest.status,
        "oldest_queued_seconds": oldest_seconds,
        "oldest_queued_at": oldest.created_at.isoformat() if oldest.created_at else None,
        "oldest_queued_quarter": oldest.quarter,
        "worker_count": len(workers),
        "active_worker_count": len(active_workers),
        "stale_worker_count": max(len(workers) - len(active_workers), 0),
    }
    if not active_workers:
        return [
            _task_with_metadata(
                "P1",
                "JOB_WORKER_UNAVAILABLE",
                "13F job worker unavailable",
                "Inspect or restart the 13F job worker; queued jobs cannot run without an active heartbeat.",
                metadata,
            )
        ]
    if oldest_seconds is not None and oldest_seconds >= STUCK_QUEUED_JOB_AFTER_SECONDS:
        return [
            _task_with_metadata(
                "P2",
                "STUCK_QUEUED_JOB",
                "13F job has been queued too long",
                "Inspect worker heartbeat and job lock state; cancel or retry the queued job if needed.",
                metadata,
            )
        ]
    return []


def _job_payload(job: JobRun) -> dict[str, Any]:
    events = _job_events(job)
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
        "events": events,
        "retry_targets": _job_retry_targets(job),
    }


def _job_events(job: JobRun) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if job.created_at:
        events.append(
            {
                "event_type": "job_created",
                "at": job.created_at.isoformat(),
                "message": f"{job.job_type} queued from {job.trigger_source}",
                "severity": "info",
            }
        )
    if job.started_at:
        events.append(
            {
                "event_type": "job_started",
                "at": job.started_at.isoformat(),
                "message": f"{job.job_type} started",
                "severity": "info",
                "worker_id": job.worker_id,
            }
        )
    if job.heartbeat_at:
        events.append(
            {
                "event_type": "job_heartbeat",
                "at": job.heartbeat_at.isoformat(),
                "message": "Worker heartbeat recorded",
                "severity": "info",
                "worker_id": job.worker_id,
            }
        )
    summary = job.summary_json if isinstance(job.summary_json, dict) else {}
    for failure in summary.get("failed_accessions") or []:
        if not isinstance(failure, dict):
            continue
        accession_no = failure.get("accession_no")
        events.append(
            {
                "event_type": "accession_failed",
                "at": job.finished_at.isoformat() if job.finished_at else None,
                "message": failure.get("error") or "Accession failed",
                "severity": "error",
                "accession_no": accession_no,
                "retry_target": {"job_type": "ingest_accession", "accession_no": accession_no} if accession_no else None,
            }
        )
    for issue in summary.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        events.append(
            {
                "event_type": "quality_issue",
                "at": job.finished_at.isoformat() if job.finished_at else None,
                "message": issue.get("detail") or issue.get("check") or "Quality issue",
                "severity": issue.get("severity") or "warning",
                "accession_no": issue.get("accession_no"),
                "check": issue.get("check"),
            }
        )
    if job.error_message:
        events.append(
            {
                "event_type": "job_error",
                "at": job.finished_at.isoformat() if job.finished_at else None,
                "message": job.error_message,
                "severity": "error",
            }
        )
    if job.finished_at:
        events.append(
            {
                "event_type": "job_finished",
                "at": job.finished_at.isoformat(),
                "message": f"{job.job_type} finished with status {job.status}",
                "severity": "error" if job.status == "failed" else "warning" if job.status == "partial_success" else "info",
            }
        )
    return sorted(events, key=lambda item: item.get("at") or "")


def _job_retry_targets(job: JobRun) -> list[dict[str, str]]:
    summary = job.summary_json if isinstance(job.summary_json, dict) else {}
    targets: list[dict[str, str]] = []
    seen: set[str] = set()
    for failure in summary.get("failed_accessions") or []:
        if not isinstance(failure, dict):
            continue
        accession_no = failure.get("accession_no")
        if not accession_no or accession_no in seen:
            continue
        seen.add(accession_no)
        targets.append(
            {
                "job_type": "ingest_accession",
                "accession_no": accession_no,
                "label": f"Retry accession {accession_no}",
            }
        )
    return targets


def _manager_payload(manager: InstitutionManager) -> dict[str, Any]:
    latest_event = _latest_cik_review_event(manager)
    return {
        "id": manager.id,
        "cik": manager.cik,
        "legal_name": manager.legal_name,
        "display_name": manager.display_name,
        "match_status": manager.match_status,
        "is_superinvestor": manager.is_superinvestor,
        "dataroma_code": manager.dataroma_code,
        "last_seen_at": manager.last_seen_at.isoformat() if manager.last_seen_at else None,
        "candidate_cik": manager.candidate_cik,
        "candidate_legal_name": manager.candidate_legal_name,
        "candidate_similarity_score": manager.candidate_similarity_score,
        "candidate_source": manager.candidate_source,
        "candidate_evidence_url": manager.candidate_evidence_url,
        "candidate_found_at": manager.candidate_found_at.isoformat() if manager.candidate_found_at else None,
        "reviewed_by_user_id": manager.reviewed_by_user_id,
        "reviewed_at": manager.reviewed_at.isoformat() if manager.reviewed_at else None,
        "review_note": manager.review_note,
        "prior_rejected_candidates": manager.prior_rejected_candidates or [],
        "latest_cik_review_event": _cik_review_event_payload(latest_event) if latest_event else None,
    }


def _filing_detail_payload(session: Session, filing: Filing13F) -> dict[str, Any]:
    holdings_count = session.query(Holding13F).filter(Holding13F.filing_id == filing.id).count()
    primary = filing.raw_primary_doc
    infotable = filing.raw_infotable_doc
    raw_docs = [doc for doc in [primary, infotable] if doc is not None]
    if any(doc.parse_status == "failed" for doc in raw_docs):
        status = "failed"
    elif filing.raw_infotable_doc_id is None:
        status = "pending"
    elif holdings_count == 0:
        status = "parsed_no_holdings"
    else:
        status = "parsed"
    return {
        "id": filing.id,
        "accession_no": filing.accession_no,
        "form_type": filing.form_type,
        "status": status,
        "manager": {
            "id": filing.manager.id,
            "legal_name": filing.manager.legal_name,
            "display_name": filing.manager.display_name,
            "cik": filing.manager.cik,
        },
        "quarter": quarter_label_for_date(filing.period_of_report),
        "period_of_report": filing.period_of_report.isoformat(),
        "filed_at": filing.filed_at.isoformat() if filing.filed_at else None,
        "version_rank": filing.version_rank,
        "is_latest_for_period": filing.is_latest_for_period,
        "amends_accession_no": filing.amends_accession_no,
        "holdings_count": holdings_count,
        "raw_primary": _raw_document_payload(primary),
        "raw_infotable": _raw_document_payload(infotable),
    }


def _quarter_suggested_actions(
    *,
    quarter: str,
    pending_filings: list[dict[str, Any]],
    failed_filings: list[dict[str, Any]],
    amendments: list[dict[str, Any]],
    quality_report: QualityReport13F | None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if pending_filings or failed_filings:
        actions.append(
            {
                "job_type": "ingest_holdings",
                "quarter": quarter,
                "label": "Ingest or retry quarter holdings",
                "reason": f"{len(pending_filings)} pending and {len(failed_filings)} failed filings need attention.",
            }
        )
    for amendment in amendments:
        if amendment["status"] in {"pending", "failed"}:
            actions.append(
                {
                    "job_type": "reprocess_amendment",
                    "accession_no": amendment["accession_no"],
                    "label": f"Reprocess amendment {amendment['accession_no']}",
                    "reason": f"Amendment status is {amendment['status']}.",
                }
            )
    if quality_report is None or quality_report.status in {"failed", "warning"}:
        actions.append(
            {
                "job_type": "quality_check",
                "quarter": quarter,
                "label": "Run quality check",
                "reason": "Latest quality report is missing, failed, or warning.",
            }
        )
    return actions


def _latest_cik_review_event(manager: InstitutionManager) -> InstitutionManagerCikReviewEvent | None:
    events = getattr(manager, "cik_review_events", None)
    if isinstance(events, list) and events:
        return sorted(events, key=lambda event: (event.created_at, event.id), reverse=True)[0]
    return None


def _manager_candidate_evidence(manager: InstitutionManager) -> dict[str, Any]:
    return {
        "candidate_cik": manager.candidate_cik,
        "candidate_legal_name": manager.candidate_legal_name,
        "candidate_similarity_score": manager.candidate_similarity_score,
        "candidate_source": manager.candidate_source,
        "candidate_evidence_url": manager.candidate_evidence_url,
    }


def _affected_filing_scope(session: Session, manager_id: int) -> dict[str, Any]:
    period_rows = (
        session.query(Filing13F.period_of_report)
        .filter(Filing13F.manager_id == manager_id)
        .distinct()
        .all()
    )
    quarters = sorted({quarter_label_for_date(row[0]) for row in period_rows if row[0]})
    return {
        "filings_count": session.query(Filing13F).filter(Filing13F.manager_id == manager_id).count(),
        "quarters": quarters,
    }


def _cik_review_event(
    manager: InstitutionManager,
    *,
    event_type: str,
    old_cik: str | None,
    old_match_status: str | None,
    reviewed_by_user_id: int | None,
    note: str | None,
    evidence_json: dict[str, Any] | None,
    affected_filings_count: int = 0,
    affected_quarters: list[str] | None = None,
    requires_downstream_review: bool = False,
) -> InstitutionManagerCikReviewEvent:
    return InstitutionManagerCikReviewEvent(
        manager_id=manager.id,
        event_type=event_type,
        old_cik=old_cik,
        new_cik=manager.cik,
        old_match_status=old_match_status,
        new_match_status=manager.match_status,
        reviewed_by_user_id=reviewed_by_user_id,
        note=note,
        evidence_json=evidence_json,
        affected_filings_count=affected_filings_count,
        affected_quarters=affected_quarters or [],
        requires_downstream_review=requires_downstream_review,
    )


def _cik_review_event_payload(event: InstitutionManagerCikReviewEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "manager_id": event.manager_id,
        "event_type": event.event_type,
        "old_cik": event.old_cik,
        "new_cik": event.new_cik,
        "old_match_status": event.old_match_status,
        "new_match_status": event.new_match_status,
        "reviewed_by_user_id": event.reviewed_by_user_id,
        "note": event.note,
        "evidence": event.evidence_json or {},
        "affected_filings_count": event.affected_filings_count,
        "affected_quarters": event.affected_quarters or [],
        "requires_downstream_review": event.requires_downstream_review,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _quality_report_payload(report: QualityReport13F) -> dict[str, Any]:
    return {
        "id": report.id,
        "quarter": report.quarter,
        "status": report.status,
        "error_count": report.error_count,
        "warning_count": report.warning_count,
        "info_count": report.info_count,
        "unavailable_reasons": report.unavailable_reasons or [],
        "issues": report.issues_json or [],
        "summary": report.summary,
        "source_job_id": report.source_job_id,
        "checked_at": report.checked_at.isoformat(),
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


def _amendment_payload(session: Session, filing: Filing13F) -> dict[str, Any]:
    holdings_count = session.query(Holding13F).filter(Holding13F.filing_id == filing.id).count()
    primary = filing.raw_primary_doc
    infotable = filing.raw_infotable_doc
    raw_docs = [doc for doc in [primary, infotable] if doc is not None]
    has_failed_raw = any(doc.parse_status == "failed" for doc in raw_docs)
    if has_failed_raw:
        status = "failed"
    elif filing.raw_infotable_doc_id is None or holdings_count == 0:
        status = "pending"
    elif filing.is_latest_for_period:
        status = "applied"
    else:
        status = "superseded"
    latest_effective = _latest_effective_filing(session, filing)
    recommended_job = (
        {"job_type": "reprocess_amendment", "accession_no": filing.accession_no}
        if status in {"failed", "pending"}
        else None
    )
    return {
        "id": filing.id,
        "accession_no": filing.accession_no,
        "form_type": filing.form_type,
        "status": status,
        "manager": {
            "id": filing.manager.id,
            "legal_name": filing.manager.legal_name,
            "display_name": filing.manager.display_name,
            "cik": filing.manager.cik,
        },
        "quarter": quarter_label_for_date(filing.period_of_report),
        "period_of_report": filing.period_of_report.isoformat(),
        "filed_at": filing.filed_at.isoformat() if filing.filed_at else None,
        "version_rank": filing.version_rank,
        "is_latest_for_period": filing.is_latest_for_period,
        "latest_effective_accession_no": latest_effective.accession_no if latest_effective else None,
        "supersedes_accession_no": filing.amends_accession_no or _previous_accession_for_amendment(session, filing),
        "holdings_count": holdings_count,
        "raw_primary": _raw_document_payload(primary),
        "raw_infotable": _raw_document_payload(infotable),
        "recommended_job": recommended_job,
    }


def _raw_document_payload(document: RawSourceDocument | None) -> dict[str, Any]:
    if document is None:
        return {
            "id": None,
            "parse_status": "missing",
            "error_message": None,
            "source_url": None,
            "parsed_at": None,
        }
    return {
        "id": document.id,
        "parse_status": document.parse_status,
        "error_message": document.error_message,
        "source_url": document.source_url,
        "parsed_at": document.parsed_at.isoformat() if document.parsed_at else None,
    }


def _latest_effective_filing(session: Session, filing: Filing13F) -> Filing13F | None:
    return (
        session.query(Filing13F)
        .filter(Filing13F.manager_id == filing.manager_id)
        .filter(Filing13F.period_of_report == filing.period_of_report)
        .filter(Filing13F.is_latest_for_period.is_(True))
        .order_by(Filing13F.version_rank.desc(), Filing13F.filed_at.desc(), Filing13F.id.desc())
        .first()
    )


def _previous_accession_for_amendment(session: Session, filing: Filing13F) -> str | None:
    previous = (
        session.query(Filing13F)
        .filter(Filing13F.manager_id == filing.manager_id)
        .filter(Filing13F.period_of_report == filing.period_of_report)
        .filter(Filing13F.id != filing.id)
        .filter(Filing13F.version_rank < filing.version_rank)
        .order_by(Filing13F.version_rank.desc(), Filing13F.filed_at.desc(), Filing13F.id.desc())
        .first()
    )
    return previous.accession_no if previous else None


def _latest_quality_report(session: Session, quarter: str) -> QualityReport13F | None:
    return (
        session.query(QualityReport13F)
        .filter(QualityReport13F.quarter == quarter)
        .order_by(QualityReport13F.checked_at.desc(), QualityReport13F.id.desc())
        .first()
    )


def _required(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not value:
        raise ValueError(f"{key} is required")
    return str(value)


_JOB_LOCK_BUILDERS = {
    "quarterly_pipeline": lambda payload: f"quarterly_pipeline:{_required(payload, 'quarter')}",
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
    if job_type == "quarterly_pipeline":
        quarter = _required(payload, "quarter")
        results = {"quarter": quarter}

        # Step 1: fetch form.idx and seed filing metadata
        from app.services.edgar_ingestion import ingest_quarter_index
        results["index_filings"] = ingest_quarter_index(session, quarter)
        session.commit()

        # Step 2: download + parse infotable for all new filings
        # _execute_ingest_job commits per-filing internally; no uncommitted work remains.
        ingest_results = _execute_ingest_job(session, "ingest_holdings", {"quarter": quarter})
        results["holdings_ingestion"] = ingest_results

        # Step 3: refresh CUSIP -> ticker mappings
        from app.services.cusip_enrichment import enrich_from_dataroma
        results["cusip_mappings"] = enrich_from_dataroma(session)
        session.commit()

        # Step 4: bootstrap stocks + backfill stock_id
        from app.services.cusip_enrichment import bootstrap_stocks_from_cusip_map, backfill_stock_ids
        results["new_stocks"] = bootstrap_stocks_from_cusip_map(session)
        results["holdings_linked"] = backfill_stock_ids(session)
        session.commit()

        # Step 5: EDGAR company_tickers.json for remaining unmatched
        from app.services.cusip_enrichment import enrich_stocks_from_edgar_tickers
        try:
            edgar_results = enrich_stocks_from_edgar_tickers(session)
            results["edgar_enrichment"] = edgar_results
            session.commit()
        except Exception as exc:
            session.rollback()
            results["edgar_enrichment_error"] = str(exc)

        # Step 6: data quality check
        report = run_quality_checks(session, quarter)
        persist_quality_report(session, quarter=quarter, report=report, source_job_id=payload.get("_job_id"))
        session.commit()
        results["quality_status"] = report.status

        status = "succeeded"
        if ingest_results.get("status") == "partial_success" or "edgar_enrichment_error" in results:
            status = "partial_success"
        return {**results, "status": status}

    if job_type == "quality_check":
        quarter = payload.get("quarter")
        report = run_quality_checks(session, quarter)
        persisted = persist_quality_report(
            session,
            quarter=quarter,
            report=report,
            source_job_id=payload.get("_job_id"),
        )
        return {
            "status": "failed" if report.errors else "succeeded",
            "quality_report_id": persisted.id,
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
