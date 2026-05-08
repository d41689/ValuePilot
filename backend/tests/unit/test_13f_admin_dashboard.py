from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    JobRun,
    JobWorkerHeartbeat,
    QualityReport13F,
    RawSourceDocument,
)
from app.models.stocks import Stock
from app.services.edgar_ingestion import match_cik_candidates, seed_pending_cik_review_fixture
from app.services.edgar_quality import QualityReport, persist_quality_report
from app.services.thirteenf_admin_dashboard import build_quarters, execute_job_payload
from app.services.thirteenf_job_worker import execute_queued_job_once, record_worker_heartbeat


def _clear_13f(db_session) -> None:
    db_session.query(Holding13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(RawSourceDocument).delete()
    db_session.query(JobWorkerHeartbeat).delete()
    db_session.query(JobRun).delete()
    db_session.query(QualityReport13F).delete()
    db_session.query(InstitutionManagerCikReviewEvent).delete()
    db_session.query(InstitutionManager).delete()
    db_session.flush()


def _admin(user_factory):
    return user_factory(email="13f-admin@example.com", role="admin")


def _manager(db_session, name: str = "Test Manager", *, cik: str | None = "0001234567") -> InstitutionManager:
    manager = InstitutionManager(
        cik=cik,
        legal_name=name,
        display_name=name,
        name_normalized=name.lower(),
        match_status="confirmed" if cik else "seeded",
        is_superinvestor=True,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session) -> Stock:
    stock = Stock(ticker="TST", exchange="NYSE", company_name="Test Corp", is_active=True)
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(
    db_session,
    manager: InstitutionManager,
    *,
    accession: str,
    period: date = date(2025, 12, 31),
    form_type: str = "13F-HR",
    is_latest: bool = True,
    raw_infotable_doc_id: int | None = None,
) -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        period_of_report=period,
        filed_at=date(2026, 2, 14),
        form_type=form_type,
        amends_accession_no="0001234567-26-000001" if form_type.endswith("/A") else None,
        version_rank=2 if form_type.endswith("/A") else 1,
        is_latest_for_period=is_latest,
        raw_infotable_doc_id=raw_infotable_doc_id,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _holding(db_session, filing: Filing13F, stock: Stock) -> Holding13F:
    holding = Holding13F(
        filing_id=filing.id,
        row_fingerprint=f"{filing.accession_no}-TST",
        cusip="123456789",
        issuer_name="Test Corp",
        title_of_class="COM",
        value_thousands=1000,
        shares=100,
        share_type="SH",
        stock_id=stock.id,
    )
    db_session.add(holding)
    db_session.flush()
    return holding


def test_admin_readiness_reports_setup_required_without_confirmed_managers(client, db_session, user_factory, auth_headers, monkeypatch):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    monkeypatch.setattr("app.services.thirteenf_admin_dashboard.settings.EDGAR_SCHEDULER_ENABLED", True)

    response = client.get("/api/v1/admin/13f/readiness", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness_level"] == "unavailable"
    assert payload["frontend_behavior"] == "show_setup_required"
    assert payload["current_quarter"]["health"] == "setup_required"
    assert payload["top_task"]["code"] == "NO_CONFIRMED_MANAGER_CIK_WHITELIST"
    assert payload["counts"]["confirmed_managers"] == 0
    checklist_by_code = {item["code"]: item for item in payload["setup_checklist"]}
    assert checklist_by_code["SCHEDULER_CONFIGURED"]["status"] in {"complete", "blocked"}
    assert checklist_by_code["MANAGER_CIKS_CONFIRMED"]["status"] == "blocked"
    assert checklist_by_code["MANAGER_CIKS_CONFIRMED"]["admin_action"] == "Bootstrap whitelist, match CIK, review candidates"


def test_scheduler_disabled_creates_p0_setup_task(client, db_session, user_factory, auth_headers, monkeypatch):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    monkeypatch.setattr("app.services.thirteenf_admin_dashboard.settings.EDGAR_SCHEDULER_ENABLED", False)

    response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))

    assert response.status_code == 200
    tasks = response.json()["items"]
    scheduler_task = next(item for item in tasks if item["code"] == "EDGAR_SCHEDULER_DISABLED")
    assert scheduler_task["priority"] == "P0"
    assert "Enable EDGAR_SCHEDULER_ENABLED" in scheduler_task["recommended_action"]


def test_consumer_readiness_exposes_only_safe_fields(client, db_session):
    _clear_13f(db_session)
    response = client.get("/api/v1/13f/readiness")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "readiness_level",
        "frontend_behavior",
        "latest_usable_quarter",
        "current_quarter",
        "warnings",
        "historical_depth_quarters",
        "historical_depth_capabilities",
        "amendment_status",
    }
    assert "blockers" not in payload
    assert "counts" not in payload
    assert "last_successful_job_at" not in payload
    assert "setup_checklist" not in payload


def test_amendment_pending_creates_p1_task_and_needs_review_health(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    _filing(db_session, manager, accession="0001234567-26-000001", is_latest=False)
    _filing(db_session, manager, accession="0001234567-26-000002", form_type="13F-HR/A")
    db_session.commit()

    response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))

    assert response.status_code == 200
    tasks = response.json()["items"]
    amendment_task = next(item for item in tasks if item["code"] == "AMENDMENT_PENDING_OR_FAILED")
    assert amendment_task["priority"] == "P1"
    assert "Reprocess amendment" in amendment_task["recommended_action"]


def test_amendment_applied_does_not_create_admin_task(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    failed_manager = _manager(db_session, name="Failed Amendment Manager", cik="0007654321")
    pending_manager = _manager(db_session, name="Pending Amendment Manager", cik="0007654322")
    stock = _stock(db_session)
    doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=failed_manager.cik,
        accession_no="0001234567-26-000002",
        source_url="https://example.test/amendment.xml",
        http_status=200,
        raw_sha256="abc",
        body_path="/tmp/amendment.xml",
        parse_status="parsed",
        parsed_at=datetime.now(timezone.utc),
    )
    db_session.add(doc)
    db_session.flush()
    _filing(db_session, manager, accession="0001234567-26-000001", is_latest=False)
    amendment = _filing(
        db_session,
        manager,
        accession="0001234567-26-000002",
        form_type="13F-HR/A",
        raw_infotable_doc_id=doc.id,
    )
    _holding(db_session, amendment, stock)
    db_session.commit()

    response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))

    assert response.status_code == 200
    assert all(item["code"] != "AMENDMENT_PENDING_OR_FAILED" for item in response.json()["items"])


