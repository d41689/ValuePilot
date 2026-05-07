from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models.institutions import Filing13F, Holding13F, InstitutionManager, JobRun, JobWorkerHeartbeat, RawSourceDocument
from app.models.stocks import Stock
from app.services.thirteenf_job_worker import execute_queued_job_once, record_worker_heartbeat


def _clear_13f(db_session) -> None:
    db_session.query(Holding13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(RawSourceDocument).delete()
    db_session.query(JobWorkerHeartbeat).delete()
    db_session.query(JobRun).delete()
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


def test_admin_readiness_reports_setup_required_without_confirmed_managers(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)

    response = client.get("/api/v1/admin/13f/readiness", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness_level"] == "unavailable"
    assert payload["frontend_behavior"] == "show_setup_required"
    assert payload["current_quarter"]["health"] == "setup_required"
    assert payload["top_task"]["code"] == "NO_CONFIRMED_MANAGER_CIK_WHITELIST"
    assert payload["counts"]["confirmed_managers"] == 0


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
    stock = _stock(db_session)
    doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=manager.cik,
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
