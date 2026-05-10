from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.institutions import EdgarSyncStatus, Filing13F, JobRun, NoIndexExpectedDate
from app.services.thirteenf_alerts import AlertTransport, emit_alert
from app.services.thirteenf_job_worker import job_timeout_seconds
from app.services.thirteenf_readiness import build_readiness_summary


def evaluate_13f_alerts(
    session: Session,
    *,
    now: datetime | None = None,
    edgar_rate_limit_status: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    alerts: list[dict[str, Any]] = []

    daily_sync_alert = _daily_sync_consecutive_failure_alert(session, today=today)
    if daily_sync_alert:
        alerts.append(daily_sync_alert)

    readiness = build_readiness_summary(session, today=today)
    alerts.extend(_readiness_metric_alerts(session, readiness, today=today))
    alerts.extend(_amendment_alerts(session, now=now))
    alerts.extend(_needs_review_alerts(session, now=now))
    alerts.extend(_ingest_timeout_retry_alerts(session))
    alerts.extend(_running_job_alerts(session, now=now))

    if edgar_rate_limit_status and edgar_rate_limit_status.get("edgar_block_alert"):
        alerts.append(
            _alert(
                "SEC_EDGAR_BLOCK_ALERT",
                "P1",
                "SEC EDGAR 403/429 responses detected",
                "SEC EDGAR is returning block/throttle signals; pause ingestion and investigate rate limiting.",
                context={
                    "recent_403_count": edgar_rate_limit_status.get("recent_403_count", 0),
                    "recent_429_count": edgar_rate_limit_status.get("recent_429_count", 0),
                },
            )
        )

    return alerts


def readiness_downgrade_alert(
    previous_level: str,
    current_level: str,
    *,
    quarter: str,
    window_closed: bool,
) -> dict[str, Any] | None:
    if not window_closed or previous_level == current_level:
        return None
    if previous_level == "ready" and current_level == "unavailable":
        return _alert(
            "READINESS_DOWNGRADE_UNAVAILABLE",
            "P1",
            "Oracle's Lens readiness downgraded to unavailable",
            f"{quarter} is no longer available for Oracle's Lens.",
            context={"quarter": quarter, "previous_level": previous_level, "current_level": current_level},
        )
    if previous_level == "ready" and current_level in {"usable_with_warning", "experimental"}:
        return _alert(
            "READINESS_DOWNGRADE_WARNING",
            "P2",
            "Oracle's Lens readiness downgraded",
            f"{quarter} readiness downgraded from ready to {current_level}.",
            context={"quarter": quarter, "previous_level": previous_level, "current_level": current_level},
        )
    return None


def build_daily_health_summary(session: Session, *, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    readiness = build_readiness_summary(session, today=today)
    metrics = readiness.get("metrics", {})
    yesterday_sync = session.get(EdgarSyncStatus, yesterday)

    return {
        "summary_date": today.isoformat(),
        "yesterday_sync_date": yesterday.isoformat(),
        "yesterday_sync_status": yesterday_sync.status if yesterday_sync else "missing",
        "readiness_level": readiness.get("readiness_level"),
        "latest_usable_quarter": readiness.get("latest_usable_quarter"),
        "manager_coverage_ratio": _ratio_value(metrics.get("manager_coverage_ratio")),
        "expected_filer_count": metrics.get("expected_filer_count", 0),
        "nt_filer_count": metrics.get("nt_filer_count", 0),
        "combination_report_count": _filing_count(session, report_type="combination_report"),
        "confidential_treatment_count": _confidential_count(session),
        "failed_filings_count": session.query(Filing13F).filter(Filing13F.parse_status == "failed").count(),
        "amendments_pending_count": session.query(Filing13F)
        .filter(Filing13F.amendment_status == "amendments_pending")
        .count(),
        "cusip_mapping_ratio": _ratio_value(metrics.get("linked_common_holding_ratio")),
        "nt_detection_supported": readiness.get("nt_detection_supported", True),
    }


def emit_daily_health_summary(
    session: Session,
    *,
    today: date | None = None,
    transport: AlertTransport | None = None,
) -> dict[str, Any]:
    summary = build_daily_health_summary(session, today=today)
    message = (
        f"Readiness: {summary['readiness_level']} | "
        f"Coverage: {_pct(summary['manager_coverage_ratio'])} | "
        f"CUSIP mapping: {_pct(summary['cusip_mapping_ratio'])} | "
        f"Failed filings: {summary['failed_filings_count']} | "
        f"Pending amendments: {summary['amendments_pending_count']}"
    )
    return emit_alert(
        severity="P3",
        title="13F daily health summary",
        message=message,
        context=summary,
        transport=transport,
    )


def _daily_sync_consecutive_failure_alert(session: Session, *, today: date) -> dict[str, Any] | None:
    dates = _recent_edgar_business_dates(session, today=today, limit=2)
    if len(dates) < 2:
        return None
    failed_dates = []
    for sync_date in dates:
        row = session.get(EdgarSyncStatus, sync_date)
        if not row or row.status != "failed":
            return None
        failed_dates.append(sync_date.isoformat())
    return _alert(
        "DAILY_SYNC_CONSECUTIVE_FAILED_BUSINESS_DAYS",
        "P1",
        "Daily 13F sync failed for two business days",
        "Daily form.idx sync failed for two consecutive EDGAR business days.",
        context={"failed_business_dates": failed_dates},
    )


def _recent_edgar_business_dates(session: Session, *, today: date, limit: int) -> list[date]:
    dates: list[date] = []
    cursor = today - timedelta(days=1)
    while len(dates) < limit and (today - cursor).days < 14:
        if cursor.weekday() < 5 and not NoIndexExpectedDate.active_for_date(session, cursor):
            dates.append(cursor)
        cursor -= timedelta(days=1)
    return dates


def _readiness_metric_alerts(session: Session, readiness: dict[str, Any], *, today: date) -> list[dict[str, Any]]:
    if not _has_closed_filing_window(session, today=today):
        return []
    metrics = readiness.get("metrics", {})
    alerts: list[dict[str, Any]] = []
    coverage = _ratio_value(metrics.get("manager_coverage_ratio"))
    if coverage is not None and coverage < 0.70:
        alerts.append(
            _alert(
                "EXPECTED_FILER_COVERAGE_LOW",
                "P1",
                "Expected filer coverage below alert threshold",
                "Expected filer coverage is below 70% after the filing deadline.",
                context={
                    "coverage_ratio": coverage,
                    "expected_filer_count": metrics.get("expected_filer_count"),
                    "filed_manager_count": metrics.get("filed_manager_count"),
                    "quarter": readiness.get("latest_usable_quarter"),
                },
            )
        )

    linked = _ratio_value(metrics.get("linked_common_holding_ratio"))
    if linked is not None and linked < 0.50:
        alerts.append(
            _alert(
                "CUSIP_MAPPING_RATIO_CRITICAL",
                "P1",
                "CUSIP mapping ratio below critical threshold",
                "Common share CUSIP mapping ratio is below 50%.",
                context={"linked_common_holding_ratio": linked, "quarter": readiness.get("latest_usable_quarter")},
            )
        )
    elif linked is not None and linked < 0.70:
        alerts.append(
            _alert(
                "CUSIP_MAPPING_RATIO_WARNING",
                "P2",
                "CUSIP mapping ratio below warning threshold",
                "Common share CUSIP mapping ratio is between 50% and 70%.",
                context={"linked_common_holding_ratio": linked, "quarter": readiness.get("latest_usable_quarter")},
            )
        )
    return alerts


def _has_closed_filing_window(session: Session, *, today: date) -> bool:
    closed_cutoff = today - timedelta(days=3)
    return (
        session.query(Filing13F.id)
        .filter(Filing13F.official_filing_deadline.isnot(None))
        .filter(Filing13F.official_filing_deadline <= closed_cutoff)
        .first()
        is not None
    )


def _amendment_alerts(session: Session, *, now: datetime) -> list[dict[str, Any]]:
    return [
        *_stale_filing_alerts(
            session,
            code="AMENDMENT_FAILED_STALE",
            severity="P2",
            title="Failed amendment is stale",
            filters=[Filing13F.amendment_status == "amendment_failed"],
            cutoff=now - timedelta(hours=24),
        ),
        *_stale_filing_alerts(
            session,
            code="AMENDMENT_RESTATEMENT_PENDING_STALE",
            severity="P2",
            title="Restatement amendment is pending too long",
            filters=[
                Filing13F.amendment_status == "amendments_pending",
                func.lower(Filing13F.amendment_type) == "restatement",
            ],
            cutoff=now - timedelta(hours=24),
        ),
        *_stale_filing_alerts(
            session,
            code="AMENDMENT_PENDING_STALE",
            severity="P2",
            title="Amendment is pending too long",
            filters=[
                Filing13F.amendment_status == "amendments_pending",
                func.coalesce(func.lower(Filing13F.amendment_type), "") != "restatement",
            ],
            cutoff=now - timedelta(hours=48),
        ),
    ]


def _needs_review_alerts(session: Session, *, now: datetime) -> list[dict[str, Any]]:
    return _stale_filing_alerts(
        session,
        code="PARSE_NEEDS_REVIEW_STALE",
        severity="P3",
        title="13F filing has been needs_review for more than 7 days",
        filters=[Filing13F.parse_status == "needs_review"],
        cutoff=now - timedelta(days=7),
    )


def _stale_filing_alerts(
    session: Session,
    *,
    code: str,
    severity: str,
    title: str,
    filters: list[Any],
    cutoff: datetime,
) -> list[dict[str, Any]]:
    query = session.query(Filing13F)
    for condition in filters:
        query = query.filter(condition)
    count = query.filter(Filing13F.updated_at < cutoff).count()
    if not count:
        return []
    return [
        _alert(
            code,
            severity,
            title,
            f"{count} filing(s) require follow-up.",
            context={"count": count, "cutoff": cutoff.isoformat()},
        )
    ]


def _running_job_alerts(session: Session, *, now: datetime) -> list[dict[str, Any]]:
    running = session.query(JobRun).filter(JobRun.status == "running").all()
    stale = [
        job
        for job in running
        if job.started_at
        and job.lease_expires_at
        and job.started_at < now - timedelta(seconds=job_timeout_seconds(job.job_type))
        and job.lease_expires_at < now
    ]
    if not stale:
        return []
    return [
        _alert(
            "JOB_RUNNING_TIMEOUT_LEASE_EXPIRED",
            "P2",
            "13F job exceeded timeout and lease expired",
            f"{len(stale)} running 13F job(s) exceeded timeout with expired leases.",
            context={"job_ids": [job.id for job in stale]},
        )
    ]


def _ingest_timeout_retry_alerts(session: Session) -> list[dict[str, Any]]:
    retry_rows = (
        session.query(JobRun.dedupe_key, func.count(JobRun.id).label("failed_count"))
        .filter(JobRun.job_type.in_(["ingest_filing", "ingest_accession"]))
        .filter(JobRun.status == "failed")
        .filter(JobRun.dedupe_key.isnot(None))
        .filter(JobRun.error_message.ilike("%timeout%"))
        .group_by(JobRun.dedupe_key)
        .having(func.count(JobRun.id) >= 3)
        .all()
    )
    return [
        _alert(
            "INGEST_FILING_TIMEOUT_RETRY_EXHAUSTED",
            "P2",
            "13F filing ingest timed out after retries",
            "A filing ingest job timed out at least three times.",
            context={"dedupe_key": row.dedupe_key, "failed_count": row.failed_count},
        )
        for row in retry_rows
    ]


def _alert(code: str, severity: str, title: str, message: str, *, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "message": message,
        "context": context,
    }


def _ratio_value(metric: Any) -> float | None:
    if isinstance(metric, dict):
        return metric.get("value")
    return metric


def _filing_count(session: Session, **filters: Any) -> int:
    query = session.query(Filing13F)
    for field, value in filters.items():
        query = query.filter(getattr(Filing13F, field) == value)
    return query.count()


def _confidential_count(session: Session) -> int:
    return (
        session.query(Filing13F)
        .filter(
            (Filing13F.has_confidential_treatment.is_(True))
            | (Filing13F.confidential_treatment_status.notin_(["none"]))
        )
        .count()
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{round(value * 100)}%"
