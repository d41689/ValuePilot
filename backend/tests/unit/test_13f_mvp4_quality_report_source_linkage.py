"""MVP4-08 quality report source linkage tests."""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

from app.models.institutions import (
    InstitutionManager,
    QualityReport13F,
)
from app.services.thirteenf_admin_dashboard import (
    _latest_quality_report,
    build_quality_reports,
)
from app.services.thirteenf_historical_backfill import (
    enqueue_historical_backfill,
    execute_historical_backfill,
)


_CIK_SEQ = count(9941000000)


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_SEQ)).zfill(10)
    manager = InstitutionManager(
        canonical_name=f"Mv4-08 Mgr {cik}",
        legal_name=f"Mv4-08 Mgr {cik}",
        edgar_legal_name=f"Mv4-08 Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _discovery(accessions_by_quarter: dict[str, list[str]]):
    def _fn(manager: InstitutionManager, quarter: str) -> list[dict]:
        return [
            {"accession_number": acc, "manager_id": manager.id, "report_quarter": quarter}
            for acc in accessions_by_quarter.get(quarter, [])
        ]
    return _fn


def _ingest_succeeds(_session, _manager, meta):
    return {"status": "succeeded", "accession_number": meta["accession_number"]}


def test_dry_run_backfill_stamps_is_dry_run_true_and_source_job_id(db_session):
    manager = _manager(db_session)
    job = enqueue_historical_backfill(
        db_session,
        start_quarter="2022-Q4",
        end_quarter="2022-Q4",
        manager_ids=[manager.id],
        dry_run=True,
    )
    execute_historical_backfill(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (True, []),
        filing_discovery_fn=_discovery({"2022-Q4": ["acc-dry-a"]}),
        ingest_fn=_ingest_succeeds,
    )
    report = (
        db_session.query(QualityReport13F)
        .filter(QualityReport13F.quarter == "2022-Q4")
        .order_by(QualityReport13F.id.desc())
        .first()
    )
    assert report is not None
    assert report.is_dry_run is True
    assert report.source_job_id == job.id


def test_real_backfill_stamps_is_dry_run_false(db_session):
    manager = _manager(db_session)
    job = enqueue_historical_backfill(
        db_session,
        start_quarter="2023-Q1",
        end_quarter="2023-Q1",
        manager_ids=[manager.id],
    )
    execute_historical_backfill(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (True, []),
        filing_discovery_fn=_discovery({"2023-Q1": ["acc-real-a"]}),
        ingest_fn=_ingest_succeeds,
    )
    report = (
        db_session.query(QualityReport13F)
        .filter(QualityReport13F.quarter == "2023-Q1")
        .filter(QualityReport13F.source_job_id == job.id)
        .one()
    )
    assert report.is_dry_run is False


def _seed_quality_report(
    db_session, *, quarter: str, is_dry_run: bool, summary: str,
) -> QualityReport13F:
    report = QualityReport13F(
        quarter=quarter,
        status="passed",
        error_count=0,
        warning_count=0,
        info_count=0,
        summary=summary,
        is_dry_run=is_dry_run,
        checked_at=datetime.now(timezone.utc),
    )
    db_session.add(report)
    db_session.flush()
    return report


def test_build_quality_reports_excludes_dry_run_by_default(db_session):
    _seed_quality_report(
        db_session, quarter="2024-Q4", is_dry_run=False, summary="real run",
    )
    _seed_quality_report(
        db_session, quarter="2024-Q4", is_dry_run=True, summary="dry run preview",
    )
    items = build_quality_reports(db_session, limit=50)
    summaries = [item["summary"] for item in items]
    assert "real run" in summaries
    assert "dry run preview" not in summaries


def test_build_quality_reports_include_dry_run_opt_in(db_session):
    _seed_quality_report(
        db_session, quarter="2024-Q3", is_dry_run=False, summary="real q3",
    )
    _seed_quality_report(
        db_session, quarter="2024-Q3", is_dry_run=True, summary="dry q3",
    )
    items = build_quality_reports(db_session, limit=50, include_dry_run=True)
    summaries = [item["summary"] for item in items]
    assert "real q3" in summaries
    assert "dry q3" in summaries


def test_latest_quality_report_ignores_dry_run_even_when_newer(db_session):
    older_real = QualityReport13F(
        quarter="2024-Q2",
        status="passed",
        error_count=0,
        warning_count=0,
        info_count=0,
        summary="real older",
        is_dry_run=False,
        checked_at=datetime(2024, 8, 1, tzinfo=timezone.utc),
    )
    newer_dry = QualityReport13F(
        quarter="2024-Q2",
        status="passed",
        error_count=0,
        warning_count=0,
        info_count=0,
        summary="dry newer",
        is_dry_run=True,
        checked_at=datetime(2024, 9, 1, tzinfo=timezone.utc),
    )
    db_session.add_all([older_real, newer_dry])
    db_session.flush()

    latest = _latest_quality_report(db_session, "2024-Q2")
    assert latest is not None
    assert latest.id == older_real.id


def test_endpoint_include_dry_run_query_param(client, db_session, user_factory, auth_headers):
    admin = user_factory(email="mvp4-08-admin@example.com", role="admin")
    _seed_quality_report(
        db_session, quarter="2024-Q1", is_dry_run=False, summary="real q1",
    )
    _seed_quality_report(
        db_session, quarter="2024-Q1", is_dry_run=True, summary="dry q1",
    )
    headers = auth_headers(admin)
    default_resp = client.get("/api/v1/admin/13f/quality", headers=headers)
    assert default_resp.status_code == 200
    default_summaries = [item["summary"] for item in default_resp.json()["items"]]
    assert "real q1" in default_summaries
    assert "dry q1" not in default_summaries

    opt_in_resp = client.get(
        "/api/v1/admin/13f/quality?include_dry_run=true", headers=headers,
    )
    assert opt_in_resp.status_code == 200
    opt_in_summaries = [item["summary"] for item in opt_in_resp.json()["items"]]
    assert "dry q1" in opt_in_summaries
