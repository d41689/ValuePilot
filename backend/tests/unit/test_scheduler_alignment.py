from datetime import date
from unittest.mock import MagicMock, patch
from app.services.scheduler import (
    _quarter_already_ingested,
    create_scheduler,
    create_research_notification_scheduler,
    run_13f_health_summary,
    run_daily_sync_poll,
    run_filing_season_digest,
    run_job_watchdog,
    run_quarterly_pipeline,
    run_research_notifications,
    run_smart_retries,
)
from app.models.institutions import Filing13F, InstitutionManager, JobRun


def test_run_quarterly_pipeline_triggers_job():
    db_factory = MagicMock()
    db = db_factory.return_value

    # On 2026-05-06, latest_available_quarter returns "2025-Q4":
    # (5, 6) >= (5, 15) is False, so Q1 checkpoint not met.
    # (5, 6) >= (2, 14) is True, so Q4 of previous year is returned.
    with patch("app.services.scheduler._quarter_already_ingested", return_value=False), \
         patch("app.services.thirteenf_admin_dashboard.trigger_job",
               return_value={"id": 1, "job_type": "quarterly_pipeline"}) as mock_trigger_job, \
         patch("app.services.scheduler.date") as mock_date:

        mock_date.today.return_value = date(2026, 5, 6)

        run_quarterly_pipeline(db_factory)

        mock_trigger_job.assert_called_once()
        _, kwargs = mock_trigger_job.call_args
        assert kwargs["payload"]["job_type"] == "quarterly_pipeline"
        assert kwargs["payload"]["quarter"] == "2025-Q4"
        assert kwargs["payload"]["trigger_source"] == "scheduler"
        assert kwargs["requested_by_user_id"] is None


def test_run_quarterly_pipeline_skips_if_already_ingested():
    db_factory = MagicMock()

    with patch("app.services.scheduler._quarter_already_ingested", return_value=True), \
         patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger_job:

        run_quarterly_pipeline(db_factory)

        mock_trigger_job.assert_not_called()


def test_one_filing_does_not_mark_a_quarter_complete(db_session):
    manager = InstitutionManager(
        legal_name="Partial Manager",
        canonical_name="Partial Manager",
        match_status="confirmed",
        status="active",
    )
    db_session.add(manager)
    db_session.flush()
    db_session.add(
        Filing13F(
            manager_id=manager.id,
            accession_no="0000000001-26-000001",
            period_of_report=date(2025, 12, 31),
            filed_at=date(2026, 2, 14),
            form_type="13F-HR",
        )
    )
    db_session.flush()

    assert _quarter_already_ingested(db_session, "2025-Q4") is False


def test_run_quarterly_pipeline_skips_on_lock_conflict():
    """Scheduler should log a skip and not treat a lock conflict as an error."""
    db_factory = MagicMock()
    db = db_factory.return_value

    conflict_response = {"conflict": True, "active_job_id": 42, "lock_key": "quarterly_pipeline:2025-Q4"}

    with patch("app.services.scheduler._quarter_already_ingested", return_value=False), \
         patch("app.services.thirteenf_admin_dashboard.trigger_job",
               return_value=conflict_response) as mock_trigger_job, \
         patch("app.services.scheduler.date") as mock_date:

        mock_date.today.return_value = date(2026, 5, 6)

        run_quarterly_pipeline(db_factory)

        mock_trigger_job.assert_called_once()
        # No exception should propagate; the conflict is handled gracefully.
        db.rollback.assert_not_called()


def test_create_scheduler_registers_smart_retries_only_when_enabled(monkeypatch):
    db_factory = MagicMock()

    monkeypatch.setattr("app.services.scheduler.settings.THIRTEENF_SMART_RETRY_ENABLED", False)
    scheduler = create_scheduler(db_factory)
    assert scheduler.get_job("smart_retries") is None
    assert scheduler.get_job("quarterly_edgar_pipeline") is not None

    monkeypatch.setattr("app.services.scheduler.settings.THIRTEENF_SMART_RETRY_ENABLED", True)
    scheduler = create_scheduler(db_factory)
    assert scheduler.get_job("smart_retries") is not None