def test_amendments_endpoint_lists_pending_failed_and_applied_accessions(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    failed_manager = _manager(db_session, name="Failed Amendment Manager", cik="0007654321")
    pending_manager = _manager(db_session, name="Pending Amendment Manager", cik="0007654322")
    stock = _stock(db_session)
    parsed_doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=manager.cik,
        accession_no="0001234567-26-000002",
        source_url="https://example.test/amendment-applied.xml",
        http_status=200,
        raw_sha256="parsed",
        body_path="/tmp/amendment-applied.xml",
        parse_status="parsed",
        parsed_at=datetime.now(timezone.utc),
    )
    failed_doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=failed_manager.cik,
        accession_no="0007654321-26-000003",
        source_url="https://example.test/amendment-failed.xml",
        http_status=200,
        raw_sha256="failed",
        body_path="/tmp/amendment-failed.xml",
        parse_status="failed",
        error_message="bad infotable XML",
        parsed_at=datetime.now(timezone.utc),
    )
    db_session.add_all([parsed_doc, failed_doc])
    db_session.flush()
    _filing(db_session, manager, accession="0001234567-26-000001", is_latest=False)
    applied = _filing(
        db_session,
        manager,
        accession="0001234567-26-000002",
        form_type="13F-HR/A",
        is_latest=True,
        raw_infotable_doc_id=parsed_doc.id,
    )
    _holding(db_session, applied, stock)
    _filing(db_session, failed_manager, accession="0007654321-26-000001", is_latest=False)
    failed = _filing(
        db_session,
        failed_manager,
        accession="0007654321-26-000003",
        form_type="13F-HR/A",
        is_latest=True,
        raw_infotable_doc_id=failed_doc.id,
    )
    _filing(db_session, pending_manager, accession="0007654322-26-000001", is_latest=False)
    pending = _filing(
        db_session,
        pending_manager,
        accession="0007654322-26-000004",
        form_type="13F-HR/A",
        is_latest=True,
    )
    db_session.commit()

    response = client.get("/api/v1/admin/13f/amendments", headers=auth_headers(admin))

    assert response.status_code == 200
    by_accession = {item["accession_no"]: item for item in response.json()["items"]}
    assert by_accession[applied.accession_no]["status"] == "applied"
    assert by_accession[applied.accession_no]["holdings_count"] == 1
    assert by_accession[failed.accession_no]["status"] == "failed"
    assert by_accession[failed.accession_no]["recommended_job"]["job_type"] == "reprocess_amendment"
    assert by_accession[failed.accession_no]["raw_infotable"]["parse_status"] == "failed"
    assert by_accession[failed.accession_no]["raw_infotable"]["error_message"] == "bad infotable XML"
    assert by_accession[pending.accession_no]["status"] == "pending"
    assert by_accession[pending.accession_no]["recommended_job"]["accession_no"] == pending.accession_no
    assert by_accession[pending.accession_no]["supersedes_accession_no"] == "0001234567-26-000001"


