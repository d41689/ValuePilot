from datetime import date
from unittest.mock import MagicMock, patch
from app.services.scheduler import run_quarterly_pipeline


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
