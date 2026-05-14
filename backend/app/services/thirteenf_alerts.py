from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.core.config import settings


class AlertTransport(Protocol):
    def send(self, webhook_url: str, payload: dict[str, Any]) -> None:
        ...


class DiscordWebhookTransport:
    def send(self, webhook_url: str, payload: dict[str, Any]) -> None:
        with httpx.Client(timeout=10.0) as client:
            client.post(webhook_url, json=payload)


class InMemoryAlertTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, webhook_url: str, payload: dict[str, Any]) -> None:
        self.sent.append({"webhook_url": webhook_url, "payload": payload})


def emit_alert(
    *,
    severity: str,
    title: str,
    message: str,
    context: dict[str, Any] | None = None,
    transport: AlertTransport | None = None,
) -> dict[str, Any]:
    if severity not in {"P1", "P2", "P3"}:
        raise ValueError("severity must be one of: P1, P2, P3")

    webhook_url = settings.DISCORD_WEBHOOK_URL
    sent = False
    if webhook_url:
        transport = transport or DiscordWebhookTransport()
        transport.send(webhook_url, {"content": f"[{severity}] {title}\n{message}"})
        sent = True

    return {
        "severity": severity,
        "title": title,
        "message": message,
        "context": context or {},
        "sent": sent,
    }
