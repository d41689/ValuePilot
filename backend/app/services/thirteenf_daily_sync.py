from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.edgar.fetcher import fetch_and_store, load_body
from app.edgar.parsers.form_idx import FormIdxRecord, daily_form_idx_url, parse_daily_13f_form_idx
from app.models.institutions import (
    EdgarSyncStatus,
    InstitutionManager,
    JobRun,
    NoIndexExpectedDate,
)


INGESTIBLE_13F_FORMS = {"13F-HR", "13F-HR/A"}
AUTO_GENERATED_NO_INDEX_REASONS = {"weekend", "federal_holiday"}


def run_daily_index_sync(session: Session, sync_date: date, *, client: Any | None = None) -> dict[str, Any]:
    url = daily_form_idx_url(sync_date)
    now = datetime.now(timezone.utc)
    sync = _sync_status_for_date(session, sync_date)
    sync.status = "running"
    sync.started_at = now
    sync.finished_at = None
    sync.attempt_count = (sync.attempt_count or 0) + 1
    sync.last_error = None
    sync.form_idx_url = url
    session.add(sync)
    session.flush()

    try:
        raw_doc = fetch_and_store(
            session,
            source_system="edgar",
            document_type="daily_form_idx",
            source_url=url,
            client=client,
            force_refresh=True,
        )
        body = load_body(raw_doc)
        records = parse_daily_13f_form_idx(body)
        active_managers = _active_manager_by_cik(session)
        matched = _matched_records(records, active_managers)
        jobs_created = _enqueue_ingest_placeholders(session, sync_date, matched)

        sync.status = "success"
        sync.raw_document_id = raw_doc.id
        sync.filings_seen_count = len(records)
        sync.tracked_13f_hr_found_count = sum(1 for record, _ in matched if record.form_type in INGESTIBLE_13F_FORMS)
        sync.tracked_13f_nt_found_count = sum(1 for record, _ in matched if record.form_type == "13F-NT")
        sync.finished_at = datetime.now(timezone.utc)
        session.add(sync)
        session.commit()
        return _sync_result(sync, matched_accessions=_matched_payload(matched), jobs_created=jobs_created)
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(session, sync, exc)
    except Exception as exc:
        sync.status = "failed"
        sync.finished_at = datetime.now(timezone.utc)
        sync.last_error = str(exc)
        session.add(sync)
        session.commit()
        return _sync_result(sync)


def list_no_index_dates(session: Session, *, year: int | None = None) -> list[dict[str, Any]]:
    query = session.query(NoIndexExpectedDate)
    if year is not None:
        query = query.filter(NoIndexExpectedDate.date >= date(year, 1, 1))
        query = query.filter(NoIndexExpectedDate.date <= date(year, 12, 31))
    rows = query.order_by(NoIndexExpectedDate.date.asc()).all()
    return [_no_index_payload(row) for row in rows]