def test_amendment_detail_endpoint_returns_single_accession(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Amendment Manager")
    _filing(db_session, manager, accession="0001234567-26-000001", is_latest=False)
    filing = _filing(db_session, manager, accession="0001234567-26-000002", form_type="13F-HR/A")
    db_session.commit()

    response = client.get(f"/api/v1/admin/13f/amendments/{filing.accession_no}", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()
    assert payload["accession_no"] == filing.accession_no
    assert payload["manager"]["legal_name"] == "Amendment Manager"
    assert payload["quarter"] == "2025-Q4"
    assert payload["status"] == "pending"
    assert payload["recommended_job"] == {
        "job_type": "reprocess_amendment",
        "accession_no": filing.accession_no,
    }


def test_duplicate_active_job_lock_returns_conflict(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    job = JobRun(
        job_type="reprocess_amendment",
        status="running",
        requested_by_user_id=admin.id,
        trigger_source="manual",
        dedupe_key="reprocess_amendment:0001234567-26-000002",
        lock_key="reprocess_amendment:0001234567-26-000002",
        input_json={"accession_no": "0001234567-26-000002"},
    )
    db_session.add(job)
    db_session.commit()

    response = client.post(
        "/api/v1/admin/13f/jobs",
        headers=auth_headers(admin),
        json={
            "job_type": "reprocess_amendment",
            "accession_no": "0001234567-26-000002",
            "dry_run": False,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["active_job_id"] == job.id


def test_job_trigger_queues_job_without_running_it(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)

    response = client.post(
        "/api/v1/admin/13f/jobs",
        headers=auth_headers(admin),
        json={"job_type": "quality_check", "quarter": "2025-Q4"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["started_at"] is None
    assert payload["finished_at"] is None
    assert payload["worker_id"] is None


def test_job_trigger_dry_run_returns_safe_preview_without_queueing(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)

    response = client.post(
        "/api/v1/admin/13f/jobs",
        headers=auth_headers(admin),
        json={"job_type": "ingest_holdings", "quarter": "2025-Q4", "dry_run": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["job_type"] == "ingest_holdings"
    assert payload["lock_key"] == "ingest_holdings:2025-Q4"
    assert payload["preview"]["requires_confirmation"] is True
    assert payload["preview"]["target_quarter"] == "2025-Q4"
    assert payload["preview"]["rate_limit_warning"]
    assert db_session.query(JobRun).count() == 0


def test_worker_executes_queued_job_and_records_heartbeat(db_session, monkeypatch):
    _clear_13f(db_session)
    job = JobRun(
        job_type="quality_check",
        status="queued",
        trigger_source="manual",
        dedupe_key="quality_check:2025-Q4",
        lock_key="quality_check:2025-Q4",
        quarter="2025-Q4",
        input_json={"job_type": "quality_check", "quarter": "2025-Q4"},
    )
    db_session.add(job)
    db_session.commit()

    def fake_execute_job(session, job_type, payload):
        assert job_type == "quality_check"
        return {"status": "succeeded", "quality_errors": 0, "quality_warnings": 1}

    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.execute_job_payload",
        fake_execute_job,
    )

    result = execute_queued_job_once(db_session, worker_id="test-worker")

    assert result is not None
    assert result.status == "succeeded"
    assert result.worker_id == "test-worker"
    assert result.summary_json == {"quality_errors": 0, "quality_warnings": 1}
    heartbeat = db_session.get(JobWorkerHeartbeat, "test-worker")
    assert heartbeat is not None
    assert heartbeat.status == "idle"


def test_job_detail_endpoint_returns_input_summary_and_worker(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    job = JobRun(
        job_type="quality_check",
        status="succeeded",
        requested_by_user_id=admin.id,
        trigger_source="manual",
        dedupe_key="quality_check:2025-Q4",
        lock_key="quality_check:2025-Q4",
        quarter="2025-Q4",
        worker_id="test-worker",
        input_json={"job_type": "quality_check", "quarter": "2025-Q4"},
        summary_json={"quality_errors": 0},
    )
    db_session.add(job)
    db_session.commit()

    response = client.get(f"/api/v1/admin/13f/jobs/{job.id}", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == job.id
    assert payload["worker_id"] == "test-worker"
    assert payload["input_json"]["quarter"] == "2025-Q4"
    assert payload["summary_json"]["quality_errors"] == 0


def test_job_detail_endpoint_returns_timeline_events_and_retry_targets(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    now = datetime.now(timezone.utc)
    job = JobRun(
        job_type="ingest_holdings",
        status="partial_success",
        requested_by_user_id=admin.id,
        trigger_source="manual",
        dedupe_key="ingest_holdings:2025-Q4",
        lock_key="ingest_holdings:2025-Q4",
        quarter="2025-Q4",
        worker_id="test-worker",
        started_at=now - timedelta(minutes=10),
        heartbeat_at=now - timedelta(minutes=1),
        finished_at=now,
        input_json={"job_type": "ingest_holdings", "quarter": "2025-Q4"},
        summary_json={
            "filings_processed": 3,
            "filings_failed": 1,
            "failed_accessions": [
                {"accession_no": "0001234567-26-000002", "error": "broken infotable"},
            ],
            "issues": [
                {
                    "check": "parse_failure",
                    "severity": "error",
                    "accession_no": "0001234567-26-000003",
                    "detail": "missing issuer",
                }
            ],
        },
    )
    db_session.add(job)
    db_session.commit()

    response = client.get(f"/api/v1/admin/13f/jobs/{job.id}", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()
    event_types = [item["event_type"] for item in payload["events"]]
    assert "job_created" in event_types
    assert "job_started" in event_types
    assert "job_finished" in event_types
    failed_event = next(item for item in payload["events"] if item["event_type"] == "accession_failed")
    assert failed_event["accession_no"] == "0001234567-26-000002"
    assert failed_event["message"] == "broken infotable"
    issue_event = next(item for item in payload["events"] if item["event_type"] == "quality_issue")
    assert issue_event["accession_no"] == "0001234567-26-000003"
    assert issue_event["severity"] == "error"
    assert payload["retry_targets"] == [
        {
            "job_type": "ingest_accession",
            "accession_no": "0001234567-26-000002",
            "label": "Retry accession 0001234567-26-000002",
        }
    ]


def test_enrichment_job_detail_exposes_enrichment_retry_target(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    job = JobRun(
        job_type="enrich_metadata",
        status="failed",
        requested_by_user_id=admin.id,
        trigger_source="pipeline",
        dedupe_key="enrich_metadata:2025-Q4",
        lock_key="enrich_metadata:2025-Q4",
        quarter="2025-Q4",
        error_message="Dataroma unavailable",
        input_json={"job_type": "enrich_metadata", "quarter": "2025-Q4"},
    )
    db_session.add(job)
    db_session.commit()

    response = client.get(f"/api/v1/admin/13f/jobs/{job.id}", headers=auth_headers(admin))

    assert response.status_code == 200
    assert response.json()["retry_targets"] == [
        {
            "job_type": "enrich_metadata",
            "quarter": "2025-Q4",
            "label": "Retry Enrichment for 2025-Q4",
        }
    ]
    task_response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))
    task = next(item for item in task_response.json()["items"] if item["code"] == "RECENT_JOB_FAILED")
    assert task["recommended_action"] == "Review job timeline and retry the failed stage."
    assert task["metadata"]["failed_accessions_count"] == 0
    assert task["metadata"]["retry_targets"] == [
        {
            "job_type": "enrich_metadata",
            "quarter": "2025-Q4",
            "label": "Retry Enrichment for 2025-Q4",
        }
    ]


def test_failed_job_creates_admin_alert_task(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    job = JobRun(
        job_type="ingest_holdings",
        status="failed",
        requested_by_user_id=admin.id,
        trigger_source="scheduler",
        dedupe_key="ingest_holdings:2025-Q4",
        lock_key="ingest_holdings:2025-Q4",
        quarter="2025-Q4",
        error_message="SEC parser failed",
        input_json={"job_type": "ingest_holdings", "quarter": "2025-Q4"},
        summary_json={
            "failed_accessions": [
                {"accession_no": "0001234567-26-000002", "error": "broken infotable"},
            ]
        },
    )
    db_session.add(job)
    db_session.commit()

    response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))

    assert response.status_code == 200
    task = next(item for item in response.json()["items"] if item["code"] == "RECENT_JOB_FAILED")
    assert task["priority"] == "P1"
    assert task["metadata"]["job_id"] == job.id
    assert task["metadata"]["job_type"] == "ingest_holdings"
    assert task["metadata"]["status"] == "failed"
    assert task["metadata"]["quarter"] == "2025-Q4"
    assert task["metadata"]["failed_accessions_count"] == 1
    assert task["metadata"]["retry_targets"][0]["accession_no"] == "0001234567-26-000002"


def test_partial_success_job_creates_lower_priority_admin_alert_task(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    job = JobRun(
        job_type="ingest_holdings",
        status="partial_success",
        requested_by_user_id=admin.id,
        trigger_source="manual",
        dedupe_key="ingest_holdings:2025-Q4",
        lock_key="ingest_holdings:2025-Q4",
        quarter="2025-Q4",
        input_json={"job_type": "ingest_holdings", "quarter": "2025-Q4"},
        summary_json={
            "filings_processed": 3,
            "filings_failed": 1,
            "failed_accessions": [
                {"accession_no": "0001234567-26-000002", "error": "broken infotable"},
            ],
        },
    )
    db_session.add(job)
    db_session.commit()

    response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))

    assert response.status_code == 200
    task = next(item for item in response.json()["items"] if item["code"] == "RECENT_JOB_PARTIAL_SUCCESS")
    assert task["priority"] == "P2"
    assert task["metadata"]["job_id"] == job.id
    assert task["metadata"]["failed_accessions_count"] == 1


def test_queued_job_without_active_worker_creates_admin_task(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    queued_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    job = JobRun(
        job_type="ingest_holdings",
        status="queued",
        requested_by_user_id=admin.id,
        trigger_source="manual",
        dedupe_key="ingest_holdings:2025-Q4",
        lock_key="ingest_holdings:2025-Q4",
        quarter="2025-Q4",
        input_json={"job_type": "ingest_holdings", "quarter": "2025-Q4"},
        created_at=queued_at,
    )
    db_session.add(job)
    db_session.commit()

    response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))

    assert response.status_code == 200
    task = next(item for item in response.json()["items"] if item["code"] == "JOB_WORKER_UNAVAILABLE")
    assert task["priority"] == "P1"
    assert task["metadata"]["queued_jobs_count"] == 1
    assert task["metadata"]["oldest_queued_job_id"] == job.id
    assert task["metadata"]["oldest_queued_job_type"] == "ingest_holdings"
    assert task["metadata"]["active_worker_count"] == 0


def test_stuck_queued_job_with_active_worker_creates_admin_task(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    queued_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    record_worker_heartbeat(db_session, worker_id="idle-worker", status="idle")
    job = JobRun(
        job_type="quality_check",
        status="queued",
        requested_by_user_id=admin.id,
        trigger_source="manual",
        dedupe_key="quality_check:2025-Q4",
        lock_key="quality_check:2025-Q4",
        quarter="2025-Q4",
        input_json={"job_type": "quality_check", "quarter": "2025-Q4"},
        created_at=queued_at,
    )
    db_session.add(job)
    db_session.commit()

    response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))

    assert response.status_code == 200
    task = next(item for item in response.json()["items"] if item["code"] == "STUCK_QUEUED_JOB")
    assert task["priority"] == "P2"
    assert task["metadata"]["oldest_queued_job_id"] == job.id
    assert task["metadata"]["active_worker_count"] == 1
    assert task["metadata"]["oldest_queued_seconds"] >= 60


def test_stale_running_job_creates_admin_task_and_can_release_lock(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    stale_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    job = JobRun(
        job_type="quality_check",
        status="running",
        requested_by_user_id=admin.id,
        trigger_source="manual",
        dedupe_key="quality_check:2025-Q4",
        lock_key="quality_check:2025-Q4",
        quarter="2025-Q4",
        worker_id="dead-worker",
        started_at=stale_at,
        heartbeat_at=stale_at,
        input_json={"job_type": "quality_check", "quarter": "2025-Q4"},
    )
    db_session.add(job)
    db_session.commit()

    task_response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))

    assert task_response.status_code == 200
    task = next(item for item in task_response.json()["items"] if item["code"] == "STALE_RUNNING_JOB")
    assert task["priority"] == "P1"
    assert task["metadata"]["stale_job_id"] == job.id
    assert task["metadata"]["stale_job_type"] == "quality_check"
    assert task["metadata"]["stale_job_worker_id"] == "dead-worker"

    detail_response = client.get(f"/api/v1/admin/13f/jobs/{job.id}", headers=auth_headers(admin))
    assert detail_response.status_code == 200
    assert detail_response.json()["can_release_stale_lock"] is True

    release_response = client.post(f"/api/v1/admin/13f/jobs/{job.id}/release-stale-lock", headers=auth_headers(admin))

    assert release_response.status_code == 200
    released = release_response.json()
    assert released["status"] == "failed"
    assert released["can_release_stale_lock"] is False
    assert "Released stale running job lock" in released["error_message"]
    assert released["heartbeat_at"] == stale_at.isoformat()

    replacement = client.post(
        "/api/v1/admin/13f/jobs",
        headers=auth_headers(admin),
        json={"job_type": "quality_check", "quarter": "2025-Q4"},
    )
    assert replacement.status_code == 200
    assert replacement.json()["status"] == "queued"


def test_release_stale_lock_rejects_fresh_running_job(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    now = datetime.now(timezone.utc)
    job = JobRun(
        job_type="quality_check",
        status="running",
        requested_by_user_id=admin.id,
        trigger_source="manual",
        dedupe_key="quality_check:2025-Q4",
        lock_key="quality_check:2025-Q4",
        quarter="2025-Q4",
        worker_id="live-worker",
        started_at=now,
        heartbeat_at=now,
        input_json={"job_type": "quality_check", "quarter": "2025-Q4"},
    )
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/api/v1/admin/13f/jobs/{job.id}/release-stale-lock", headers=auth_headers(admin))

    assert response.status_code == 400
    assert "not stale" in response.json()["detail"]
    db_session.refresh(job)
    assert job.status == "running"


def test_cancel_queued_job_releases_active_lock(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    job = JobRun(
        job_type="quality_check",
        status="queued",
        requested_by_user_id=admin.id,
        trigger_source="manual",
        dedupe_key="quality_check:2025-Q4",
        lock_key="quality_check:2025-Q4",
        quarter="2025-Q4",
        input_json={"job_type": "quality_check", "quarter": "2025-Q4"},
    )
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/api/v1/admin/13f/jobs/{job.id}/cancel", headers=auth_headers(admin))

    assert response.status_code == 200
    assert response.json()["status"] == "canceled"
    replacement = client.post(
        "/api/v1/admin/13f/jobs",
        headers=auth_headers(admin),
        json={"job_type": "quality_check", "quarter": "2025-Q4"},
    )
    assert replacement.status_code == 200
    assert replacement.json()["status"] == "queued"


def test_worker_heartbeat_endpoint_marks_stale_workers(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    record_worker_heartbeat(
        db_session,
        worker_id="stale-worker",
        status="idle",
        now=old_time,
    )

    response = client.get("/api/v1/admin/13f/workers", headers=auth_headers(admin))

    assert response.status_code == 200
    worker = response.json()["items"][0]
    assert worker["worker_id"] == "stale-worker"
    assert worker["status"] == "stale"


def test_active_quarter_job_marks_quarter_health_ingesting(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    _manager(db_session)
    db_session.add(
        JobRun(
            job_type="ingest_holdings",
            status="running",
            requested_by_user_id=admin.id,
            trigger_source="manual",
            dedupe_key="ingest_holdings:2025-Q4",
            lock_key="ingest_holdings:2025-Q4",
            quarter="2025-Q4",
            input_json={"job_type": "ingest_holdings", "quarter": "2025-Q4"},
        )
    )
    db_session.commit()

    response = client.get("/api/v1/admin/13f/quarters/2025-Q4", headers=auth_headers(admin))

    assert response.status_code == 200
    assert response.json()["quarter_health"] == "ingesting"


def test_post_deadline_missing_current_data_with_prior_history_is_stale(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    stock = _stock(db_session)
    prior = _filing(db_session, manager, accession="0001234567-26-000001", period=date(2025, 12, 31))
    _holding(db_session, prior, stock)
    db_session.commit()

    quarters = build_quarters(db_session, today=date(2026, 5, 16), limit=2)

    current = next(item for item in quarters if item["quarter"] == "2026-Q2")
    latest_usable = next(item for item in quarters if item["quarter"] == "2026-Q1")
    assert current["quarter_phase"] == "pre_window"
    assert latest_usable["quarter_phase"] == "post_deadline"
    assert latest_usable["quarter_health"] == "stale"


def test_no_holdings_exposes_unavailable_reason_for_linked_ratio(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    _manager(db_session)
    db_session.commit()

    response = client.get("/api/v1/admin/13f/quarters/2025-Q4", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()
    assert payload["linked_holding_ratio"] is None
    assert payload["linked_holding_unavailable_reason"] == "NO_HOLDINGS_PARSED"


def test_manager_payload_includes_cik_candidate_audit_fields(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Bill Ackman - Pershing Square", cik=None)
    manager.match_status = "candidate"
    manager.candidate_cik = "0001336528"
    manager.candidate_legal_name = "PERSHING SQUARE CAPITAL MANAGEMENT, L.P."
    manager.candidate_similarity_score = 0.82
    manager.candidate_source = "edgar_browse_company"
    manager.candidate_evidence_url = "https://www.sec.gov/cgi-bin/browse-edgar?company=Pershing%20Square"
    manager.candidate_found_at = datetime.now(timezone.utc)
    manager.prior_rejected_candidates = [{"cik": "0000000001", "legal_name": "Wrong Manager"}]
    db_session.commit()

    response = client.get("/api/v1/admin/13f/managers", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()["items"][0]
    assert payload["candidate_cik"] == "0001336528"
    assert payload["candidate_legal_name"] == "PERSHING SQUARE CAPITAL MANAGEMENT, L.P."
    assert payload["candidate_similarity_score"] == 0.82
    assert payload["candidate_source"] == "edgar_browse_company"
    assert payload["candidate_evidence_url"].startswith("https://www.sec.gov/cgi-bin/browse-edgar")
    assert payload["prior_rejected_candidates"][0]["cik"] == "0000000001"


def test_seed_pending_cik_review_fixture_creates_idempotent_candidate(db_session):
    _clear_13f(db_session)

    first_count = seed_pending_cik_review_fixture(db_session)
    db_session.commit()
    second_count = seed_pending_cik_review_fixture(db_session)
    db_session.commit()

    manager = (
        db_session.query(InstitutionManager)
        .filter_by(dataroma_code="QA_PENDING_CIK")
        .one()
    )
    assert first_count == 1
    assert second_count == 1
    assert manager.match_status == "candidate"
    assert manager.cik is None
    assert manager.candidate_cik == "0001336528"
    assert manager.candidate_legal_name == "PERSHING SQUARE CAPITAL MANAGEMENT, L.P."
    assert manager.candidate_source == "qa_fixture"
    assert manager.candidate_found_at is not None


def test_retry_manager_cik_search_with_edited_name_preserves_candidate_review(
    client,
    db_session,
    user_factory,
    auth_headers,
    monkeypatch,
):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Ambiguous Manager", cik=None)
    manager.match_status = "seeded"
    db_session.commit()

    monkeypatch.setattr(
        "app.services.edgar_ingestion._search_edgar_by_company_name",
        lambda client, company_name: [("Edited Capital Management LP", "0007654321")],
    )

    response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/retry-cik-search",
        headers=auth_headers(admin),
        json={"search_name": "Edited Capital Management", "note": "Use legal manager name"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["match_status"] == "candidate"
    assert payload["cik"] is None
    assert payload["candidate_cik"] == "0007654321"
    assert payload["candidate_source"] == "edgar_browse_company_edited"
    assert payload["candidate_similarity_score"] >= 0.6
    event_response = client.get(
        f"/api/v1/admin/13f/managers/{manager.id}/cik-review-events",
        headers=auth_headers(admin),
    )
    assert event_response.status_code == 200
    assert event_response.json()["items"][0]["event_type"] == "retry_candidate_search"
    assert event_response.json()["items"][0]["evidence"]["search_name"] == "Edited Capital Management"


def test_retry_manager_cik_search_rejects_confirmed_manager_without_revocation(
    client,
    db_session,
    user_factory,
    auth_headers,
    monkeypatch,
):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Confirmed Manager", cik="0001234567")
    db_session.commit()

    monkeypatch.setattr(
        "app.services.edgar_ingestion._search_edgar_by_company_name",
        lambda client, company_name: [("Edited Capital Management LP", "0007654321")],
    )

    response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/retry-cik-search",
        headers=auth_headers(admin),
        json={"search_name": "Edited Capital Management", "note": "Use legal manager name"},
    )

    assert response.status_code == 400
    assert "revoke-cik" in response.json()["detail"]
    db_session.refresh(manager)
    assert manager.match_status == "confirmed"
    assert manager.cik == "0001234567"
    events = db_session.query(InstitutionManagerCikReviewEvent).filter_by(manager_id=manager.id).all()
    assert events == []


def test_match_cik_candidates_writes_candidate_audit_metadata(db_session, monkeypatch):
    _clear_13f(db_session)
    manager = _manager(db_session, name="Bill Ackman - Pershing Square", cik=None)
    db_session.commit()

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.services.edgar_ingestion.EdgarClient", DummyClient)
    monkeypatch.setattr(
        "app.services.edgar_ingestion._search_edgar_by_company_name",
        lambda client, company_name: [("PERSHING SQUARE CAPITAL MANAGEMENT, L.P.", "0001336528")],
    )
    monkeypatch.setattr("app.services.edgar_ingestion._name_score", lambda left, right: 0.72)

    updated = match_cik_candidates(db_session, min_score=0.6)

    assert updated == 1
    db_session.refresh(manager)
    assert manager.match_status == "candidate"
    assert manager.cik is None
    assert manager.candidate_cik == "0001336528"
    assert manager.candidate_legal_name == "PERSHING SQUARE CAPITAL MANAGEMENT, L.P."
    assert manager.candidate_similarity_score is not None
    assert manager.candidate_source == "edgar_browse_company"
    assert "browse-edgar" in manager.candidate_evidence_url
    assert manager.candidate_found_at is not None


def test_confirm_manager_cik_records_reviewer_note_and_candidate_evidence(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Bill Ackman - Pershing Square", cik=None)
    manager.match_status = "candidate"
    manager.candidate_cik = "0001336528"
    manager.candidate_legal_name = "PERSHING SQUARE CAPITAL MANAGEMENT, L.P."
    manager.candidate_similarity_score = 0.82
    manager.candidate_source = "edgar_browse_company"
    manager.candidate_evidence_url = "https://www.sec.gov/cgi-bin/browse-edgar?company=Pershing%20Square"
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/confirm-cik",
        headers=auth_headers(admin),
        json={"note": "SEC entity page matches Dataroma manager"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["match_status"] == "confirmed"
    assert payload["cik"] == "0001336528"
    assert payload["reviewed_by_user_id"] == admin.id
    assert payload["review_note"] == "SEC entity page matches Dataroma manager"
    db_session.refresh(manager)
    assert manager.reviewed_by_user_id == admin.id
    assert manager.reviewed_at is not None
    assert manager.legal_name == "PERSHING SQUARE CAPITAL MANAGEMENT, L.P."


def test_reject_manager_cik_retains_prior_rejected_candidate(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Bill Ackman - Pershing Square", cik=None)
    manager.match_status = "candidate"
    manager.candidate_cik = "0001336528"
    manager.candidate_legal_name = "PERSHING SQUARE CAPITAL MANAGEMENT, L.P."
    manager.candidate_similarity_score = 0.82
    manager.candidate_source = "edgar_browse_company"
    manager.candidate_evidence_url = "https://www.sec.gov/cgi-bin/browse-edgar?company=Pershing%20Square"
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/reject-cik",
        headers=auth_headers(admin),
        json={"note": "CIK belongs to a different adviser"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["match_status"] == "rejected"
    assert payload["reviewed_by_user_id"] == admin.id
    assert payload["prior_rejected_candidates"][0]["cik"] == "0001336528"
    assert payload["prior_rejected_candidates"][0]["review_note"] == "CIK belongs to a different adviser"


def test_revoke_confirmed_manager_cik_records_audit_event_and_blocks_ingestion(
    client,
    db_session,
    user_factory,
    auth_headers,
):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Wrong CIK Manager", cik="0001336528")
    _filing(db_session, manager, accession="0001336528-26-000001", period=date(2025, 12, 31))
    _filing(db_session, manager, accession="0001336528-25-000001", period=date(2025, 9, 30))
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/revoke-cik",
        headers=auth_headers(admin),
        json={"note": "CIK belongs to a different SEC entity"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["match_status"] == "revoked"
    assert payload["cik"] is None
    assert payload["review_note"] == "CIK belongs to a different SEC entity"
    assert payload["latest_cik_review_event"]["event_type"] == "revoke_confirmed_cik"
    assert payload["latest_cik_review_event"]["old_cik"] == "0001336528"
    assert payload["latest_cik_review_event"]["affected_filings_count"] == 2
    assert payload["latest_cik_review_event"]["affected_quarters"] == ["2025-Q3", "2025-Q4"]
    assert payload["latest_cik_review_event"]["requires_downstream_review"] is True
    assert db_session.query(InstitutionManager).filter_by(match_status="confirmed").count() == 0


def test_revoke_confirmed_manager_cik_requires_review_note(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Wrong CIK Manager", cik="0001336528")
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/revoke-cik",
        headers=auth_headers(admin),
        json={"note": ""},
    )

    assert response.status_code == 400
    assert "note is required" in response.json()["detail"]


def test_manager_review_events_endpoint_returns_recent_cik_events(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Event Manager", cik="0001336528")
    event = InstitutionManagerCikReviewEvent(
        manager_id=manager.id,
        event_type="confirm_candidate_cik",
        old_cik=None,
        new_cik="0001336528",
        old_match_status="candidate",
        new_match_status="confirmed",
        reviewed_by_user_id=admin.id,
        note="Confirmed from SEC evidence",
        affected_filings_count=0,
        affected_quarters=[],
        requires_downstream_review=False,
    )
    db_session.add(event)
    db_session.commit()

    response = client.get(f"/api/v1/admin/13f/managers/{manager.id}/cik-review-events", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()["items"][0]
    assert payload["event_type"] == "confirm_candidate_cik"
    assert payload["new_cik"] == "0001336528"
    assert payload["note"] == "Confirmed from SEC evidence"


def test_revoked_cik_downstream_review_creates_admin_repair_task(
    client,
    db_session,
    user_factory,
    auth_headers,
):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Revoked CIK Manager", cik="0001336528")
    _filing(db_session, manager, accession="0001336528-26-000001", period=date(2025, 12, 31))
    db_session.commit()
    revoke_response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/revoke-cik",
        headers=auth_headers(admin),
        json={"note": "Wrong SEC entity"},
    )
    assert revoke_response.status_code == 200

    task_response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))

    assert task_response.status_code == 200
    tasks = task_response.json()["items"]
    repair_task = next(item for item in tasks if item["code"] == "REVOKED_CIK_DOWNSTREAM_REVIEW")
    assert repair_task["priority"] == "P1"
    assert repair_task["metadata"]["manager_id"] == manager.id
    assert repair_task["metadata"]["old_cik"] == "0001336528"
    assert repair_task["metadata"]["affected_filings_count"] == 1
    assert repair_task["metadata"]["affected_quarters"] == ["2025-Q4"]
    assert "Reconfirm the correct CIK" in repair_task["recommended_action"]


def test_revoked_cik_marks_affected_quarter_needs_review_and_readiness_warning(
    client,
    db_session,
    user_factory,
    auth_headers,
):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Revoked CIK Manager", cik="0001336528")
    _manager(db_session, name="Still Confirmed Manager", cik="0001336529")
    filing = _filing(db_session, manager, accession="0001336528-26-000001", period=date(2025, 12, 31))
    _holding(db_session, filing, _stock(db_session))
    db_session.commit()

    revoke_response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/revoke-cik",
        headers=auth_headers(admin),
        json={"note": "Wrong SEC entity"},
    )
    assert revoke_response.status_code == 200

    quarter_response = client.get("/api/v1/admin/13f/quarters/2025-Q4/detail", headers=auth_headers(admin))
    readiness_response = client.get("/api/v1/admin/13f/readiness", headers=auth_headers(admin))

    assert quarter_response.status_code == 200
    assert quarter_response.json()["summary"]["quarter_health"] == "needs_review"
    assert quarter_response.json()["summary"]["revoked_cik_review_required"] is True
    assert readiness_response.status_code == 200
    assert any("Revoked CIK" in warning["message"] for warning in readiness_response.json()["warnings"])


def test_revoked_cik_does_not_outrank_setup_required_when_no_confirmed_managers(
    client,
    db_session,
    user_factory,
    auth_headers,
):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Only Confirmed Manager", cik="0001336528")
    filing = _filing(db_session, manager, accession="0001336528-26-000001", period=date(2025, 12, 31))
    _holding(db_session, filing, _stock(db_session))
    db_session.commit()

    revoke_response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/revoke-cik",
        headers=auth_headers(admin),
        json={"note": "Wrong SEC entity"},
    )
    quarter_response = client.get("/api/v1/admin/13f/quarters/2025-Q4/detail", headers=auth_headers(admin))

    assert revoke_response.status_code == 200
    assert quarter_response.status_code == 200
    assert quarter_response.json()["summary"]["revoked_cik_review_required"] is True
    assert quarter_response.json()["summary"]["quarter_health"] == "setup_required"


def test_revoked_cik_repair_task_clears_after_reconfirming_manager(
    client,
    db_session,
    user_factory,
    auth_headers,
):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session, name="Revoked CIK Manager", cik="0001336528")
    _filing(db_session, manager, accession="0001336528-26-000001", period=date(2025, 12, 31))
    db_session.commit()
    client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/revoke-cik",
        headers=auth_headers(admin),
        json={"note": "Wrong SEC entity"},
    )
    client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/confirm-cik",
        headers=auth_headers(admin),
        json={"cik": "0001336529", "note": "Correct SEC entity confirmed"},
    )

    task_response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))
    quarter_response = client.get("/api/v1/admin/13f/quarters/2025-Q4/detail", headers=auth_headers(admin))

    assert task_response.status_code == 200
    assert all(item["code"] != "REVOKED_CIK_DOWNSTREAM_REVIEW" for item in task_response.json()["items"])
    assert quarter_response.status_code == 200
    assert quarter_response.json()["summary"]["revoked_cik_review_required"] is False
    assert quarter_response.json()["summary"]["quarter_health"] == "partial"


def test_quarter_detail_endpoint_paginates_and_filters_filing_rows(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    pending_manager = _manager(db_session, name="Pending Pagination Capital", cik="0001234567")
    parsed_manager = _manager(db_session, name="Parsed Pagination Capital", cik="0001234568")
    failed_manager = _manager(db_session, name="Failed Pagination Capital", cik="0001234569")
    parsed_doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=parsed_manager.cik,
        accession_no="0001234568-26-000002",
        source_url="https://example.test/parsed-pagination.xml",
        http_status=200,
        raw_sha256="parsed-pagination",
        body_path="/tmp/parsed-pagination.xml",
        parse_status="parsed",
        parsed_at=datetime.now(timezone.utc),
    )
    failed_doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=failed_manager.cik,
        accession_no="0001234569-26-000003",
        source_url="https://example.test/failed-pagination.xml",
        http_status=200,
        raw_sha256="failed-pagination",
        body_path="/tmp/failed-pagination.xml",
        parse_status="failed",
        error_message="bad XML",
    )
    db_session.add_all([parsed_doc, failed_doc])
    db_session.flush()
    _filing(db_session, pending_manager, accession="0001234567-26-000001", period=date(2025, 12, 31))
    _filing(
        db_session,
        parsed_manager,
        accession="0001234568-26-000002",
        period=date(2025, 12, 31),
        raw_infotable_doc_id=parsed_doc.id,
    )
    _filing(
        db_session,
        failed_manager,
        accession="0001234569-26-000003",
        period=date(2025, 12, 31),
        raw_infotable_doc_id=failed_doc.id,
    )
    db_session.commit()

    response = client.get(
        "/api/v1/admin/13f/quarters/2025-Q4/detail?filing_status=failed&filing_limit=1&filing_offset=0",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    page = response.json()["filings_page"]
    assert page["total"] == 1
    assert page["limit"] == 1
    assert page["offset"] == 0
    assert page["status"] == "failed"
    assert [item["accession_no"] for item in page["items"]] == ["0001234569-26-000003"]
    assert response.json()["filing_counts_by_status"]["pending"] == 1
    assert response.json()["filing_counts_by_status"]["failed"] == 1
    assert [item["accession_no"] for item in response.json()["filings"]] == [
        "0001234567-26-000001",
        "0001234568-26-000002",
        "0001234569-26-000003",
    ]


def test_quarter_detail_endpoint_returns_operational_drilldown(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    stock = _stock(db_session)
    parsed_doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=manager.cik,
        accession_no="0001234567-26-000001",
        source_url="https://example.test/parsed.xml",
        http_status=200,
        raw_sha256="parsed-quarter-detail",
        body_path="/tmp/parsed.xml",
        parse_status="parsed",
        parsed_at=datetime.now(timezone.utc),
    )
    failed_doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=manager.cik,
        accession_no="0001234567-26-000002",
        source_url="https://example.test/failed.xml",
        http_status=200,
        raw_sha256="failed-quarter-detail",
        body_path="/tmp/failed.xml",
        parse_status="failed",
        error_message="broken infotable",
        parsed_at=datetime.now(timezone.utc),
    )
    db_session.add_all([parsed_doc, failed_doc])
    db_session.flush()
    parsed = _filing(
        db_session,
        manager,
        accession="0001234567-26-000001",
        raw_infotable_doc_id=parsed_doc.id,
    )
    _holding(db_session, parsed, stock)
    failed = _filing(
        db_session,
        manager,
        accession="0001234567-26-000002",
        is_latest=False,
        raw_infotable_doc_id=failed_doc.id,
    )
    pending = _filing(
        db_session,
        manager,
        accession="0001234567-26-000003",
        is_latest=False,
    )
    amendment = _filing(
        db_session,
        manager,
        accession="0001234567-26-000004",
        form_type="13F-HR/A",
        is_latest=False,
    )
    report = QualityReport()
    report.add("parse_failure", "error", "failed infotable", accession_no=failed.accession_no)
    persist_quality_report(db_session, quarter="2025-Q4", report=report)
    db_session.commit()

    response = client.get("/api/v1/admin/13f/quarters/2025-Q4/detail", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["quarter"] == "2025-Q4"
    assert {item["accession_no"] for item in payload["pending_filings"]} == {
        pending.accession_no,
        amendment.accession_no,
    }
    assert payload["failed_filings"][0]["accession_no"] == failed.accession_no
    assert payload["failed_filings"][0]["raw_infotable"]["error_message"] == "broken infotable"
    assert payload["amendments"][0]["accession_no"] == amendment.accession_no
    assert payload["quality_report"]["status"] == "failed"
    action_types = {item["job_type"] for item in payload["suggested_actions"]}
    assert {"ingest_holdings", "quality_check", "reprocess_amendment"}.issubset(action_types)


def test_persisted_quality_report_surfaces_in_quarter_and_tasks(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    stock = _stock(db_session)
    filing = _filing(db_session, manager, accession="0001234567-26-000001")
    _holding(db_session, filing, stock)
    report = QualityReport()
    report.add("reconciliation", "warning", "reported and computed totals differ", accession_no=filing.accession_no)
    persist_quality_report(db_session, quarter="2025-Q4", report=report)
    db_session.commit()

    quarter_response = client.get("/api/v1/admin/13f/quarters/2025-Q4", headers=auth_headers(admin))
    task_response = client.get("/api/v1/admin/13f/tasks", headers=auth_headers(admin))

    assert quarter_response.status_code == 200
    quarter = quarter_response.json()
    assert quarter["quality_status"] == "warning"
    assert quarter["quality_warnings"] == 1
    assert quarter["quality_errors"] == 0
    assert any(item["code"] == "QUALITY_WARNINGS" for item in task_response.json()["items"])


def test_quality_check_job_persists_report(client, db_session, user_factory, auth_headers, monkeypatch):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    job = JobRun(
        job_type="quality_check",
        status="queued",
        requested_by_user_id=admin.id,
        trigger_source="manual",
        dedupe_key="quality_check:2025-Q4",
        lock_key="quality_check:2025-Q4",
        quarter="2025-Q4",
        input_json={"job_type": "quality_check", "quarter": "2025-Q4"},
    )
    db_session.add(job)
    db_session.commit()
    report = QualityReport()
    report.add("parse_failure", "error", "failed infotable", accession_no="0001234567-26-000001")
    monkeypatch.setattr("app.services.thirteenf_admin_dashboard.run_quality_checks", lambda session, quarter: report)

    result = execute_queued_job_once(db_session, worker_id="test-worker")

    assert result.status == "failed"
    persisted = db_session.query(QualityReport13F).filter_by(quarter="2025-Q4").one()
    assert persisted.status == "failed"
    assert persisted.error_count == 1
    assert persisted.warning_count == 0
    assert persisted.source_job_id == job.id


def test_quarterly_pipeline_records_retryable_stage_jobs(db_session, monkeypatch):
    _clear_13f(db_session)
    calls: list[str] = []

    monkeypatch.setattr(
        "app.services.edgar_ingestion.ingest_quarter_index",
        lambda session, quarter: calls.append(f"index:{quarter}") or 2,
    )
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard._execute_ingest_job",
        lambda session, job_type, payload: calls.append(f"{job_type}:{payload['quarter']}")
        or {"filings_processed": 2, "filings_failed": 0, "holdings_inserted": 10, "status": "succeeded"},
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_from_dataroma",
        lambda session: calls.append("enrich_cusip") or 3,
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.bootstrap_stocks_from_cusip_map",
        lambda session: calls.append("bootstrap_stocks") or 4,
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.backfill_stock_ids",
        lambda session: calls.append("backfill_stock_ids") or 5,
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_stocks_from_edgar_tickers",
        lambda session: calls.append("enrich_stocks_edgar") or {"new_mappings": 6},
    )
    report = QualityReport()
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.run_quality_checks",
        lambda session, quarter: calls.append(f"quality:{quarter}") or report,
    )

    result = execute_job_payload(db_session, "quarterly_pipeline", {"quarter": "2025-Q4", "_job_id": 99})
    stage_jobs = db_session.query(JobRun).order_by(JobRun.id.asc()).all()

    assert result["status"] == "succeeded"
    assert result["stages"] == [
        {"job_type": "fetch_quarter_index", "job_id": stage_jobs[0].id, "status": "succeeded"},
        {"job_type": "ingest_holdings", "job_id": stage_jobs[1].id, "status": "succeeded"},
        {"job_type": "enrich_metadata", "job_id": stage_jobs[2].id, "status": "succeeded"},
        {"job_type": "quality_check", "job_id": stage_jobs[3].id, "status": "succeeded"},
    ]
    assert calls == [
        "index:2025-Q4",
        "ingest_holdings:2025-Q4",
        "enrich_cusip",
        "bootstrap_stocks",
        "backfill_stock_ids",
        "enrich_stocks_edgar",
        "quality:2025-Q4",
    ]
    assert [job.job_type for job in stage_jobs] == [
        "fetch_quarter_index",
        "ingest_holdings",
        "enrich_metadata",
        "quality_check",
    ]
    assert all(job.trigger_source == "pipeline" for job in stage_jobs)
    assert stage_jobs[2].summary_json["cusip_mappings"] == 3
    assert stage_jobs[2].summary_json["holdings_linked"] == 5
    assert stage_jobs[2].summary_json["schema"] == "enrich_metadata_summary.v1"
    assert result["summary_schema"] == "quarterly_pipeline_summary.v1"


def test_readiness_thresholds_are_configurable(client, db_session, user_factory, auth_headers, monkeypatch):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = _manager(db_session)
    filing = _filing(db_session, manager, accession="0001234567-26-000001", period=date(2025, 12, 31))
    linked_stock = _stock(db_session)
    _holding(db_session, filing, linked_stock)
    unlinked = Holding13F(
        filing_id=filing.id,
        row_fingerprint=f"{filing.accession_no}-UNLINKED",
        cusip="987654321",
        issuer_name="Unlinked Corp",
        title_of_class="COM",
        value_thousands=1000,
        shares=100,
        share_type="SH",
        stock_id=None,
    )
    db_session.add(unlinked)
    db_session.commit()
    monkeypatch.setattr("app.services.thirteenf_admin_dashboard.settings.THIRTEENF_READY_LINK_RATIO", 0.40)
    monkeypatch.setattr("app.services.thirteenf_admin_dashboard.settings.THIRTEENF_WARNING_LINK_RATIO", 0.25)
    monkeypatch.setattr("app.services.thirteenf_admin_dashboard.settings.THIRTEENF_READY_HISTORICAL_DEPTH", 1)
    monkeypatch.setattr("app.services.thirteenf_admin_dashboard.settings.THIRTEENF_MIN_HISTORICAL_DEPTH", 1)

    response = client.get("/api/v1/admin/13f/readiness", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness_level"] == "ready"
    assert payload["thresholds"]["ready_link_ratio"] == 0.4
    assert payload["thresholds"]["warning_link_ratio"] == 0.25


def test_edgar_rate_limit_status_endpoint_returns_runtime_budget(client, db_session, user_factory, auth_headers, monkeypatch):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.edgar_rate_limit_status",
        lambda: {
            "mode": "live",
            "request_delay_s": 0.2,
            "max_retries": 3,
            "window_seconds": 60,
            "recent_request_count": 7,
            "estimated_capacity": 300,
            "remaining_estimated_capacity": 293,
            "global_pause_until": None,
        },
    )

    response = client.get("/api/v1/admin/13f/edgar-rate-limit", headers=auth_headers(admin))

    assert response.status_code == 200
    assert response.json()["recent_request_count"] == 7
    assert response.json()["remaining_estimated_capacity"] == 293


def test_edgar_rate_limit_status_counts_recorded_requests(monkeypatch):
    from app.edgar import client as edgar_client

    monkeypatch.setattr(edgar_client.settings, "EDGAR_RATE_LIMIT_WINDOW_S", 60)
    monkeypatch.setattr(edgar_client.settings, "EDGAR_REQUEST_DELAY_S", 0.5)
    with edgar_client._REQUEST_EVENTS_LOCK:
        edgar_client._REQUEST_EVENTS.clear()
        edgar_client._GLOBAL_PAUSE_UNTIL = None

    edgar_client._record_request(200, "https://www.sec.gov/test-a")
    edgar_client._record_request(503, "https://www.sec.gov/test-b")

    status = edgar_client.edgar_rate_limit_status()

    assert status["recent_request_count"] == 2
    assert status["estimated_capacity"] == 120
    assert status["remaining_estimated_capacity"] == 118


def test_quarterly_pipeline_continues_after_retryable_enrichment_failure(
    client,
    db_session,
    user_factory,
    auth_headers,
    monkeypatch,
):
    _clear_13f(db_session)
    admin = _admin(user_factory)

    monkeypatch.setattr("app.services.edgar_ingestion.ingest_quarter_index", lambda session, quarter: 1)
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard._execute_ingest_job",
        lambda session, job_type, payload: {"filings_processed": 1, "status": "succeeded"},
    )

    def fail_enrichment(session):
        raise RuntimeError("CUSIP enrichment failed")

    monkeypatch.setattr("app.services.cusip_enrichment.enrich_from_dataroma", fail_enrichment)

    report = QualityReport()

    monkeypatch.setattr("app.services.thirteenf_admin_dashboard.run_quality_checks", lambda session, quarter: report)

    result = execute_job_payload(db_session, "quarterly_pipeline", {"quarter": "2025-Q4", "_job_id": 99})

    stage_jobs = db_session.query(JobRun).order_by(JobRun.id.asc()).all()
    assert result["status"] == "partial_success"
    assert result["stages"] == [
        {"job_type": "fetch_quarter_index", "job_id": stage_jobs[0].id, "status": "succeeded"},
        {"job_type": "ingest_holdings", "job_id": stage_jobs[1].id, "status": "succeeded"},
        {"job_type": "enrich_metadata", "job_id": stage_jobs[2].id, "status": "failed"},
        {"job_type": "quality_check", "job_id": stage_jobs[3].id, "status": "succeeded"},
    ]
    assert [job.job_type for job in stage_jobs] == [
        "fetch_quarter_index",
        "ingest_holdings",
        "enrich_metadata",
        "quality_check",
    ]
    assert [job.status for job in stage_jobs] == ["succeeded", "succeeded", "failed", "succeeded"]
    assert stage_jobs[2].error_message == "CUSIP enrichment failed"
    assert stage_jobs[2].input_json["parent_job_id"] == 99

    parent_summary = dict(result)
    parent_summary.pop("status")
    parent_job = JobRun(
        job_type="quarterly_pipeline",
        status="partial_success",
        requested_by_user_id=admin.id,
        trigger_source="scheduler",
        dedupe_key="quarterly_pipeline:2025-Q4",
        lock_key="quarterly_pipeline:2025-Q4",
        quarter="2025-Q4",
        input_json={"job_type": "quarterly_pipeline", "quarter": "2025-Q4"},
        summary_json=parent_summary,
    )
    db_session.add(parent_job)
    db_session.commit()

    response = client.get(f"/api/v1/admin/13f/jobs/{parent_job.id}", headers=auth_headers(admin))

    assert response.status_code == 200
    assert response.json()["retry_targets"] == [
        {
            "job_type": "enrich_metadata",
            "quarter": "2025-Q4",
            "label": "Retry enrichment for 2025-Q4",
        }
    ]


def test_quality_reports_endpoint_returns_latest_reports(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    report = QualityReport()
    report.add("reconciliation", "info", "ok")
    persist_quality_report(db_session, quarter="2025-Q4", report=report)
    db_session.commit()

    response = client.get("/api/v1/admin/13f/quality", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()["items"][0]
    assert payload["quarter"] == "2025-Q4"
    assert payload["status"] == "passed"
    assert payload["info_count"] == 1