def test_create_scheduler_registers_hourly_daily_sync_poll():
    scheduler = create_scheduler(MagicMock())

    job = scheduler.get_job("daily_13f_sync_poll")

    assert job is not None
    assert job.func == run_daily_sync_poll


def test_create_scheduler_registers_job_watchdog():
    scheduler = create_scheduler(MagicMock())

    job = scheduler.get_job("thirteenf_job_watchdog")

    assert job is not None
    assert job.func == run_job_watchdog


def test_create_scheduler_registers_daily_health_summary_at_8am_et():
    scheduler = create_scheduler(MagicMock())

    job = scheduler.get_job("thirteenf_daily_health_summary")

    assert job is not None
    assert job.func == run_13f_health_summary
    assert str(job.trigger.timezone) == "America/New_York"
    assert "hour='8'" in str(job.trigger)
    assert "minute='0'" in str(job.trigger)


def test_create_scheduler_registers_daily_filing_season_digest():
    scheduler = create_scheduler(MagicMock())

    job = scheduler.get_job("thirteenf_filing_season_digest")

    assert job is not None
    assert job.func == run_filing_season_digest
    assert str(job.trigger.timezone) == "America/New_York"
    assert "hour='7'" in str(job.trigger)


def test_research_notification_scheduler_is_independent_from_edgar_jobs():
    scheduler = create_research_notification_scheduler(MagicMock())

    notification_job = scheduler.get_job("research_notification_materializer")
    assert notification_job is not None
    assert notification_job.func == run_research_notifications
    assert scheduler.get_job("quarterly_edgar_pipeline") is None

    edgar_scheduler = create_scheduler(MagicMock())
    assert edgar_scheduler.get_job("research_notification_materializer") is None


def test_research_notification_run_skips_rotation_when_keyring_is_unconfigured(monkeypatch):
    db_factory = MagicMock()
    monkeypatch.setattr(
        "app.services.scheduler.settings.NOTIFICATION_SECRET_KEYS",
        None,
    )
    monkeypatch.setattr(
        "app.services.research_notifications.materialize_due_research_reviews",
        MagicMock(return_value=0),
    )
    monkeypatch.setattr(
        "app.services.research_notifications.materialize_intrinsic_value_crossings",
        MagicMock(return_value=0),
    )
    monkeypatch.setattr(
        "app.services.research_notifications.materialize_research_coverage_changes",
        MagicMock(return_value=0),
    )
    digest = MagicMock(return_value=0)
    monkeypatch.setattr(
        "app.services.research_notifications.materialize_scheduled_digests",
        digest,
    )
    rotation = MagicMock()
    monkeypatch.setattr(
        "app.services.research_notifications.run_destination_secret_rotation",
        rotation,
    )
    monkeypatch.setattr(
        "app.services.research_notifications.deliver_pending_attempts",
        MagicMock(return_value={"delivered": 0}),
    )

    run_research_notifications(db_factory)

    rotation.assert_not_called()
    digest.assert_called_once()
    db_factory.return_value.close.assert_called_once()


def test_research_notification_run_skips_noop_secret_rotation(monkeypatch):
    db_factory = MagicMock()
    monkeypatch.setattr(
        "app.services.scheduler.settings.NOTIFICATION_SECRET_KEYS",
        "v1:configured-for-condition-test",
    )
    for name in (
        "materialize_due_research_reviews",
        "materialize_intrinsic_value_crossings",
        "materialize_research_coverage_changes",
        "materialize_scheduled_digests",
    ):
        monkeypatch.setattr(
            f"app.services.research_notifications.{name}",
            MagicMock(return_value=0),
        )
    needed = MagicMock(return_value=False)
    rotation = MagicMock()
    monkeypatch.setattr(
        "app.services.research_notifications.destination_secret_rotation_needed",
        needed,
    )
    monkeypatch.setattr(
        "app.services.research_notifications.run_destination_secret_rotation",
        rotation,
    )
    monkeypatch.setattr(
        "app.services.research_notifications.deliver_pending_attempts",
        MagicMock(return_value={"delivered": 0}),
    )

    run_research_notifications(db_factory)

    needed.assert_called_once_with(db_factory.return_value)
    rotation.assert_not_called()
    db_factory.return_value.close.assert_called_once()


