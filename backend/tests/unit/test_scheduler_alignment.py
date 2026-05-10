from datetime import date
from unittest.mock import MagicMock, patch
from app.services.scheduler import (
    create_scheduler,
    run_13f_health_summary,
    run_daily_sync_poll,
    run_job_watchdog,
    run_quarterly_pipeline,
    run_smart_retries,
)


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
        "app.services.scheduler.edgar_rate_limit_status",
        lambda: {"edgar_block_alert": True, "recent_403_count": 0, "recent_429_count": 1},
    )

    run_13f_health_summary(db_factory)

    assert calls[0][0] == "alert"
    assert calls[0][1]["context"]["edgar_rate_limit_status"]["recent_429_count"] == 1
    assert calls[1] == ("summary", None)


def test_run_smart_retries_noops_when_disabled(monkeypatch):
    db_factory = MagicMock()

    monkeypatch.setattr("app.services.scheduler.settings.THIRTEENF_SMART_RETRY_ENABLED", False)
    with patch("app.services.thirteenf_admin_dashboard.smart_retry_failed_jobs") as mock_smart_retry:
        run_smart_retries(db_factory)

    mock_smart_retry.assert_not_called()
    db_factory.assert_not_called()
