"""User-owned follows and fail-closed research notification delivery.

Logical notifications are durable, append-only facts. Mutable inbox state and
delivery attempts are projections/outbox records. Destination secrets are only
decrypted at the adapter boundary and are never serialized or logged.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import smtplib
from datetime import datetime, time, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.institutions import Filing13F, InstitutionManager, JobRun
from app.models.notifications import (
    LogicalNotification,
    ManagerFollow,
    NotificationDeliveryAttempt,
    NotificationDeliveryEvent,
    NotificationDestination,
    NotificationEmailChallenge,
    NotificationInboxState,
    NotificationPriceAlertState,
    NotificationSubscription,
)


EVENT_FAMILIES = {
    "followed_manager_filed",
    "followed_manager_position_changed",
    "intrinsic_value_threshold_crossed",
    "research_review_due",
    "research_coverage_changed",
    "filing_season_digest",
    "destination_test",
}
_SLACK_PATH = re.compile(r"^/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]+$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MAX_DELIVERY_ATTEMPTS = 5


class NotificationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _keyring() -> list[tuple[str, Fernet]]:
    configured = settings.NOTIFICATION_SECRET_KEYS
    if not configured:
        raise NotificationError(
            "destination_encryption_unconfigured",
            "Destination encryption is not configured.",
            status_code=503,
        )
    result: list[tuple[str, Fernet]] = []
    for entry in configured.split(","):
        version, separator, encoded = entry.strip().partition(":")
        if not separator or not version or not encoded:
            raise NotificationError(
                "destination_encryption_invalid",
                "Destination encryption configuration is invalid.",
                status_code=503,
            )
        try:
            result.append((version, Fernet(encoded.encode("ascii"))))
        except (ValueError, TypeError) as exc:
            raise NotificationError(
                "destination_encryption_invalid",
                "Destination encryption configuration is invalid.",
                status_code=503,
            ) from exc
    if not 1 <= len(result) <= 2 or len({version for version, _ in result}) != len(result):
        raise NotificationError(
            "destination_encryption_window_invalid",
            "Destination encryption must contain one current key and at most one previous key.",
            status_code=503,
        )
    return result


def _encrypt(value: str) -> tuple[str, str]:
    version, cipher = _keyring()[0]
    return cipher.encrypt(value.encode("utf-8")).decode("ascii"), version


def _decrypt(destination: NotificationDestination) -> str:
    try:
        cipher = dict(_keyring())[destination.key_version]
        return cipher.decrypt(destination.secret_ciphertext.encode("ascii")).decode("utf-8")
    except (KeyError, InvalidToken, UnicodeDecodeError) as exc:
        raise NotificationError(
            "destination_secret_unreadable",
            "Destination secret cannot be decrypted with the active key window.",
            status_code=503,
        ) from exc


def _validate_slack_webhook(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "hooks.slack.com"
        or parsed.port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not _SLACK_PATH.fullmatch(parsed.path)
    ):
        raise NotificationError(
            "invalid_slack_destination",
            "Only an approved Slack Incoming Webhook HTTPS URL is accepted.",
        )
    return f"https://hooks.slack.com{parsed.path}"


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise NotificationError("invalid_timezone", "Timezone must be a valid IANA name.") from exc
    return value


def _validate_clock(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        time.fromisoformat(value)
    except ValueError as exc:
        raise NotificationError("invalid_quiet_hours", "Quiet hours must use HH:MM.") from exc
    if len(value) != 5:
        raise NotificationError("invalid_quiet_hours", "Quiet hours must use HH:MM.")
    return value


def follow_manager(
    session: Session, *, user_id: int, manager_id: int
) -> tuple[ManagerFollow, bool]:
    manager = session.get(InstitutionManager, manager_id)
    if manager is None or manager.status != "active":
        raise NotificationError("manager_not_found", "Manager not found.", status_code=404)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"manager-follow:{user_id}:{manager_id}"},
    )
    existing = (
        session.query(ManagerFollow).filter_by(user_id=user_id, manager_id=manager_id).one_or_none()
    )
    if existing:
        return existing, False
    row = ManagerFollow(user_id=user_id, manager_id=manager_id)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row, True


def list_follows(session: Session, *, user_id: int) -> list[ManagerFollow]:
    return (
        session.query(ManagerFollow)
        .join(InstitutionManager, InstitutionManager.id == ManagerFollow.manager_id)
        .filter(ManagerFollow.user_id == user_id)
        .order_by(InstitutionManager.display_name, InstitutionManager.canonical_name, ManagerFollow.id)
        .all()
    )


def unfollow_manager(session: Session, *, user_id: int, follow_id: int) -> None:
    row = (
        session.query(ManagerFollow)
        .filter(ManagerFollow.id == follow_id, ManagerFollow.user_id == user_id)
        .one_or_none()
    )
    if row is None:
        raise NotificationError("manager_follow_not_found", "Manager follow not found.", status_code=404)
    session.delete(row)
    session.commit()


def create_or_update_slack_destination(
    session: Session,
    *,
    user_id: int,
    label: str,
    webhook_url: str,
    consent: bool,
    destination_id: int | None = None,
) -> tuple[NotificationDestination, bool]:
    if not consent:
        raise NotificationError("consent_required", "Explicit destination consent is required.")
    if not label.strip() or len(label.strip()) > 120:
        raise NotificationError("invalid_destination_label", "Destination label is required.")
    normalized = _validate_slack_webhook(webhook_url)
    ciphertext, key_version = _encrypt(normalized)
    row = None
    if destination_id is not None:
        row = (
            session.query(NotificationDestination)
            .filter(
                NotificationDestination.id == destination_id,
                NotificationDestination.user_id == user_id,
                NotificationDestination.channel == "slack",
            )
            .one_or_none()
        )
        if row is None:
            raise NotificationError("destination_not_found", "Destination not found.", status_code=404)
    created = row is None
    if row is None:
        row = NotificationDestination(
            user_id=user_id,
            channel="slack",
            label=label.strip(),
            destination_hint=f"hooks.slack.com/…/{normalized[-4:]}",
            secret_ciphertext=ciphertext,
            key_version=key_version,
            status="enabled",
            consented_at=_utcnow(),
            verified_at=_utcnow(),
        )
        session.add(row)
    else:
        row.label = label.strip()
        row.destination_hint = f"hooks.slack.com/…/{normalized[-4:]}"
        row.secret_ciphertext = ciphertext
        row.key_version = key_version
        row.status = "enabled"
        row.consented_at = _utcnow()
        row.verified_at = _utcnow()
        row.revoked_at = None
        row.last_error_class = None
    session.commit()
    session.refresh(row)
    return row, created


def _default_verification_sender(email: str, token: str) -> bool:
    if (
        not settings.SMTP_HOST
        or not settings.SMTP_FROM
        or not settings.SMTP_TLS_REQUIRED
    ):
        raise NotificationError(
            "email_provider_unconfigured",
            "TLS email delivery is not configured.",
            status_code=503,
        )
    message = EmailMessage()
    message["Subject"] = "Verify your ValuePilot notification destination"
    message["From"] = settings.SMTP_FROM
    message["To"] = email
    message.set_content(
        f"Verify this notification destination with this one-time code:\n\n{token}\n"
    )
    try:
        with smtplib.SMTP(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        ) as smtp:
            smtp.starttls()
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise NotificationError(
            "email_provider_transient_failure",
            "Verification email could not be accepted by the configured provider.",
            status_code=503,
        ) from exc
    return True


def create_email_destination(
    session: Session,
    *,
    user_id: int,
    label: str,
    email: str,
    consent: bool,
    verification_sender: Callable[[str, str], bool] | None = None,
) -> tuple[NotificationDestination, str]:
    if not consent:
        raise NotificationError("consent_required", "Explicit destination consent is required.")
    normalized = email.strip().lower()
    if len(normalized) > 320 or not _EMAIL.fullmatch(normalized):
        raise NotificationError("invalid_email_destination", "Email destination is invalid.")
    if not label.strip() or len(label.strip()) > 120:
        raise NotificationError("invalid_destination_label", "Destination label is required.")
    ciphertext, key_version = _encrypt(normalized)
    token = secrets.token_urlsafe(24)
    challenge = NotificationEmailChallenge(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=_utcnow() + timedelta(minutes=30),
    )
    destination = NotificationDestination(
        user_id=user_id,
        channel="email",
        label=label.strip(),
        destination_hint=f"{normalized[:1]}***@{normalized.rsplit('@', 1)[1]}",
        secret_ciphertext=ciphertext,
        key_version=key_version,
        status="pending_verification",
        consented_at=_utcnow(),
    )
    destination.verification_challenges.append(challenge)
    session.add(destination)
    sender = verification_sender or _default_verification_sender
    try:
        if sender(normalized, token) is not True:
            raise NotificationError(
                "email_provider_rejected",
                "Verification email was not accepted by the provider.",
                status_code=503,
            )
    except Exception:
        session.rollback()
        raise
    session.commit()
    session.refresh(destination)
    return destination, token


def verify_email_destination(
    session: Session, *, user_id: int, destination_id: int, token: str
) -> NotificationDestination:
    destination = (
        session.query(NotificationDestination)
        .filter(
            NotificationDestination.id == destination_id,
            NotificationDestination.user_id == user_id,
            NotificationDestination.channel == "email",
        )
        .one_or_none()
    )
    if destination is None:
        raise NotificationError("destination_not_found", "Destination not found.", status_code=404)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    challenge = (
        session.query(NotificationEmailChallenge)
        .filter_by(destination_id=destination.id, token_hash=token_hash)
        .with_for_update()
        .one_or_none()
    )
    now = _utcnow()
    if challenge is None:
        raise NotificationError("verification_invalid", "Verification challenge is invalid.")
    if challenge.used_at is not None:
        raise NotificationError("verification_used", "Verification challenge was already used.", status_code=409)
    if challenge.expires_at < now:
        raise NotificationError("verification_expired", "Verification challenge expired.", status_code=409)
    challenge.used_at = now
    destination.status = "enabled"
    destination.verified_at = now
    session.commit()
    session.refresh(destination)
    return destination


def revoke_destination(session: Session, *, user_id: int, destination_id: int) -> None:
    row = (
        session.query(NotificationDestination)
        .filter(
            NotificationDestination.id == destination_id,
            NotificationDestination.user_id == user_id,
        )
        .one_or_none()
    )
    if row is None:
        raise NotificationError("destination_not_found", "Destination not found.", status_code=404)
    row.status = "revoked"
    row.revoked_at = _utcnow()
    row.secret_ciphertext = Fernet.generate_key().decode("ascii")
    row.key_version = "revoked"
    row.last_error_class = None
    for subscription in session.query(NotificationSubscription).filter_by(
        user_id=user_id, destination_id=row.id
    ):
        subscription.is_enabled = False
    session.commit()


def rotate_destination_secrets(session: Session, *, limit: int = 100) -> dict[str, int]:
    keyring = _keyring()
    current_version = keyring[0][0]
    rows = (
        session.query(NotificationDestination)
        .filter(
            NotificationDestination.status.notin_(["revoked"]),
            NotificationDestination.key_version != current_version,
        )
        .order_by(NotificationDestination.id)
        .limit(min(max(limit, 1), 500))
        .with_for_update(skip_locked=True)
        .all()
    )
    rotated = blocked = 0
    for row in rows:
        try:
            secret = _decrypt(row)
            row.secret_ciphertext, row.key_version = _encrypt(secret)
            row.last_error_class = None
            rotated += 1
        except NotificationError:
            row.status = "configuration_blocked"
            row.last_error_class = "destination_secret_unreadable"
            blocked += 1
    session.commit()
    return {"rotated": rotated, "configuration_blocked": blocked}


def destination_secret_rotation_needed(session: Session) -> bool:
    """Return whether rotation work or a configuration audit is required."""
    try:
        current_version = _keyring()[0][0]
    except NotificationError:
        # Let the audited runner record the configuration failure once invoked.
        return True
    return (
        session.query(NotificationDestination.id)
        .filter(
            NotificationDestination.status != "revoked",
            NotificationDestination.key_version != current_version,
        )
        .first()
        is not None
    )


def run_destination_secret_rotation(
    session: Session, *, limit: int = 100
) -> dict[str, int | str]:
    """Run a bounded key rotation with durable, credential-free job audit."""
    bounded_limit = min(max(limit, 1), 500)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "notification-secret-rotation"},
    )
    active = (
        session.query(JobRun)
        .filter(
            JobRun.job_type == "notification_secret_rotation",
            JobRun.status.in_(["queued", "running", "cancel_requested"]),
        )
        .order_by(JobRun.id.desc())
        .first()
    )
    if active is not None:
        session.rollback()
        return {
            "job_id": active.id,
            "status": "already_running",
            "rotated": 0,
            "configuration_blocked": 0,
        }
    now = _utcnow()
    job = JobRun(
        job_type="notification_secret_rotation",
        status="running",
        trigger_source="scheduler",
        lock_key="notification_secret_rotation",
        dedupe_key=f"notification_secret_rotation:{now.isoformat()}",
        input_json={"limit": bounded_limit},
        started_at=now,
        heartbeat_at=now,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    try:
        result = rotate_destination_secrets(session, limit=bounded_limit)
        finished_at = _utcnow()
        job = session.get(JobRun, job.id)
        assert job is not None
        job.status = "succeeded"
        job.summary_json = {**result, "limit": bounded_limit}
        job.finished_at = finished_at
        job.heartbeat_at = finished_at
        session.commit()
        return {"job_id": job.id, "status": job.status, **result}
    except Exception as error:
        session.rollback()
        finished_at = _utcnow()
        job = session.get(JobRun, job.id)
        assert job is not None
        job.status = "failed"
        job.error_message = type(error).__name__
        job.finished_at = finished_at
        job.heartbeat_at = finished_at
        session.commit()
        return {
            "job_id": job.id,
            "status": job.status,
            "rotated": 0,
            "configuration_blocked": 0,
        }


def upsert_subscription(
    session: Session,
    *,
    user_id: int,
    event_family: str,
    destination_id: int | None,
    frequency: str,
    timezone_name: str,
    quiet_start_local: str | None,
    quiet_end_local: str | None,
    cooldown_minutes: int,
    threshold_ratio: float | None = None,
    hysteresis_ratio: float = 0.02,
    is_enabled: bool,
) -> NotificationSubscription:
    if event_family not in EVENT_FAMILIES - {"destination_test"}:
        raise NotificationError("invalid_event_family", "Notification event family is invalid.")
    if frequency not in {"immediate", "daily_digest", "weekly_digest"}:
        raise NotificationError("invalid_frequency", "Notification frequency is invalid.")
    if destination_id is None and frequency != "immediate":
        raise NotificationError(
            "in_app_frequency_invalid",
            "In-app notification history is always immediate.",
        )
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"notification-subscription:{user_id}:{event_family}"},
    )
    _validate_timezone(timezone_name)
    quiet_start_local = _validate_clock(quiet_start_local)
    quiet_end_local = _validate_clock(quiet_end_local)
    if (quiet_start_local is None) != (quiet_end_local is None):
        raise NotificationError("invalid_quiet_hours", "Both quiet-hour boundaries are required.")
    if not 0 <= cooldown_minutes <= 43200:
        raise NotificationError("invalid_cooldown", "Cooldown is outside the supported range.")
    if event_family == "intrinsic_value_threshold_crossed":
        if threshold_ratio is None or not 0 <= threshold_ratio <= 0.95:
            raise NotificationError(
                "invalid_threshold", "Intrinsic-value alerts require a valid threshold ratio."
            )
    elif threshold_ratio is not None:
        raise NotificationError(
            "invalid_threshold", "Threshold ratio applies only to intrinsic-value alerts."
        )
    if not 0 <= hysteresis_ratio <= 0.25:
        raise NotificationError("invalid_hysteresis", "Hysteresis ratio is invalid.")
    if destination_id is not None:
        destination = (
            session.query(NotificationDestination)
            .filter(
                NotificationDestination.id == destination_id,
                NotificationDestination.user_id == user_id,
                NotificationDestination.status == "enabled",
            )
            .one_or_none()
        )
        if destination is None:
            raise NotificationError("destination_not_found", "Destination not found.", status_code=404)
    query = session.query(NotificationSubscription).filter_by(
        user_id=user_id,
        event_family=event_family,
    )
    if destination_id is None:
        query = query.filter(NotificationSubscription.destination_id.is_(None))
    else:
        query = query.filter(NotificationSubscription.destination_id == destination_id)
    row = query.one_or_none()
    if row is None:
        row = NotificationSubscription(
            user_id=user_id,
            event_family=event_family,
            destination_id=destination_id,
        )
        session.add(row)
    row.frequency = frequency
    row.timezone = timezone_name
    row.quiet_start_local = quiet_start_local
    row.quiet_end_local = quiet_end_local
    row.cooldown_minutes = cooldown_minutes
    row.threshold_ratio = threshold_ratio
    row.hysteresis_ratio = hysteresis_ratio
    row.is_enabled = is_enabled
    session.flush()
    if event_family == "intrinsic_value_threshold_crossed":
        # Crossing state is one user/stock projection, so its boundary policy
        # must be one user/event policy as well. Channel frequency, timezone,
        # quiet hours and enablement remain destination-specific.
        sibling_rows = (
            session.query(NotificationSubscription)
            .filter_by(
                user_id=user_id,
                event_family="intrinsic_value_threshold_crossed",
            )
            .all()
        )
        for sibling in sibling_rows:
            sibling.threshold_ratio = threshold_ratio
            sibling.hysteresis_ratio = hysteresis_ratio
            sibling.cooldown_minutes = cooldown_minutes
    session.commit()
    session.refresh(row)
    return row


def is_delivery_time_allowed(
    subscription: NotificationSubscription | None, now: datetime
) -> bool:
    if subscription is None:
        return True
    if not subscription.quiet_start_local or not subscription.quiet_end_local:
        return True
    try:
        local = now.astimezone(ZoneInfo(subscription.timezone)).time().replace(tzinfo=None)
    except ZoneInfoNotFoundError:
        return False
    start = time.fromisoformat(subscription.quiet_start_local)
    end = time.fromisoformat(subscription.quiet_end_local)
    if start == end:
        return True
    quiet = start <= local < end if start < end else local >= start or local < end
    return not quiet


def _queue_external_attempts(
    session: Session, notification: LogicalNotification, *, now: datetime
) -> None:
    subscriptions = (
        session.query(NotificationSubscription)
        .join(
            NotificationDestination,
            NotificationDestination.id == NotificationSubscription.destination_id,
        )
        .filter(
            NotificationSubscription.user_id == notification.user_id,
            NotificationSubscription.event_family == notification.event_family,
            NotificationSubscription.is_enabled.is_(True),
            NotificationSubscription.destination_id.isnot(None),
            NotificationDestination.status == "enabled",
        )
        .all()
    )
    for subscription in subscriptions:
        if subscription.frequency != "immediate":
            continue
        last_success = (
            session.query(NotificationDeliveryAttempt)
            .join(
                LogicalNotification,
                LogicalNotification.id
                == NotificationDeliveryAttempt.logical_notification_id,
            )
            .filter(
                NotificationDeliveryAttempt.destination_id
                == subscription.destination_id,
                NotificationDeliveryAttempt.status == "succeeded",
                LogicalNotification.user_id == notification.user_id,
                LogicalNotification.event_family == notification.event_family,
            )
            .order_by(NotificationDeliveryAttempt.succeeded_at.desc().nullslast())
            .first()
        )
        cooldown_ends = (
            last_success.succeeded_at
            + timedelta(minutes=subscription.cooldown_minutes)
            if last_success and last_success.succeeded_at
            else now
        )
        scheduled_for = max(now, cooldown_ends)
        attempt = NotificationDeliveryAttempt(
            logical_notification_id=notification.id,
            destination_id=subscription.destination_id,
            content_version=notification.content_version,
            status="queued",
            scheduled_for=scheduled_for,
            next_attempt_at=scheduled_for,
        )
        session.add(attempt)
        session.flush()
        session.add(
            NotificationDeliveryEvent(
                attempt_id=attempt.id,
                event_type="queued",
                payload_json={"event_family": notification.event_family},
            )
        )


def produce_notification(
    session: Session,
    *,
    user_id: int,
    event_family: str,
    subject_type: str,
    subject_key: str,
    source_version: str,
    title: str,
    body: str,
    evidence_route: str,
    case_id: int | None = None,
    stock_id: int | None = None,
    manager_id: int | None = None,
    payload: dict[str, Any] | None = None,
    severity: str = "info",
    supersedes_notification_id: int | None = None,
) -> tuple[LogicalNotification, bool]:
    if event_family not in EVENT_FAMILIES:
        raise NotificationError("invalid_event_family", "Notification event family is invalid.")
    if not subject_type or len(subject_type) > 40 or not subject_key or len(subject_key) > 240:
        raise NotificationError("invalid_notification_subject", "Notification subject is invalid.")
    if not source_version or len(source_version) > 240:
        raise NotificationError("invalid_source_version", "Notification source version is invalid.")
    if not title.strip() or len(title.strip()) > 240 or not body.strip() or len(body.strip()) > 4000:
        raise NotificationError("invalid_notification_content", "Notification content is invalid.")
    if not evidence_route.startswith("/") or evidence_route.startswith("//") or len(evidence_route) > 500:
        raise NotificationError("invalid_evidence_route", "Evidence route must be an internal route.")
    logical_key = f"{event_family}:{subject_key}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"logical-notification:{user_id}:{logical_key}:{source_version}"},
    )
    existing = (
        session.query(LogicalNotification)
        .filter_by(user_id=user_id, logical_key=logical_key, source_version=source_version)
        .one_or_none()
    )
    if existing:
        return existing, False
    if supersedes_notification_id is not None:
        prior = (
            session.query(LogicalNotification)
            .filter(
                LogicalNotification.id == supersedes_notification_id,
                LogicalNotification.user_id == user_id,
                LogicalNotification.logical_key == logical_key,
            )
            .one_or_none()
        )
        if prior is None:
            raise NotificationError("superseded_notification_not_found", "Prior notification not found.")
    now = _utcnow()
    row = LogicalNotification(
        user_id=user_id,
        event_family=event_family,
        subject_type=subject_type,
        subject_key=subject_key,
        logical_key=logical_key,
        source_version=source_version,
        content_version=1,
        correction_type="correction" if supersedes_notification_id else "original",
        supersedes_notification_id=supersedes_notification_id,
        case_id=case_id,
        stock_id=stock_id,
        manager_id=manager_id,
        title=title.strip(),
        body=body.strip(),
        evidence_route=evidence_route,
        payload_json=payload,
        severity=severity,
    )
    session.add(row)
    session.flush()
    session.add(NotificationInboxState(logical_notification_id=row.id, user_id=user_id))
    _queue_external_attempts(session, row, now=now)
    session.commit()
    session.refresh(row)
    return row, True


def materialize_followed_manager_filing(session: Session, *, filing_id: int) -> int:
    filing = session.get(Filing13F, filing_id)
    if filing is None or not filing.is_active_for_manager_period or filing.parse_status != "succeeded":
        raise NotificationError("filing_unavailable", "An active parsed filing is required.")
    manager = session.get(InstitutionManager, filing.manager_id)
    assert manager is not None
    source_version = ":".join(
        [
            filing.accession_number or filing.accession_no,
            filing.parser_version or "parser-unknown",
            filing.effective_value_unit_override or "infer",
        ]
    )
    prior_filing = None
    if filing.is_amendment:
        prior_filing = (
            session.query(Filing13F)
            .filter(
                Filing13F.manager_id == filing.manager_id,
                Filing13F.report_quarter == filing.report_quarter,
                Filing13F.id != filing.id,
            )
            .order_by(Filing13F.version_rank.desc(), Filing13F.id.desc())
            .first()
        )
    created = 0
    for follow in session.query(ManagerFollow).filter_by(manager_id=filing.manager_id).all():
        subject_key = f"manager:{filing.manager_id}:{filing.report_quarter}"
        supersedes_id = None
        if prior_filing is not None:
            prior_accession = prior_filing.accession_number or prior_filing.accession_no
            prior = (
                session.query(LogicalNotification)
                .filter(
                    LogicalNotification.user_id == follow.user_id,
                    LogicalNotification.logical_key == f"followed_manager_filed:{subject_key}",
                    LogicalNotification.source_version.like(f"{prior_accession}:%"),
                )
                .order_by(LogicalNotification.id.desc())
                .first()
            )
            supersedes_id = prior.id if prior else None
        _, was_created = produce_notification(
            session,
            user_id=follow.user_id,
            event_family="followed_manager_filed",
            subject_type="manager",
            subject_key=subject_key,
            source_version=source_version,
            title=(
                f"{manager.display_name or manager.canonical_name} filing corrected"
                if supersedes_id
                else f"{manager.display_name or manager.canonical_name} filed a 13F"
            ),
            body=(
                "A superseding amendment changed the delayed filing evidence. Review the correction before drawing conclusions."
                if supersedes_id
                else "A delayed quarter-end filing is available. Treat it as a research prompt, not a current trade signal."
            ),
            evidence_route=f"/13f/managers/{manager.id}",
            manager_id=manager.id,
            payload={
                "filing_id": filing.id,
                "accession_number": filing.accession_number or filing.accession_no,
                "report_quarter": filing.report_quarter,
            },
            supersedes_notification_id=supersedes_id,
        )
        created += int(was_created)
    return created


def materialize_due_research_reviews(
    session: Session, *, as_of: datetime
) -> int:
    """Create one durable due event per case/head/review date.

    ``next_review_on`` is a user calendar date. We resolve "today" in each
    user's subscribed IANA timezone when available, falling back to UTC only
    when no preference exists. Execution timestamps remain UTC.
    """
    from app.models.research import ResearchCase
    from app.models.users import User

    created = 0
    cases = (
        session.query(ResearchCase, User)
        .join(User, User.id == ResearchCase.user_id)
        .filter(
            ResearchCase.state == "monitoring",
            ResearchCase.next_review_on.isnot(None),
            User.is_active.is_(True),
        )
        .order_by(ResearchCase.user_id, ResearchCase.id)
        .all()
    )
    for case, _user in cases:
        preference = (
            session.query(NotificationSubscription)
            .filter(
                NotificationSubscription.user_id == case.user_id,
                NotificationSubscription.event_family == "research_review_due",
                NotificationSubscription.is_enabled.is_(True),
            )
            .order_by(NotificationSubscription.destination_id.asc().nullsfirst())
            .first()
        )
        timezone_name = preference.timezone if preference else "UTC"
        try:
            local_date = as_of.astimezone(ZoneInfo(timezone_name)).date()
        except ZoneInfoNotFoundError:
            local_date = as_of.date()
        if case.next_review_on is None or case.next_review_on > local_date:
            continue
        _, was_created = produce_notification(
            session,
            user_id=case.user_id,
            event_family="research_review_due",
            subject_type="research_case",
            subject_key=f"case:{case.id}:review:{case.next_review_on.isoformat()}",
            source_version=f"case-{case.id}-head-{case.head_revision_number}",
            title=f"Research review is due for case #{case.id}",
            body=(
                "Re-read the recorded thesis, disconfirming evidence, valuation, "
                "and current data before renewing or changing the decision."
            ),
            evidence_route=f"/research/cases/{case.id}",
            case_id=case.id,
            stock_id=case.stock_id,
            severity="warning" if case.next_review_on < local_date else "info",
        )
        created += int(was_created)
    return created


def materialize_research_coverage_changes(session: Session) -> int:
    """Project committed ready/failed coverage states into durable case events."""
    from app.models.coverage import ResearchCoverageRequirement
    from app.models.research import ResearchCase
    from app.models.stocks import Stock
    from app.services.research_coverage import serialize_requirements

    rows = (
        session.query(ResearchCoverageRequirement, ResearchCase, Stock)
        .join(
            ResearchCase,
            (ResearchCase.user_id == ResearchCoverageRequirement.user_id)
            & (ResearchCase.stock_id == ResearchCoverageRequirement.stock_id),
        )
        .join(Stock, Stock.id == ResearchCoverageRequirement.stock_id)
        .filter(
            ResearchCoverageRequirement.is_current.is_(True),
            ResearchCoverageRequirement.state.in_(["ready", "failed"]),
            ResearchCase.state.in_(["queued", "researching", "monitoring"]),
        )
        .order_by(
            ResearchCoverageRequirement.user_id,
            ResearchCase.id,
            ResearchCoverageRequirement.kind,
        )
        .all()
    )
    serialized_rows = serialize_requirements(
        session,
        [(requirement, stock) for requirement, _, stock in rows],
        evaluated_at=datetime.now(timezone.utc),
    )
    created = 0
    for (requirement, case, stock), serialized in zip(rows, serialized_rows):
        if serialized["state"] not in {"ready", "failed"}:
            continue
        evidence_version = hashlib.sha256(
            json.dumps(
                {
                    "state": serialized["state"],
                    "reason_code": serialized["reason_code"],
                    "source_type": serialized["source_type"],
                    "source_ref_id": serialized["source_ref_id"],
                    "observed_at": (
                        requirement.observed_at.isoformat()
                        if requirement.observed_at
                        else None
                    ),
                    "evidence": serialized["evidence"],
                    "freshness_policy_version": requirement.freshness_policy_version,
                },
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:24]
        source_version = ":".join(
            [
                requirement.priority_policy_version,
                requirement.kind,
                serialized["state"],
                evidence_version,
            ]
        )
        was_ready = serialized["state"] == "ready"
        _, was_created = produce_notification(
            session,
            user_id=requirement.user_id,
            event_family="research_coverage_changed",
            subject_type="research_case",
            subject_key=f"case:{case.id}:coverage:{requirement.kind}",
            source_version=source_version,
            title=(
                f"{stock.ticker} coverage is ready"
                if was_ready
                else f"{stock.ticker} coverage failed"
            ),
            body=(
                f"{requirement.kind.replace('_', ' ')} is ready for the open research case. "
                "Review the source and continue independent research."
                if was_ready
                else f"{requirement.kind.replace('_', ' ')} failed: {serialized['reason']}"
            ),
            evidence_route=f"/research/cases/{case.id}",
            case_id=case.id,
            stock_id=stock.id,
            severity="info" if was_ready else "warning",
            payload={
                "coverage_requirement_id": requirement.id,
                "kind": requirement.kind,
                "state": serialized["state"],
                "reason_code": serialized["reason_code"],
                "source_type": serialized["source_type"],
                "source_ref_id": serialized["source_ref_id"],
            },
        )
        created += int(was_created)
    return created


def materialize_followed_manager_position_changes(
    session: Session, *, report_quarter: str
) -> int:
    """Notify only when a followed manager changed a user-scoped stock."""
    from app.models.institutions import Filing13F, OwnershipChange13F
    from app.models.research import ResearchCase
    from app.models.stocks import PoolMembership, Stock

    changes = (
        session.query(OwnershipChange13F)
        .filter(
            OwnershipChange13F.report_quarter == report_quarter,
            OwnershipChange13F.stock_id.isnot(None),
            OwnershipChange13F.change_status.in_(
                ["new_position", "increased", "reduced", "exited_position"]
            ),
        )
        .order_by(OwnershipChange13F.manager_id, OwnershipChange13F.stock_id)
        .all()
    )
    created = 0
    for change in changes:
        filing = session.get(Filing13F, change.current_filing_id) if change.current_filing_id else None
        source_version = ":".join(
            [
                (filing.accession_number or filing.accession_no) if filing else "no-current-filing",
                str(change.current_parse_run_id or "no-parse-run"),
                str(change.id),
            ]
        )
        stock = session.get(Stock, change.stock_id)
        manager = session.get(InstitutionManager, change.manager_id)
        if stock is None or manager is None:
            continue
        follower_ids = {
            user_id
            for (user_id,) in session.query(ManagerFollow.user_id)
            .filter(ManagerFollow.manager_id == change.manager_id)
            .all()
        }
        if not follower_ids:
            continue
        scoped_user_ids = {
            user_id
            for (user_id,) in session.query(PoolMembership.user_id)
            .filter(
                PoolMembership.user_id.in_(follower_ids),
                PoolMembership.stock_id == change.stock_id,
            )
            .distinct()
            .all()
        }
        scoped_user_ids.update(
            user_id
            for (user_id,) in session.query(ResearchCase.user_id)
            .filter(
                ResearchCase.user_id.in_(follower_ids),
                ResearchCase.stock_id == change.stock_id,
                ResearchCase.state.in_(["queued", "researching", "monitoring"]),
            )
            .distinct()
            .all()
        )
        for user_id in sorted(scoped_user_ids):
            _, was_created = produce_notification(
                session,
                user_id=user_id,
                event_family="followed_manager_position_changed",
                subject_type="manager_stock",
                subject_key=(
                    f"manager:{change.manager_id}:stock:{change.stock_id}:"
                    f"quarter:{report_quarter}:change:{change.change_status}"
                ),
                source_version=source_version,
                title=(
                    f"{manager.display_name or manager.canonical_name} reported "
                    f"{change.change_status.replace('_', ' ')} in {stock.ticker}"
                ),
                body=(
                    "This is a delayed quarter-end 13F comparison, not a current trade, "
                    "cost basis, or recommendation. Review the filing caveats."
                ),
                evidence_route=f"/13f/managers/{manager.id}?view=activity",
                stock_id=stock.id,
                manager_id=manager.id,
                payload={
                    "ownership_change_id": change.id,
                    "report_quarter": report_quarter,
                    "change_status": change.change_status,
                },
            )
            created += int(was_created)
    return created


def materialize_intrinsic_value_crossings(
    session: Session, *, as_of: datetime
) -> int:
    """Evaluate USD price-to-user-value crossings with initialization/noise guards."""
    from app.models.research import ResearchCase, ResearchCaseRevision
    from app.models.stocks import Stock
    from app.services.market_data_service import read_current_eod_price
    from app.services.valuation import read_valuation_context

    created = 0
    policies = (
        session.query(NotificationSubscription)
        .filter(
            NotificationSubscription.event_family == "intrinsic_value_threshold_crossed",
            NotificationSubscription.is_enabled.is_(True),
            NotificationSubscription.threshold_ratio.isnot(None),
        )
        .order_by(
            NotificationSubscription.user_id,
            NotificationSubscription.destination_id.asc().nullsfirst(),
            NotificationSubscription.id,
        )
        .all()
    )
    policy_by_user: dict[int, NotificationSubscription] = {}
    for policy in policies:
        policy_by_user.setdefault(policy.user_id, policy)
    for user_id, policy in policy_by_user.items():
        cases = (
            session.query(ResearchCase)
            .filter(
                ResearchCase.user_id == user_id,
                ResearchCase.state == "monitoring",
                ResearchCase.decision.in_(["watch", "own"]),
            )
            .all()
        )
        for case in cases:
            # Multiple API replicas may run the independent scheduler. Lock
            # before reading/creating the one user-stock projection so the
            # initial no-row case cannot race the unique constraint.
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"notification-price-alert:{user_id}:{case.stock_id}"},
            )
            head_revision = (
                session.query(ResearchCaseRevision)
                .filter_by(
                    case_id=case.id,
                    revision_number=case.head_revision_number,
                )
                .one_or_none()
            )
            research_revision_id = head_revision.id if head_revision else None
            stock = session.get(Stock, case.stock_id)
            if stock is None:
                continue
            price = read_current_eod_price(
                session, stock=stock, evaluated_at=as_of
            )
            valuation = read_valuation_context(
                session, user_id=user_id, stock_id=case.stock_id
            )
            if (
                price.status != "available"
                or price.current_value is None
                or price.price_id is None
                or price.currency != valuation.user_intrinsic_value_currency
                or price.freshness_state != "fresh"
                or valuation.user_intrinsic_value is None
                or valuation.user_intrinsic_value_fact_id is None
            ):
                continue
            state = (
                session.query(NotificationPriceAlertState)
                .filter_by(user_id=user_id, stock_id=case.stock_id)
                .with_for_update()
                .one_or_none()
            )
            valuation_changed = bool(
                state is not None
                and state.last_valuation_fact_id
                != valuation.user_intrinsic_value_fact_id
            )
            policy_changed = bool(
                state is not None
                and (
                    state.last_threshold_ratio is None
                    or state.last_hysteresis_ratio is None
                    or float(state.last_threshold_ratio)
                    != float(policy.threshold_ratio)
                    or float(state.last_hysteresis_ratio)
                    != float(policy.hysteresis_ratio)
                )
            )
            decision_changed = bool(
                state is not None
                and state.last_research_revision_id != research_revision_id
            )
            boundary_changed = valuation_changed or policy_changed or decision_changed
            if (
                state is not None
                and state.last_price_id == price.price_id
                and not boundary_changed
            ):
                continue
            fair_value = valuation.user_intrinsic_value
            boundary = fair_value * (1 - float(policy.threshold_ratio))
            hysteresis = fair_value * float(policy.hysteresis_ratio)
            close = float(price.current_value)
            if state is None or state.last_side is None or boundary_changed:
                side = "below" if close < boundary else "above"
                if state is None:
                    state = NotificationPriceAlertState(
                        user_id=user_id,
                        stock_id=case.stock_id,
                    )
                    session.add(state)
                state.last_price_id = price.price_id
                state.last_valuation_fact_id = (
                    valuation.user_intrinsic_value_fact_id
                )
                state.last_research_revision_id = research_revision_id
                state.last_threshold_ratio = policy.threshold_ratio
                state.last_hysteresis_ratio = policy.hysteresis_ratio
                state.last_side = side
                state.consecutive_fresh_count = 1
                session.commit()
                continue
            prior_side = state.last_side
            if prior_side == "above" and close <= boundary - hysteresis:
                side = "below"
            elif prior_side == "below" and close >= boundary + hysteresis:
                side = "above"
            else:
                side = prior_side
            eligible_crossing = side != prior_side and state.consecutive_fresh_count >= 1
            cooldown_ok = (
                state.last_notified_at is None
                or state.last_notified_at
                <= as_of - timedelta(minutes=policy.cooldown_minutes)
            )
            state.last_price_id = price.price_id
            state.last_valuation_fact_id = valuation.user_intrinsic_value_fact_id
            state.last_research_revision_id = research_revision_id
            state.last_threshold_ratio = policy.threshold_ratio
            state.last_hysteresis_ratio = policy.hysteresis_ratio
            state.last_side = side
            state.consecutive_fresh_count += 1
            if eligible_crossing and cooldown_ok:
                direction = "entered" if side == "below" else "left"
                _, was_created = produce_notification(
                    session,
                    user_id=user_id,
                    event_family="intrinsic_value_threshold_crossed",
                    subject_type="research_case",
                    subject_key=f"case:{case.id}:mos:{policy.threshold_ratio}:{direction}",
                    source_version=(
                        f"price-{price.price_id}:value-{valuation.user_intrinsic_value_fact_id}"
                    ),
                    title=f"{stock.ticker} {direction} your value threshold",
                    body=(
                        f"A fresh USD EOD close crossed your configured threshold after "
                        f"hysteresis. Reassess the thesis; this is not a buy or sell signal."
                    ),
                    evidence_route=f"/research/cases/{case.id}",
                    case_id=case.id,
                    stock_id=stock.id,
                    payload={
                        "price_id": price.price_id,
                        "price_date": price.price_date.isoformat() if price.price_date else None,
                        "threshold_ratio": str(policy.threshold_ratio),
                        "direction": direction,
                    },
                )
                if was_created:
                    state.last_notified_at = as_of
                    created += 1
            session.commit()
    return created


def _scheduled_digest_window(
    subscription: NotificationSubscription,
    *,
    as_of: datetime,
) -> tuple[datetime, str] | None:
    """Return the closed local-time window eligible for one digest run."""
    try:
        zone = ZoneInfo(subscription.timezone)
    except ZoneInfoNotFoundError:
        return None
    local_now = as_of.astimezone(zone)
    if subscription.frequency == "daily_digest":
        cutoff_date = local_now.date()
        eligible_at = datetime.combine(cutoff_date, time(8), zone)
        if local_now < eligible_at:
            return None
        cutoff = datetime.combine(cutoff_date, time.min, zone)
        period_key = (cutoff_date - timedelta(days=1)).isoformat()
    elif subscription.frequency == "weekly_digest":
        cutoff_date = local_now.date() - timedelta(days=local_now.weekday())
        eligible_at = datetime.combine(cutoff_date, time(8), zone)
        if local_now < eligible_at:
            return None
        cutoff = datetime.combine(cutoff_date, time.min, zone)
        period_key = (
            f"{(cutoff_date - timedelta(days=7)).isoformat()}_"
            f"{(cutoff_date - timedelta(days=1)).isoformat()}"
        )
    else:
        return None
    return cutoff.astimezone(timezone.utc), period_key


def materialize_scheduled_digests(
    session: Session,
    *,
    as_of: datetime,
) -> int:
    """Create one idempotent, catch-up digest per due external subscription.

    In-app source events remain immediate and immutable. A digest is a derived
    logical notification whose payload records the bounded source range; its
    delivery attempt is inserted in the same transaction so a scheduler crash
    cannot strand the digest without an outbox record.
    """
    subscriptions = (
        session.query(NotificationSubscription)
        .join(
            NotificationDestination,
            NotificationDestination.id == NotificationSubscription.destination_id,
        )
        .filter(
            NotificationSubscription.is_enabled.is_(True),
            NotificationSubscription.destination_id.isnot(None),
            NotificationSubscription.frequency.in_(["daily_digest", "weekly_digest"]),
            NotificationDestination.status == "enabled",
            NotificationDestination.user_id == NotificationSubscription.user_id,
        )
        .order_by(NotificationSubscription.id)
        .all()
    )
    created = 0
    for subscription in subscriptions:
        window = _scheduled_digest_window(subscription, as_of=as_of)
        if window is None:
            continue
        cutoff, period_key = window
        last_digest = (
            session.query(LogicalNotification)
            .filter(
                LogicalNotification.user_id == subscription.user_id,
                LogicalNotification.subject_type == "notification_digest",
                LogicalNotification.payload_json["subscription_id"].astext
                == str(subscription.id),
                LogicalNotification.payload_json["frequency"].astext
                == subscription.frequency,
            )
            .order_by(LogicalNotification.id.desc())
            .first()
        )
        last_source_id = int(
            (last_digest.payload_json or {}).get("source_max_notification_id", 0)
        ) if last_digest else 0
        lower_time = subscription.updated_at or subscription.created_at
        source_query = session.query(LogicalNotification).filter(
            LogicalNotification.user_id == subscription.user_id,
            LogicalNotification.event_family == subscription.event_family,
            LogicalNotification.subject_type != "notification_digest",
            LogicalNotification.id > last_source_id,
            LogicalNotification.created_at >= lower_time,
            LogicalNotification.created_at < cutoff,
        )
        source_count = source_query.count()
        if source_count == 0:
            continue
        source_max_id = source_query.with_entities(
            func.max(LogicalNotification.id)
        ).scalar()
        assert source_max_id is not None
        previews = (
            source_query.order_by(LogicalNotification.id)
            .limit(10)
            .all()
        )
        subject_key = (
            f"subscription:{subscription.id}:digest:"
            f"{subscription.frequency}:{period_key}"
        )
        logical_key = f"{subscription.event_family}:{subject_key}"
        source_version = f"through-notification-{source_max_id}"
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"notification-digest:{subscription.id}:{period_key}"},
        )
        existing = (
            session.query(LogicalNotification)
            .filter_by(
                user_id=subscription.user_id,
                logical_key=logical_key,
                source_version=source_version,
            )
            .one_or_none()
        )
        if existing is not None:
            session.rollback()
            continue
        preview_lines = [f"• {item.title}" for item in previews]
        if source_count > len(previews):
            preview_lines.append(f"• Plus {source_count - len(previews)} more updates")
        digest = LogicalNotification(
            user_id=subscription.user_id,
            event_family=subscription.event_family,
            subject_type="notification_digest",
            subject_key=subject_key,
            logical_key=logical_key,
            source_version=source_version,
            content_version=1,
            correction_type="original",
            title=f"{source_count} {subscription.event_family.replace('_', ' ')} updates",
            body="\n".join(preview_lines),
            evidence_route="/notifications",
            payload_json={
                "subscription_id": subscription.id,
                "frequency": subscription.frequency,
                "period_key": period_key,
                "source_notification_count": source_count,
                "source_max_notification_id": source_max_id,
            },
            severity="info",
        )
        session.add(digest)
        session.flush()
        session.add(
            NotificationInboxState(
                logical_notification_id=digest.id,
                user_id=subscription.user_id,
            )
        )
        last_success = (
            session.query(NotificationDeliveryAttempt)
            .join(
                LogicalNotification,
                LogicalNotification.id
                == NotificationDeliveryAttempt.logical_notification_id,
            )
            .filter(
                NotificationDeliveryAttempt.destination_id
                == subscription.destination_id,
                NotificationDeliveryAttempt.status == "succeeded",
                LogicalNotification.user_id == subscription.user_id,
                LogicalNotification.event_family == subscription.event_family,
            )
            .order_by(
                NotificationDeliveryAttempt.succeeded_at.desc().nullslast()
            )
            .first()
        )
        scheduled_for = max(
            as_of,
            (
                last_success.succeeded_at
                + timedelta(minutes=subscription.cooldown_minutes)
                if last_success and last_success.succeeded_at
                else as_of
            ),
        )
        attempt = NotificationDeliveryAttempt(
            logical_notification_id=digest.id,
            destination_id=subscription.destination_id,
            content_version=digest.content_version,
            status="queued",
            scheduled_for=scheduled_for,
            next_attempt_at=scheduled_for,
        )
        session.add(attempt)
        session.flush()
        session.add(
            NotificationDeliveryEvent(
                attempt_id=attempt.id,
                event_type="queued",
                payload_json={
                    "frequency": subscription.frequency,
                    "period_key": period_key,
                },
            )
        )
        session.commit()
        created += 1
    return created


class DeliveryAdapter(Protocol):
    def send(
        self,
        *,
        destination: NotificationDestination,
        notification: LogicalNotification,
        secret: str,
    ) -> tuple[bool, str]: ...


class SlackWebhookAdapter:
    def __init__(self, *, sender: Callable[[str, dict[str, Any]], tuple[bool, str]] | None = None):
        self.sender = sender or self._send_http

    @staticmethod
    def _send_http(url: str, payload: dict[str, Any]) -> tuple[bool, str]:
        try:
            with httpx.Client(follow_redirects=False, timeout=10.0) as client:
                response = client.post(url, json=payload)
            if 200 <= response.status_code < 300:
                return True, "accepted"
            if response.status_code == 429:
                return False, "transient_rate_limited"
            if response.status_code >= 500:
                return False, "transient_provider_failure"
            return False, "permanent_provider_rejection"
        except (httpx.TimeoutException, httpx.NetworkError):
            return False, "transient_network_failure"

    def send(
        self,
        *,
        destination: NotificationDestination,
        notification: LogicalNotification,
        secret: str,
    ) -> tuple[bool, str]:
        _validate_slack_webhook(secret)
        payload = {
            "text": notification.title,
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": notification.title}},
                {"type": "section", "text": {"type": "mrkdwn", "text": notification.body}},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"<{settings.BASE_URL}{notification.evidence_route}|Open evidence in ValuePilot>",
                    },
                },
            ],
        }
        return self.sender(secret, payload)


class EmailSMTPAdapter:
    def send(
        self,
        *,
        destination: NotificationDestination,
        notification: LogicalNotification,
        secret: str,
    ) -> tuple[bool, str]:
        if not settings.SMTP_HOST or not settings.SMTP_FROM or not settings.SMTP_TLS_REQUIRED:
            return False, "configuration_blocked"
        message = EmailMessage()
        message["Subject"] = notification.title
        message["From"] = settings.SMTP_FROM
        message["To"] = secret
        message.set_content(
            f"{notification.body}\n\nOpen evidence: {settings.BASE_URL}{notification.evidence_route}\n"
        )
        try:
            with smtplib.SMTP(
                settings.SMTP_HOST,
                settings.SMTP_PORT,
                timeout=settings.SMTP_TIMEOUT_SECONDS,
            ) as smtp:
                smtp.starttls()
                if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                smtp.send_message(message)
            return True, "accepted"
        except (OSError, smtplib.SMTPException):
            return False, "transient_provider_failure"


def deliver_pending_attempts(
    session: Session,
    *,
    now: datetime,
    adapters: dict[str, DeliveryAdapter] | None = None,
    limit: int = 50,
) -> dict[str, int]:
    if not settings.NOTIFICATION_DELIVERY_ENABLED:
        return {"attempted": 0, "succeeded": 0, "retry_scheduled": 0, "failed": 0}
    adapters = adapters or {"slack": SlackWebhookAdapter(), "email": EmailSMTPAdapter()}
    bounded_limit = min(max(limit, 1), 200)
    result = {"attempted": 0, "succeeded": 0, "retry_scheduled": 0, "failed": 0}

    # Slack webhooks and SMTP do not give us an idempotency key. A lease that
    # expired after a process crash therefore has an ambiguous external
    # outcome: automatic resend could duplicate a message. Surface it as a
    # visible permanent failure and require an explicit new test/event instead.
    expired_leases = (
        session.query(NotificationDeliveryAttempt)
        .filter(
            NotificationDeliveryAttempt.status == "leased",
            NotificationDeliveryAttempt.lease_expires_at < now,
            NotificationDeliveryAttempt.next_attempt_at <= now,
        )
        .order_by(NotificationDeliveryAttempt.next_attempt_at, NotificationDeliveryAttempt.id)
        .limit(bounded_limit)
        .with_for_update(skip_locked=True)
        .all()
    )
    for attempt in expired_leases:
        attempt.status = "permanent_failure"
        attempt.provider_response_class = "delivery_outcome_unknown"
        attempt.lease_expires_at = None
        session.add(
            NotificationDeliveryEvent(
                attempt_id=attempt.id,
                event_type="permanent_failure",
                response_class="delivery_outcome_unknown",
            )
        )
        result["failed"] += 1
    session.commit()

    remaining = bounded_limit - len(expired_leases)
    for _ in range(remaining):
        attempt = (
            session.query(NotificationDeliveryAttempt)
            .filter(
                NotificationDeliveryAttempt.status.in_(["queued", "retry_scheduled"]),
                NotificationDeliveryAttempt.next_attempt_at <= now,
            )
            .order_by(
                NotificationDeliveryAttempt.next_attempt_at,
                NotificationDeliveryAttempt.id,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
            .one_or_none()
        )
        if attempt is None:
            break
        destination = attempt.destination
        notification = attempt.notification
        subscription = (
            session.query(NotificationSubscription)
            .filter_by(
                user_id=notification.user_id,
                event_family=notification.event_family,
                destination_id=destination.id,
                is_enabled=True,
            )
            .one_or_none()
        )
        explicit_test = notification.event_family == "destination_test"
        if destination.status != "enabled" or (subscription is None and not explicit_test):
            attempt.status = "configuration_blocked"
            attempt.provider_response_class = "destination_disabled"
            session.add(
                NotificationDeliveryEvent(
                    attempt_id=attempt.id,
                    event_type="configuration_blocked",
                    response_class="destination_disabled",
                )
            )
            result["failed"] += 1
            session.commit()
            continue
        if not is_delivery_time_allowed(subscription, now):
            attempt.next_attempt_at = now + timedelta(minutes=30)
            session.commit()
            continue
        adapter = adapters.get(destination.channel)
        if adapter is None:
            attempt.status = "configuration_blocked"
            attempt.provider_response_class = "adapter_unconfigured"
            result["failed"] += 1
            session.commit()
            continue
        try:
            secret = _decrypt(destination)
        except NotificationError as error:
            destination.status = "configuration_blocked"
            destination.last_error_class = error.code
            attempt.status = "configuration_blocked"
            attempt.provider_response_class = error.code
            session.add(
                NotificationDeliveryEvent(
                    attempt_id=attempt.id,
                    event_type="configuration_blocked",
                    response_class=error.code,
                )
            )
            result["failed"] += 1
            session.commit()
            continue

        # Persist the lease before any external side effect. This prevents a
        # second worker from sending the same attempt while the first is in the
        # provider call.
        attempt.status = "leased"
        attempt.lease_expires_at = now + timedelta(minutes=2)
        attempt.last_attempt_at = now
        attempt.attempt_count += 1
        session.add(
            NotificationDeliveryEvent(attempt_id=attempt.id, event_type="attempted")
        )
        session.commit()

        try:
            success, response_class = adapter.send(
                destination=destination,
                notification=notification,
                secret=secret,
            )
        except Exception:
            # The adapter may have crossed the network boundary before raising;
            # retrying automatically would risk a duplicate external message.
            success = False
            response_class = "delivery_outcome_unknown"
        result["attempted"] += 1
        attempt = session.get(NotificationDeliveryAttempt, attempt.id)
        assert attempt is not None
        destination = attempt.destination
        attempt.provider_response_class = response_class
        attempt.lease_expires_at = None
        if success:
            attempt.status = "succeeded"
            attempt.succeeded_at = now
            result["succeeded"] += 1
            event_type = "succeeded"
        elif response_class.startswith("transient_") and attempt.attempt_count < MAX_DELIVERY_ATTEMPTS:
            attempt.status = "retry_scheduled"
            attempt.next_attempt_at = now + timedelta(minutes=2 ** attempt.attempt_count)
            result["retry_scheduled"] += 1
            event_type = "retry_scheduled"
        else:
            attempt.status = (
                "configuration_blocked"
                if response_class == "configuration_blocked"
                else "permanent_failure"
            )
            destination.last_error_class = response_class
            result["failed"] += 1
            event_type = attempt.status
        session.add(
            NotificationDeliveryEvent(
                attempt_id=attempt.id,
                event_type=event_type,
                response_class=response_class,
            )
        )
        session.commit()
    return result


def serialize_destination(row: NotificationDestination) -> dict[str, Any]:
    return {
        "id": row.id,
        "channel": row.channel,
        "label": row.label,
        "destination_hint": row.destination_hint,
        "status": row.status,
        "key_version": row.key_version if row.status != "revoked" else None,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "last_error_class": row.last_error_class,
        "created_at": row.created_at.isoformat(),
    }


def serialize_notification(
    row: LogicalNotification, state: NotificationInboxState
) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_family": row.event_family,
        "subject_type": row.subject_type,
        "source_version": row.source_version,
        "correction_type": row.correction_type,
        "supersedes_notification_id": row.supersedes_notification_id,
        "title": row.title,
        "body": row.body,
        "evidence_route": row.evidence_route,
        "severity": row.severity,
        "read_at": state.read_at.isoformat() if state.read_at else None,
        "dismissed_at": state.dismissed_at.isoformat() if state.dismissed_at else None,
        "created_at": row.created_at.isoformat(),
    }