def test_run_filing_season_digest_persists_and_closes_session(monkeypatch):
    db_factory = MagicMock()
    persist = MagicMock(return_value={"status": "persisted", "created": 2, "existing": 0})
    monkeypatch.setattr(
        "app.services.thirteenf_filing_season.persist_filing_season_digest",
        persist,
    )

    run_filing_season_digest(db_factory)

    persist.assert_called_once_with(db_factory.return_value)
    db_factory.return_value.close.assert_called_once()


def test_run_13f_health_summary_emits_alerts_before_summary(monkeypatch):
    db_factory = MagicMock()
    calls = []
    monkeypatch.setattr(
        "app.services.thirteenf_health.evaluate_13f_alerts",
        lambda db, edgar_rate_limit_status=None: [
            {
                "severity": "P1",
                "title": "SEC blocked",
                "message": "429 detected",
                "context": {"edgar_rate_limit_status": edgar_rate_limit_status},
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.thirteenf_health.emit_daily_health_summary",
        lambda db: calls.append(("summary", None)) or {"sent": True},
    )
    monkeypatch.setattr(
        "app.services.scheduler.emit_alert",
        lambda **kwargs: calls.append(("alert", kwargs)) or {"sent": True},
    )
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.build_edgar_rate_limit_status",
        lambda: {"edgar_block_alert": True, "recent_403_count": 0, "recent_429_count": 1},
    )

    run_13f_health_summary(db_factory)

    assert calls[0][0] == "alert"
    assert calls[0][1]["context"]["edgar_rate_limit_status"]["recent_429_count"] == 1
    assert calls[1] == ("summary", None)


def test_run_13f_health_summary_survives_rate_guard_outage(monkeypatch):
    """A Rate Guard outage must not crash the alert run or fire a false alarm —
    evaluate_13f_alerts is called with edgar_rate_limit_status=None."""
    from app.rate_guard.client import RateGuardFetchError

    db_factory = MagicMock()
    seen: dict = {}

    def _capture_alerts(db, edgar_rate_limit_status=None):
        seen["rate_limit_status"] = edgar_rate_limit_status
        return []

    monkeypatch.setattr("app.services.thirteenf_health.evaluate_13f_alerts", _capture_alerts)
    monkeypatch.setattr(
        "app.services.thirteenf_health.emit_daily_health_summary",
        lambda db: seen.update(summary=True) or {"sent": True},
    )
    monkeypatch.setattr("app.services.scheduler.emit_alert", lambda **kwargs: {"sent": True})

    def _outage() -> dict:
        raise RateGuardFetchError("Rate Guard unreachable for /v1/metrics")

    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.build_edgar_rate_limit_status", _outage
    )

    run_13f_health_summary(db_factory)  # must not raise

    assert seen["rate_limit_status"] is None
    assert seen["summary"] is True


def test_run_smart_retries_noops_when_disabled(monkeypatch):
    db_factory = MagicMock()

    monkeypatch.setattr("app.services.scheduler.settings.THIRTEENF_SMART_RETRY_ENABLED", False)
    with patch("app.services.thirteenf_admin_dashboard.smart_retry_failed_jobs") as mock_smart_retry:
        run_smart_retries(db_factory)

    mock_smart_retry.assert_not_called()
    db_factory.assert_not_called()
