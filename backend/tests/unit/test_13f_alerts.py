from __future__ import annotations

import pytest

from app.services.thirteenf_alerts import InMemoryAlertTransport, emit_alert


def test_alert_service_records_severity_and_message_payload(monkeypatch):
    transport = InMemoryAlertTransport()
    monkeypatch.setattr("app.services.thirteenf_alerts.settings.DISCORD_WEBHOOK_URL", None)

    alert = emit_alert(
        severity="P1",
        title="Daily sync failed",
        message="Two business days failed",
        context={"sync_date": "2026-05-08"},
        transport=transport,
    )

    assert alert == {
        "severity": "P1",
        "title": "Daily sync failed",
        "message": "Two business days failed",
        "context": {"sync_date": "2026-05-08"},
        "sent": False,
    }
    assert transport.sent == []


def test_alert_service_sends_to_transport_when_discord_configured(monkeypatch):
    transport = InMemoryAlertTransport()
    monkeypatch.setattr("app.services.thirteenf_alerts.settings.DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

    alert = emit_alert(
        severity="P2",
        title="Job lease expired",
        message="Worker stopped heartbeating",
        transport=transport,
    )

    assert alert["sent"] is True
    assert transport.sent == [
        {
            "webhook_url": "https://discord.example/webhook",
            "payload": {
                "content": "[P2] Job lease expired\nWorker stopped heartbeating",
            },
        }
    ]


def test_alert_service_accepts_p3_without_webhook(monkeypatch):
    monkeypatch.setattr("app.services.thirteenf_alerts.settings.DISCORD_WEBHOOK_URL", None)

    alert = emit_alert(severity="P3", title="Needs review stale", message="Manual review is overdue")

    assert alert["severity"] == "P3"
    assert alert["sent"] is False


def test_alert_service_rejects_unknown_severity():
    with pytest.raises(ValueError):
        emit_alert(severity="P4", title="Bad severity", message="Invalid")
