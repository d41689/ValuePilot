from unittest.mock import MagicMock, patch
from app.services.notifications import send_slack_notification, send_discord_notification, notify_job_completion
from app.core.config import settings

# --- Slack Tests ---

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

def test_send_slack_notification_http_failure_returns_false():
    with patch.object(settings, "SLACK_WEBHOOK_URL", "http://mock-slack.com"), \
         patch("httpx.Client.post", side_effect=Exception("connection refused")):
        result = send_slack_notification(
            severity="error",
            job_type="test_job",
            error_summary="Something failed",
            suggested_action="Fix it"
        )
        assert result is False

# --- Discord Tests ---

def test_send_discord_notification_skips_without_url():
    with patch.object(settings, "DISCORD_WEBHOOK_URL", None):
        result = send_discord_notification(
            severity="error",
            job_type="test_job",
            error_summary="Something failed",
            suggested_action="Fix it"
        )
        assert result is False

def test_send_discord_notification_calls_webhook():
    with patch.object(settings, "DISCORD_WEBHOOK_URL", "http://mock-discord.com"), \
         patch("httpx.Client.post") as mock_post:
        
        mock_post.return_value = MagicMock()
        mock_post.return_value.status_code = 200
        
        result = send_discord_notification(
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
        assert payload["username"] == "ValuePilot Bot"
        assert payload["embeds"][0]["title"] == "13F Data Operations Alert"
        assert any(f["name"] == "Quarter" and f["value"] == "2025-Q4" for f in payload["embeds"][0]["fields"])

def test_send_discord_notification_http_failure_returns_false():
    with patch.object(settings, "DISCORD_WEBHOOK_URL", "http://mock-discord.com"), \
         patch("httpx.Client.post", side_effect=Exception("discord down")):
        result = send_discord_notification(
            severity="error",
            job_type="test_job",
            error_summary="Something failed",
            suggested_action="Fix it"
        )
        assert result is False

# --- notify_job_completion Orchestration Tests ---

def test_notify_job_completion_success_pipeline_warnings():
    with patch("app.services.notifications.send_slack_notification") as mock_slack, \
         patch("app.services.notifications.send_discord_notification") as mock_discord:
        notify_job_completion(
            job_id=1,
            job_type="quarterly_pipeline",
            status="succeeded",
            quarter="2025-Q4",
            summary={"quality_status": "warning"},
            error_message=None
        )
        mock_slack.assert_called_once_with(
            severity="warning",
            job_type="quarterly_pipeline",
            quarter="2025-Q4",
            error_summary="Pipeline succeeded but has quality warnings.",
            suggested_action="Review quality report in the dashboard.",
            job_id=1
        )
        mock_discord.assert_called_once_with(
            severity="warning",
            job_type="quarterly_pipeline",
            quarter="2025-Q4",
            error_summary="Pipeline succeeded but has quality warnings.",
            suggested_action="Review quality report in the dashboard.",
            job_id=1
        )

def test_notify_job_completion_success_pipeline_quality_failed():
    with patch("app.services.notifications.send_slack_notification") as mock_slack, \
         patch("app.services.notifications.send_discord_notification") as mock_discord:
        notify_job_completion(
            job_id=1,
            job_type="quarterly_pipeline",
            status="succeeded",
            quarter="2025-Q4",
            summary={"quality_status": "failed"},
            error_message=None
        )
        mock_slack.assert_called_once_with(
            severity="error",
            job_type="quarterly_pipeline",
            quarter="2025-Q4",
            error_summary="Pipeline succeeded but has critical quality errors.",
            suggested_action="Review quality report in the dashboard.",
            job_id=1
        )
        mock_discord.assert_called_once_with(
            severity="error",
            job_type="quarterly_pipeline",
            quarter="2025-Q4",
            error_summary="Pipeline succeeded but has critical quality errors.",
            suggested_action="Review quality report in the dashboard.",
            job_id=1
        )

def test_notify_job_completion_success_no_alert():
    """succeeded jobs with no quality issues must not trigger any notification."""
    with patch("app.services.notifications.send_slack_notification") as mock_slack, \
         patch("app.services.notifications.send_discord_notification") as mock_discord:
        notify_job_completion(
            job_id=1,
            job_type="quarterly_pipeline",
            status="succeeded",
            quarter="2025-Q4",
            summary={"quality_status": "passed"},
            error_message=None
        )
        mock_slack.assert_not_called()
        mock_discord.assert_not_called()

def test_notify_job_completion_failed():
    with patch("app.services.notifications.send_slack_notification") as mock_slack, \
         patch("app.services.notifications.send_discord_notification") as mock_discord:
        notify_job_completion(
            job_id=3,
            job_type="ingest_holdings",
            status="failed",
            quarter="2025-Q4",
            summary={},
            error_message="DB connection lost"
        )
        mock_slack.assert_called_once()
        mock_discord.assert_called_once()
        
        _, kwargs = mock_slack.call_args
        assert kwargs["severity"] == "error"
        assert kwargs["error_summary"] == "DB connection lost"
        
        _, kwargs_d = mock_discord.call_args
        assert kwargs_d["severity"] == "error"
        assert kwargs_d["error_summary"] == "DB connection lost"

def test_notify_job_completion_partial_success():
    with patch("app.services.notifications.send_slack_notification") as mock_slack, \
         patch("app.services.notifications.send_discord_notification") as mock_discord:
        notify_job_completion(
            job_id=2,
            job_type="ingest_holdings",
            status="partial_success",
            quarter="2025-Q4",
            summary={"filings_failed": 3},
            error_message=None
        )
        mock_slack.assert_called_once()
        mock_discord.assert_called_once()
        
        _, kwargs = mock_slack.call_args
        assert "3 filings failed" in kwargs["error_summary"]
        
        _, kwargs_d = mock_discord.call_args
        assert "3 filings failed" in kwargs_d["error_summary"]
