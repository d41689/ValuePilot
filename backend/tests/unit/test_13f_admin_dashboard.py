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
from app.services.edgar_ingestion import match_cik_candidates
from app.services.edgar_quality import QualityReport, persist_quality_report
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

    assert task_response.status_code == 200
    assert all(item["code"] != "REVOKED_CIK_DOWNSTREAM_REVIEW" for item in task_response.json()["items"])


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
