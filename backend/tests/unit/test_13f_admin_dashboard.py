from __future__ import annotations

from datetime import date, datetime, timezone

from app.models.institutions import Filing13F, Holding13F, InstitutionManager, JobRun, RawSourceDocument
from app.models.stocks import Stock


def _clear_13f(db_session) -> None:
    db_session.query(Holding13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(RawSourceDocument).delete()
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
