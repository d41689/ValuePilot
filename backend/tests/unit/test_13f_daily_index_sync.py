from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from app.models.institutions import (
    EdgarSyncStatus,
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    JobRun,
    JobWorkerHeartbeat,
    NoIndexExpectedDate,
    QualityReport13F,
    RawSourceDocument,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.services.thirteenf_daily_sync import run_daily_index_sync


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "13f" / "daily_index"


class FakeEdgarClient:
    def __init__(self, body: bytes | None = None, *, status_code: int | None = None):
        self.body = body
        self.status_code = status_code
        self.urls: list[str] = []

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        if self.status_code is not None:
            request = httpx.Request("GET", url)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("fetch failed", request=request, response=response)
        assert self.body is not None
        return self.body


def _clear_13f(db_session) -> None:
    # Pre-MVP8-01: persisted Oracle's Lens rows FK-reference
    # InstitutionManager, so they must clear first.
    db_session.query(OraclesLensScoreComponent).delete()
    db_session.query(OraclesLensSignal).delete()
    db_session.query(Holding13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(EdgarSyncStatus).delete()
    db_session.query(NoIndexExpectedDate).delete()
    db_session.query(RawSourceDocument).delete()
    db_session.query(JobWorkerHeartbeat).delete()
    db_session.query(JobRun).delete()
    db_session.query(QualityReport13F).delete()
    db_session.query(InstitutionManagerCikReviewEvent).delete()
    db_session.query(InstitutionManager).delete()
    db_session.flush()


def _manager(db_session, name: str, *, cik: str, status: str = "active") -> InstitutionManager:
    manager = InstitutionManager(
        canonical_name=name,
        legal_name=name,
        edgar_legal_name=name,
        cik=cik,
        status=status,
        match_status="confirmed" if status == "active" else "candidate",
    )
    db_session.add(manager)
    db_session.commit()
    db_session.refresh(manager)
    return manager


def test_daily_index_sync_matches_active_managers_and_enqueues_accession_jobs(db_session):
    _clear_13f(db_session)
    active = _manager(db_session, "Active Tracked Manager", cik="0001067983")
    _manager(db_session, "Inactive Manager", cik="0001035055", status="inactive")
    client = FakeEdgarClient((FIXTURE_DIR / "2024-02-14_form.idx").read_bytes())

    result = run_daily_index_sync(db_session, date(2024, 2, 14), client=client)

    assert result["status"] == "success"
    assert result["filings_seen_count"] == 4
    assert result["tracked_13f_hr_found_count"] == 1
    assert result["tracked_13f_nt_found_count"] == 1
    assert result["matched_accessions"] == [
        {
            "manager_id": active.id,
            "cik": "0001067983",
            "form_type": "13F-HR",
            "accession_number": "0001067983-24-000006",
            "filename": "edgar/data/1067983/0001067983-24-000006.txt",
            "job_enqueued": True,
        },
        {
            "manager_id": active.id,
            "cik": "0001067983",
            "form_type": "13F-NT",
            "accession_number": "0001067983-24-000007",
            "filename": "edgar/data/1067983/0001067983-24-000007.txt",
            "job_enqueued": False,
        },
    ]

    sync = db_session.get(EdgarSyncStatus, date(2024, 2, 14))
    assert sync.status == "success"
    assert sync.raw_document_id is not None
    assert sync.form_idx_url == "https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/form.20240214.idx"

    raw_doc = db_session.get(RawSourceDocument, sync.raw_document_id)
    assert raw_doc.document_type == "daily_form_idx"
    assert raw_doc.source_url == sync.form_idx_url

    jobs = db_session.query(JobRun).order_by(JobRun.id.asc()).all()
    assert len(jobs) == 1
    assert jobs[0].job_type == "ingest_accession"
    assert jobs[0].sync_date == date(2024, 2, 14)
    assert jobs[0].dedupe_key == "0001067983-24-000006"
    assert jobs[0].lock_key == "ingest_accession:0001067983-24-000006"
    assert jobs[0].input_json["accession_no"] == "0001067983-24-000006"


def test_daily_index_sync_requeues_when_prior_accession_job_failed(db_session):
    _clear_13f(db_session)
    active = _manager(db_session, "Active Tracked Manager", cik="0001067983")
    db_session.add(
        JobRun(
            job_type="ingest_accession",
            status="failed",
            trigger_source="daily_sync",
            sync_date=date(2024, 2, 13),
            dedupe_key="0001067983-24-000006",
            lock_key="ingest_accession:0001067983-24-000006",
            input_json={"accession_no": "0001067983-24-000006"},
        )
    )
    db_session.commit()
    client = FakeEdgarClient((FIXTURE_DIR / "2024-02-14_form.idx").read_bytes())

    result = run_daily_index_sync(db_session, date(2024, 2, 14), client=client)

    assert result["jobs_created"] == 1
    assert result["matched_accessions"][0] == {
        "manager_id": active.id,
        "cik": "0001067983",
        "form_type": "13F-HR",
        "accession_number": "0001067983-24-000006",
        "filename": "edgar/data/1067983/0001067983-24-000006.txt",
        "job_enqueued": True,
    }
    jobs = (
        db_session.query(JobRun)
        .filter(JobRun.job_type == "ingest_accession")
        .filter(JobRun.dedupe_key == "0001067983-24-000006")
        .order_by(JobRun.id.asc())
        .all()
    )
    assert [job.status for job in jobs] == ["failed", "queued"]


def test_daily_index_sync_is_idempotent_for_active_accession_jobs(db_session):
    _clear_13f(db_session)
    active = _manager(db_session, "Active Tracked Manager", cik="0001067983")
    body = (FIXTURE_DIR / "2024-02-14_form.idx").read_bytes()

    first = run_daily_index_sync(db_session, date(2024, 2, 14), client=FakeEdgarClient(body))
    second = run_daily_index_sync(db_session, date(2024, 2, 14), client=FakeEdgarClient(body))

    assert first["jobs_created"] == 1
    assert second["jobs_created"] == 0
    assert second["matched_accessions"][0] == {
        "manager_id": active.id,
        "cik": "0001067983",
        "form_type": "13F-HR",
        "accession_number": "0001067983-24-000006",
        "filename": "edgar/data/1067983/0001067983-24-000006.txt",
        "job_enqueued": False,
    }
    assert db_session.query(JobRun).filter(JobRun.job_type == "ingest_accession").count() == 1


def test_expected_no_index_404_marks_sync_no_data(db_session):
    _clear_13f(db_session)
    db_session.add(
        NoIndexExpectedDate(
            date=date(2024, 2, 17),
            reason="weekend",
            source="auto_generated",
            holiday_name="Saturday",
        )
    )
    db_session.commit()

    result = run_daily_index_sync(db_session, date(2024, 2, 17), client=FakeEdgarClient(status_code=404))

    assert result["status"] == "no_data"
    sync = db_session.get(EdgarSyncStatus, date(2024, 2, 17))
    assert sync.status == "no_data"
    assert sync.last_error is None
    assert sync.raw_document_id is None
    assert db_session.query(JobRun).count() == 0


def test_unexpected_404_marks_sync_failed_for_retry(db_session):
    _clear_13f(db_session)

    result = run_daily_index_sync(db_session, date(2024, 2, 16), client=FakeEdgarClient(status_code=404))

    assert result["status"] == "failed"
    sync = db_session.get(EdgarSyncStatus, date(2024, 2, 16))
    assert sync.status == "failed"
    assert "404" in sync.last_error
    assert sync.raw_document_id is None
