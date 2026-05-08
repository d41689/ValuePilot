import logging
import httpx
from typing import Optional, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

def send_slack_notification(
    *,
    severity: str,
    job_type: str,
    quarter: Optional[str] = None,
    error_summary: str,
    suggested_action: str,
    job_id: Optional[int] = None,
) -> bool:
    """
    Sends a Slack notification via Incoming Webhook.
    Returns True if sent successfully, False otherwise.
    """
    if not settings.SLACK_WEBHOOK_URL:
        return False

    dashboard_url = f"{settings.BASE_URL}/admin/13f"
    if job_id:
        dashboard_url = f"{dashboard_url}?job_id={job_id}"

    # Slack Block Kit payload
    payload = {
        "text": f"13F Alert: {job_type} {severity}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "13F Data Operations Alert",
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Severity:*\n{severity.upper()}"},
                    {"type": "mrkdwn", "text": f"*Job Type:*\n{job_type}"},
                ]
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Quarter:*\n{quarter or 'N/A'}"},
                    {"type": "mrkdwn", "text": f"*Dashboard:*\n<{dashboard_url}|Admin Panel>"},
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error Summary:*\n{error_summary}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Suggested Action:*\n{suggested_action}"
                }
            }
        ]
    }

    try:
        with httpx.Client() as client:
            response = client.post(settings.SLACK_WEBHOOK_URL, json=payload, timeout=10.0)
            response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Failed to send Slack notification: %s", exc)
        return False

def send_discord_notification(
    *,
    severity: str,
    job_type: str,
    quarter: Optional[str] = None,
    error_summary: str,
    suggested_action: str,
    job_id: Optional[int] = None,
) -> bool:
    """
    Sends a Discord notification via Webhook using Embeds.
    Returns True if sent successfully, False otherwise.
    """
    if not settings.DISCORD_WEBHOOK_URL:
        return False

    dashboard_url = f"{settings.BASE_URL}/admin/13f"
    if job_id:
        dashboard_url = f"{dashboard_url}?job_id={job_id}"

    # Discord Embed color (Hex to decimal)
    # Red for error, Orange for warning
    color = 0xFF5252 if severity == "error" else 0xFFB74D
    emoji = "🔴" if severity == "error" else "🟠"

    description = (
        f"**Severity**: {emoji} `{severity.upper()}`\n"
        f"**Job Type**: `{job_type}`\n"
        f"**Quarter**: `{quarter or 'N/A'}`\n"
        f"**Dashboard**: [Admin Panel]({dashboard_url})"
    )

    payload = {
        "username": "ValuePilot Bot",
        "embeds": [
            {
                "title": "13F Data Operations Alert",
                "color": color,
                "description": description,
                "fields": [
                    {"name": "Quarter", "value": quarter or "N/A", "inline": True},
                    {"name": "📝 Error Summary", "value": error_summary, "inline": False},
                    {"name": "💡 Suggested Action", "value": suggested_action, "inline": False},
                ],
                "footer": {"text": f"Job ID: {job_id}" if job_id else ""}
            }
        ]
    }

    try:
        with httpx.Client() as client:
            response = client.post(settings.DISCORD_WEBHOOK_URL, json=payload, timeout=10.0)
            response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Failed to send Discord notification: %s", exc)
        return False

def notify_job_completion(job_id: int, job_type: str, status: str, quarter: Optional[str], summary: Dict[str, Any], error_message: Optional[str]):
    """Analyzes job result and triggers notifications if it's not a complete success."""
    if status == "succeeded":
        # Check if it's a pipeline and if quality passed
        if job_type == "quarterly_pipeline":
            quality_status = summary.get("quality_status")
            if quality_status in {"warning", "failed"}:
                severity = "warning" if quality_status == "warning" else "error"
                msg = f"Pipeline succeeded but has {'quality warnings' if severity == 'warning' else 'critical quality errors'}."
                
                send_slack_notification(
                    severity=severity,
                    job_type=job_type,
                    quarter=quarter,
                    error_summary=msg,
                    suggested_action="Review quality report in the dashboard.",
                    job_id=job_id
                )
                send_discord_notification(
                    severity=severity,
                    job_type=job_type,
                    quarter=quarter,
                    error_summary=msg,
                    suggested_action="Review quality report in the dashboard.",
                    job_id=job_id
                )
        return

    severity = "error" if status == "failed" else "warning"
    error_summary = error_message or "Job completed with issues."
    
    if status == "partial_success":
        top = summary.get("filings_failed")
        nested = summary.get("holdings_ingestion", {}).get("filings_failed")
        failed_count = top if top is not None else (nested if nested is not None else 0)
        error_summary = f"Partial success: {failed_count} filings failed to process."

    suggested_action = "Inspect job logs and retry failed accessions."
    if job_type == "quarterly_pipeline":
        suggested_action = "Review the pipeline summary and retry failed segments."

    # Send to both - functions handle their own config check
    send_slack_notification(
        severity=severity,
        job_type=job_type,
        quarter=quarter,
        error_summary=error_summary,
        suggested_action=suggested_action,
        job_id=job_id
    )
    send_discord_notification(
        severity=severity,
        job_type=job_type,
        quarter=quarter,
        error_summary=error_summary,
        suggested_action=suggested_action,
        job_id=job_id
    )
