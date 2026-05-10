from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models.institutions import (
    EdgarSyncStatus,
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    JobRun,
    NoIndexExpectedDate,
    ParseRun13F,
)
from app.services.thirteenf_alerts import InMemoryAlertTransport
from app.services.thirteenf_health import (
    build_daily_health_summary,
    emit_daily_health_summary,
    evaluate_13f_alerts,
    readiness_downgrade_alert,
)


NOW = datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc)


def _clear(db_session) -> None:
    db_session.query(Holding13F).delete()
    db_session.query(ParseRun13F).delete()
    db_session.query(JobRun).delete()
    db_session.query(EdgarSyncStatus).delete()
    db_session.query(Filing13F).delete()
    db_session.query(NoIndexExpectedDate).delete()
    db_session.query(InstitutionManagerCikReviewEvent).delete()
    db_session.query(InstitutionManager).delete()
    db_session.flush()


def _manager(db_session) -> InstitutionManager:
    manager = InstitutionManager(
        canonical_name="Alert Manager",
        legal_name="Alert Manager",
        display_name="Alert Manager",
        edgar_legal_name="Alert Manager",
        cik="0001111111",
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _filing(db_session, manager: InstitutionManager, **overrides) -> Filing13F:
    payload = {
        "manager_id": manager.id,
        "accession_no": overrides.pop("accession_no", "0001111111-26-000001"),
        "accession_number": overrides.pop("accession_number", "0001111111-26-000001"),
        "cik": manager.cik,
        "period_of_report": date(2026, 3, 31),
        "filed_at": date(2026, 5, 14),
        "filing_date": date(2026, 5, 14),
        "accepted_at": NOW - timedelta(days=10),
        "form_type": "13F-HR",
        "report_type": "holdings_report",
        "coverage_completeness": "complete",
        "coverage_type": "normal",
        "quarter_end_date": date(2026, 3, 31),
        "report_quarter": "2026-Q1",
        "official_filing_deadline": date(2026, 5, 15),
        "is_active_for_manager_period": True,
        "parse_status": "succeeded",
        "amendment_status": "no_amendments_seen",
        "holdings_count": 1,
        "common_holdings_count": 1,
    }
    payload.update(overrides)
    filing = Filing13F(**payload)
    db_session.add(filing)
    db_session.flush()
    return filing


def _codes(alerts: list[dict]) -> dict[str, dict]:
    return {item["code"]: item for item in alerts}


def test_consecutive_failed_daily_sync_excludes_no_index_dates(db_session):
    _clear(db_session)
    db_session.add_all(
        [
            EdgarSyncStatus(sync_date=date(2026, 5, 11), status="failed", attempt_count=3),
            EdgarSyncStatus(sync_date=date(2026, 5, 8), status="failed", attempt_count=3),
            EdgarSyncStatus(sync_date=date(2026, 5, 7), status="failed", attempt_count=3),
            NoIndexExpectedDate(
                date=date(2026, 5, 8),
                reason="edgar_special_closure",
                source="admin_manual",
                active=True,
            ),
        ]
    )
    db_session.flush()

    alerts = evaluate_13f_alerts(db_session, now=NOW)

    daily = _codes(alerts)["DAILY_SYNC_CONSECUTIVE_FAILED_BUSINESS_DAYS"]
    assert daily["severity"] == "P1"
    assert daily["context"]["failed_business_dates"] == ["2026-05-11", "2026-05-07"]


def test_coverage_and_cusip_alerts_use_prd_thresholds(db_session, monkeypatch):
    _clear(db_session)
    _filing(db_session, _manager(db_session), official_filing_deadline=date(2026, 5, 1))

    monkeypatch.setattr(
        "app.services.thirteenf_health.build_readiness_summary",
        lambda session, today=None: {
            "readiness_level": "experimental",
            "latest_usable_quarter": "2026-Q1",
            "nt_detection_supported": True,
            "metrics": {
                "manager_coverage_ratio": {"value": 0.65, "estimated": False},
                "linked_common_holding_ratio": {"value": 0.45, "estimated": False},
                "expected_filer_count": 10,
                "filed_manager_count": 6,
                "nt_filer_count": 1,
            },
            "quarter_lists": {},
        },
    )

    alerts = _codes(evaluate_13f_alerts(db_session, now=NOW))

    assert alerts["EXPECTED_FILER_COVERAGE_LOW"]["severity"] == "P1"
    assert alerts["CUSIP_MAPPING_RATIO_CRITICAL"]["severity"] == "P1"


def test_cusip_warning_range_emits_p2(db_session, monkeypatch):
    _clear(db_session)
    _filing(db_session, _manager(db_session), official_filing_deadline=date(2026, 5, 1))
    monkeypatch.setattr(
        "app.services.thirteenf_health.build_readiness_summary",
        lambda session, today=None: {
            "readiness_level": "usable_with_warning",
            "latest_usable_quarter": "2026-Q1",
            "nt_detection_supported": True,
            "metrics": {
                "manager_coverage_ratio": {"value": 0.9, "estimated": False},
                "linked_common_holding_ratio": {"value": 0.62, "estimated": False},
                "expected_filer_count": 10,
                "filed_manager_count": 9,
                "nt_filer_count": 0,
            },
            "quarter_lists": {},
        },
    )

    alerts = _codes(evaluate_13f_alerts(db_session, now=NOW))

    assert alerts["CUSIP_MAPPING_RATIO_WARNING"]["severity"] == "P2"


def test_amendment_and_needs_review_age_alerts(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    _filing(
        db_session,
        manager,
        accession_no="0001111111-26-000002",
        accession_number="0001111111-26-000002",
        amendment_status="amendment_failed",
        updated_at=NOW - timedelta(hours=25),
    )
    _filing(
        db_session,
        manager,
        accession_no="0001111111-26-000003",
        accession_number="0001111111-26-000003",
        amendment_status="amendments_pending",
        amendment_type="RESTATEMENT",
        is_latest_for_period=False,
        is_active_for_manager_period=False,
        updated_at=NOW - timedelta(hours=25),
    )
    _filing(
        db_session,
        manager,
        accession_no="0001111111-26-000004",
        accession_number="0001111111-26-000004",
        amendment_status="amendments_pending",
        amendment_type="other",
        is_latest_for_period=False,
        is_active_for_manager_period=False,
        updated_at=NOW - timedelta(hours=49),
    )
    _filing(
        db_session,
        manager,
        accession_no="0001111111-26-000005",
        accession_number="0001111111-26-000005",
        parse_status="needs_review",
        is_latest_for_period=False,
        is_active_for_manager_period=False,
        updated_at=NOW - timedelta(days=8),
    )
    db_session.flush()

    alerts = _codes(evaluate_13f_alerts(db_session, now=NOW))

    assert alerts["AMENDMENT_FAILED_STALE"]["severity"] == "P2"
    assert alerts["AMENDMENT_RESTATEMENT_PENDING_STALE"]["severity"] == "P2"
    assert alerts["AMENDMENT_PENDING_STALE"]["severity"] == "P2"
    assert alerts["PARSE_NEEDS_REVIEW_STALE"]["severity"] == "P3"


def test_running_job_and_edgar_block_alerts(db_session):
    _clear(db_session)
    db_session.add(
        JobRun(
            job_type="ingest_accession",
            status="running",
            trigger_source="test",
            lock_key="ingest_accession:1",
            dedupe_key="1",
            started_at=NOW - timedelta(minutes=20),
            lease_expires_at=NOW - timedelta(minutes=1),
        )
    )
    db_session.flush()

    alerts = _codes(
        evaluate_13f_alerts(
            db_session,
            now=NOW,
            edgar_rate_limit_status={"edgar_block_alert": True, "recent_403_count": 1, "recent_429_count": 2},
        )
    )

    assert alerts["JOB_RUNNING_TIMEOUT_LEASE_EXPIRED"]["severity"] == "P2"
    assert alerts["SEC_EDGAR_BLOCK_ALERT"]["severity"] == "P1"


def test_ingest_accession_timeout_retry_three_times_alerts(db_session):
    _clear(db_session)
    for index in range(3):
        db_session.add(
            JobRun(
                job_type="ingest_accession",
                status="failed",
                trigger_source="test",
                lock_key=f"ingest_accession:retry-{index}",
                dedupe_key="0001111111-26-000001",
                error_message="job_lease_expired_or_timeout",
                finished_at=NOW - timedelta(minutes=index),
            )
        )
    db_session.flush()

    alerts = _codes(evaluate_13f_alerts(db_session, now=NOW))

    assert alerts["INGEST_FILING_TIMEOUT_RETRY_EXHAUSTED"]["severity"] == "P2"
    assert alerts["INGEST_FILING_TIMEOUT_RETRY_EXHAUSTED"]["context"]["dedupe_key"] == "0001111111-26-000001"


def test_readiness_downgrade_severity():
    warning = readiness_downgrade_alert("ready", "usable_with_warning", quarter="2026-Q1", window_closed=True)
    unavailable = readiness_downgrade_alert("ready", "unavailable", quarter="2026-Q1", window_closed=True)
    open_window = readiness_downgrade_alert("ready", "unavailable", quarter="2026-Q2", window_closed=False)

    assert warning and warning["severity"] == "P2"
    assert unavailable and unavailable["severity"] == "P1"
    assert open_window is None


def test_daily_health_summary_payload_and_delivery(db_session, monkeypatch):
    _clear(db_session)
    manager = _manager(db_session)
    _filing(db_session, manager, report_type="combination_report", coverage_completeness="partial")
    _filing(
        db_session,
        manager,
        accession_no="0001111111-26-000010",
        accession_number="0001111111-26-000010",
        has_confidential_treatment=True,
        parse_status="failed",
        amendment_status="amendments_pending",
        is_latest_for_period=False,
        is_active_for_manager_period=False,
    )
    db_session.add(EdgarSyncStatus(sync_date=date(2026, 5, 11), status="success", attempt_count=1))
    db_session.flush()
    monkeypatch.setattr("app.services.thirteenf_alerts.settings.DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    monkeypatch.setattr(
        "app.services.thirteenf_health.build_readiness_summary",
        lambda session, today=None: {
            "readiness_level": "usable_with_warning",
            "latest_usable_quarter": "2026-Q1",
            "nt_detection_supported": True,
            "metrics": {
                "manager_coverage_ratio": {"value": 0.8, "estimated": False},
                "linked_common_holding_ratio": {"value": 0.75, "estimated": False},
                "expected_filer_count": 10,
                "filed_manager_count": 8,
                "nt_filer_count": 2,
            },
            "quarter_lists": {},
        },
    )

    summary = build_daily_health_summary(db_session, today=date(2026, 5, 12))
    transport = InMemoryAlertTransport()
    alert = emit_daily_health_summary(db_session, today=date(2026, 5, 12), transport=transport)

    assert summary["yesterday_sync_status"] == "success"
    assert summary["combination_report_count"] == 1
    assert summary["confidential_treatment_count"] == 1
    assert summary["failed_filings_count"] == 1
    assert summary["amendments_pending_count"] == 1
    assert alert["sent"] is True
    assert transport.sent[0]["payload"]["content"].startswith("[P3] 13F daily health summary")
