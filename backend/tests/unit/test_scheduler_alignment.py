from datetime import date
from unittest.mock import MagicMock, patch
from app.services.scheduler import run_quarterly_pipeline

def test_run_quarterly_pipeline_triggers_job():
    db_factory = MagicMock()
    db = db_factory.return_value
    
    # Mocking today's date to be May 6, 2026
    # On May 6, the latest available quarter according to checkpoints is 2025-Q4
    with patch("app.services.scheduler._quarter_already_ingested", return_value=False), \
         patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger_job, \
         patch("app.services.scheduler.date") as mock_date:
        
        mock_date.today.return_value = date(2026, 5, 6)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
        
        run_quarterly_pipeline(db_factory)
        
        mock_trigger_job.assert_called_once()
        args, kwargs = mock_trigger_job.call_args
        assert kwargs["payload"]["job_type"] == "quarterly_pipeline"
        assert kwargs["payload"]["quarter"] == "2025-Q4"
        assert kwargs["payload"]["trigger_source"] == "scheduler"

def test_run_quarterly_pipeline_skips_if_already_ingested():
    db_factory = MagicMock()
    
    with patch("app.services.scheduler._quarter_already_ingested", return_value=True), \
         patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger_job:
        
        run_quarterly_pipeline(db_factory)
        
        mock_trigger_job.assert_not_called()
