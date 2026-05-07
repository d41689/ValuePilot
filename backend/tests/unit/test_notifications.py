from unittest.mock import MagicMock, patch
from app.services.notifications import send_slack_notification, notify_job_completion
from app.core.config import settings

def test_send_slack_notification_skips_without_url():
    with patch.object(settings, "SLACK_WEBHOOK_URL", None):
        result = send_slack_notification(
            severity="error",
            job_type="test_job",
            error_summary="Something failed",
            suggested_action="Fix it"
        )
        assert result is False

def test_send_slack_notification_calls_webhook():
    with patch.object(settings, "SLACK_WEBHOOK_URL", "http://mock-slack.com"), \
         patch("httpx.Client.post") as mock_post:
        
        mock_post.return_value = MagicMock()
        mock_post.return_value.status_code = 200
        
        result = send_slack_notification(
            severity="error",
            job_type="test_job",
            quarter="2025-Q4",
            error_summary="Something failed",
            suggested_action="Fix it",
            job_id=123
        )
        
        assert result is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["blocks"][0]["type"] == "header"
        assert "2025-Q4" in str(payload)
        assert "123" in payload["blocks"][2]["fields"][1]["text"]

def test_notify_job_completion_success_pipeline_warnings():
    with patch("app.services.notifications.send_slack_notification") as mock_send:
        notify_job_completion(
            job_id=1,
            job_type="quarterly_pipeline",
            status="succeeded",
            quarter="2025-Q4",
            summary={"quality_status": "warning"},
            error_message=None
        )
        mock_send.assert_called_once_with(
            severity="warning",
            job_type="quarterly_pipeline",
            quarter="2025-Q4",
            error_summary="Pipeline succeeded but has quality warnings.",
            suggested_action="Review quality report in the dashboard.",
            job_id=1
        )

def test_notify_job_completion_partial_success():
    with patch("app.services.notifications.send_slack_notification") as mock_send:
        notify_job_completion(
            job_id=2,
            job_type="ingest_holdings",
            status="partial_success",
            quarter="2025-Q4",
            summary={"filings_failed": 3},
            error_message=None
        )
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        assert kwargs["severity"] == "warning"
        assert "3 filings failed" in kwargs["error_summary"]