def create_no_index_date(
    session: Session,
    *,
    expected_date: date,
    reason: str,
    holiday_name: str | None = None,
    note: str | None = None,
    created_by: int | None = None,
) -> dict[str, Any]:
    if reason in AUTO_GENERATED_NO_INDEX_REASONS:
        raise ValueError(f"{reason} rows are auto_generated and cannot be created manually")
    existing = session.get(NoIndexExpectedDate, expected_date)
    if existing is not None:
        raise ValueError("No-index date already exists")

    row = NoIndexExpectedDate(
        date=expected_date,
        reason=reason,
        holiday_name=holiday_name,
        source="admin_manual",
        note=note,
        active=True,
        created_by=created_by,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _no_index_payload(row)


def update_no_index_date(
    session: Session,
    expected_date: date,
    *,
    note: str | None = None,
    active: bool | None = None,
) -> dict[str, Any]:
    row = session.get(NoIndexExpectedDate, expected_date)
    if row is None:
        raise ValueError("No-index date not found")
    if note is not None:
        row.note = note
    if active is not None:
        row.active = active
    session.add(row)
    session.commit()
    session.refresh(row)
    return _no_index_payload(row)


def _sync_status_for_date(session: Session, sync_date: date) -> EdgarSyncStatus:
    sync = session.get(EdgarSyncStatus, sync_date)
    if sync is None:
        sync = EdgarSyncStatus(sync_date=sync_date, status="pending")
        session.add(sync)
        session.flush()
    return sync


def _active_manager_by_cik(session: Session) -> dict[str, InstitutionManager]:
    managers = (
        session.query(InstitutionManager)
        .filter(InstitutionManager.status == "active")
        .filter(InstitutionManager.cik.isnot(None))
        .all()
    )
    return {manager.cik.zfill(10): manager for manager in managers if manager.cik}


def _matched_records(
    records: list[FormIdxRecord],
    active_managers: dict[str, InstitutionManager],
) -> list[tuple[FormIdxRecord, InstitutionManager]]:
    matched: list[tuple[FormIdxRecord, InstitutionManager]] = []
    for record in records:
        manager = active_managers.get(record.cik_padded)
        if manager is not None:
            matched.append((record, manager))
    return matched


def _enqueue_ingest_placeholders(
    session: Session,
    sync_date: date,
    matched: list[tuple[FormIdxRecord, InstitutionManager]],
) -> int:
    created = 0
    for record, manager in matched:
        if record.form_type not in INGESTIBLE_13F_FORMS:
            continue
        accession = record.accession_number
        existing = (
            session.query(JobRun)
            .filter(JobRun.job_type == "ingest_accession")
            .filter(JobRun.dedupe_key == accession)
            .one_or_none()
        )
        if existing is not None:
            continue
        session.add(
            JobRun(
                job_type="ingest_accession",
                status="queued",
                trigger_source="daily_sync",
                sync_date=sync_date,
                dedupe_key=accession,
                lock_key=f"ingest_accession:{accession}",
                input_json={
                    "job_type": "ingest_accession",
                    "accession_no": accession,
                    "manager_id": manager.id,
                    "cik": record.cik_padded,
                    "form_type": record.form_type,
                    "source": "daily_index",
                    "sync_date": sync_date.isoformat(),
                    "filename": record.filename,
                },
            )
        )
        created += 1
    session.flush()
    return created


def _handle_http_error(session: Session, sync: EdgarSyncStatus, exc: httpx.HTTPStatusError) -> dict[str, Any]:
    status_code = exc.response.status_code
    if status_code == 404 and NoIndexExpectedDate.active_for_date(session, sync.sync_date):
        sync.status = "no_data"
        sync.last_error = None
    else:
        sync.status = "failed"
        sync.last_error = f"HTTP {status_code} fetching {sync.form_idx_url}"
    sync.finished_at = datetime.now(timezone.utc)
    sync.raw_document_id = None
    sync.filings_seen_count = 0
    sync.tracked_13f_hr_found_count = 0
    sync.tracked_13f_nt_found_count = 0
    session.add(sync)
    session.commit()
    return _sync_result(sync)


def _sync_result(
    sync: EdgarSyncStatus,
    *,
    matched_accessions: list[dict[str, Any]] | None = None,
    jobs_created: int = 0,
) -> dict[str, Any]:
    return {
        "sync_date": sync.sync_date.isoformat(),
        "status": sync.status,
        "attempt_count": sync.attempt_count,
        "form_idx_url": sync.form_idx_url,
        "raw_document_id": sync.raw_document_id,
        "filings_seen_count": sync.filings_seen_count,
        "tracked_13f_hr_found_count": sync.tracked_13f_hr_found_count,
        "tracked_13f_nt_found_count": sync.tracked_13f_nt_found_count,
        "last_error": sync.last_error,
        "matched_accessions": matched_accessions or [],
        "jobs_created": jobs_created,
    }


def _matched_payload(matched: list[tuple[FormIdxRecord, InstitutionManager]]) -> list[dict[str, Any]]:
    return [
        {
            "manager_id": manager.id,
            "cik": record.cik_padded,
            "form_type": record.form_type,
            "accession_number": record.accession_number,
            "filename": record.filename,
        }
        for record, manager in matched
    ]


def _no_index_payload(row: NoIndexExpectedDate) -> dict[str, Any]:
    return {
        "date": row.date.isoformat(),
        "reason": row.reason,
        "holiday_name": row.holiday_name,
        "source": row.source,
        "note": row.note,
        "active": row.active,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
