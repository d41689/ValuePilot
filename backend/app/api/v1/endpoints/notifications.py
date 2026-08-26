from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func

from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.core.config import settings
from app.models.institutions import InstitutionManager, JobRun
from app.models.notifications import (
    LogicalNotification,
    NotificationDeliveryAttempt,
    NotificationDeliveryEvent,
    NotificationDestination,
    NotificationInboxState,
    NotificationSubscription,
)
from app.schemas.notifications import (
    DestinationTestInput,
    EmailDestinationInput,
    EmailVerificationInput,
    SlackDestinationInput,
    SubscriptionInput,
)
from app.services.api_rate_limits import RateLimitExceeded, consume_user_operation
from app.services.research_notifications import (
    NotificationError,
    create_email_destination,
    create_or_update_slack_destination,
    deliver_pending_attempts,
    follow_manager,
    list_follows,
    produce_notification,
    revoke_destination,
    serialize_destination,
    serialize_notification,
    unfollow_manager,
    upsert_subscription,
    verify_email_destination,
)


router = APIRouter()


def _raise(session: SessionDep, error: NotificationError) -> None:
    session.rollback()
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    ) from error


def _consume_rate_limit(session: SessionDep, *, user_id: int, operation: str) -> None:
    try:
        consume_user_operation(
            session,
            user_id=user_id,
            operation=operation,
        )
    except RateLimitExceeded as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limit_exceeded",
                "operation": error.operation,
                "message": "Too many attempts. Try again later.",
            },
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error


@router.post("/manager-follows/{manager_id}", response_model=dict)
def create_manager_follow(
    manager_id: int,
    response: Response,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        row, created = follow_manager(
            session, user_id=current_user.id, manager_id=manager_id
        )
    except NotificationError as error:
        _raise(session, error)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return {"created": created, "follow": {"id": row.id, "manager_id": row.manager_id}}


@router.get("/manager-follows", response_model=dict)
def get_manager_follows(
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    rows = list_follows(session, user_id=current_user.id)
    managers = {
        manager.id: manager
        for manager in session.query(InstitutionManager)
        .filter(InstitutionManager.id.in_([row.manager_id for row in rows] or [-1]))
        .all()
    }
    return {
        "items": [
            {
                "id": row.id,
                "manager_id": row.manager_id,
                "manager_name": (
                    managers[row.manager_id].display_name
                    or managers[row.manager_id].canonical_name
                ),
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.delete("/manager-follows/{follow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_manager_follow(
    follow_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> Response:
    try:
        unfollow_manager(session, user_id=current_user.id, follow_id=follow_id)
    except NotificationError as error:
        _raise(session, error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/destinations", response_model=dict)
def list_destinations(
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    rows = (
        session.query(NotificationDestination)
        .filter(NotificationDestination.user_id == current_user.id)
        .order_by(NotificationDestination.created_at, NotificationDestination.id)
        .all()
    )
    return {"items": [serialize_destination(row) for row in rows]}


@router.post("/destinations/slack", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_slack_destination(
    payload: SlackDestinationInput,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        row, created = create_or_update_slack_destination(
            session,
            user_id=current_user.id,
            label=payload.label,
            webhook_url=payload.webhook_url,
            consent=payload.consent,
        )
    except NotificationError as error:
        _raise(session, error)
    return {"created": created, "destination": serialize_destination(row)}


@router.post("/destinations/email", response_model=dict, status_code=status.HTTP_202_ACCEPTED)
def create_verified_email_destination(
    payload: EmailDestinationInput,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        row, _token = create_email_destination(
            session,
            user_id=current_user.id,
            label=payload.label,
            email=str(payload.email),
            consent=payload.consent,
        )
    except NotificationError as error:
        _raise(session, error)
    return {"destination": serialize_destination(row), "verification_sent": True}


@router.post("/destinations/{destination_id}/verify-email", response_model=dict)
def verify_email(
    destination_id: int,
    payload: EmailVerificationInput,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    _consume_rate_limit(
        session,
        user_id=current_user.id,
        operation="destination_verification",
    )
    try:
        row = verify_email_destination(
            session,
            user_id=current_user.id,
            destination_id=destination_id,
            token=payload.token,
        )
    except NotificationError as error:
        _raise(session, error)
    return {"destination": serialize_destination(row)}


@router.delete("/destinations/{destination_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_destination(
    destination_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> Response:
    try:
        revoke_destination(
            session, user_id=current_user.id, destination_id=destination_id
        )
    except NotificationError as error:
        _raise(session, error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/destinations/{destination_id}/test", response_model=dict)
def test_destination(
    destination_id: int,
    payload: DestinationTestInput,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    destination = (
        session.query(NotificationDestination)
        .filter(
            NotificationDestination.id == destination_id,
            NotificationDestination.user_id == current_user.id,
            NotificationDestination.status == "enabled",
        )
        .one_or_none()
    )
    if destination is None:
        raise HTTPException(status_code=404, detail="Destination not found.")
    _consume_rate_limit(
        session,
        user_id=current_user.id,
        operation="destination_delivery_test",
    )
    latest_test = (
        session.query(NotificationDeliveryAttempt)
        .join(
            LogicalNotification,
            LogicalNotification.id == NotificationDeliveryAttempt.logical_notification_id,
        )
        .filter(
            NotificationDeliveryAttempt.destination_id == destination.id,
            LogicalNotification.event_family == "destination_test",
        )
        .order_by(NotificationDeliveryAttempt.created_at.desc())
        .first()
    )
    now = datetime.now(timezone.utc)
    if latest_test and latest_test.created_at > now - timedelta(minutes=1):
        raise HTTPException(status_code=429, detail="Wait one minute before another test.")
    notification, _ = produce_notification(
        session,
        user_id=current_user.id,
        event_family="destination_test",
        subject_type="destination",
        subject_key=f"destination:{destination.id}:test:{now.strftime('%Y%m%d%H%M')}",
        source_version=now.isoformat(),
        title="ValuePilot destination test",
        body="This explicitly requested test confirms that your notification destination works.",
        evidence_route="/notifications",
    )
    attempt = NotificationDeliveryAttempt(
        logical_notification_id=notification.id,
        destination_id=destination.id,
        content_version=notification.content_version,
        status="queued",
        scheduled_for=now,
        next_attempt_at=now,
    )
    session.add(attempt)
    session.flush()
    session.add(NotificationDeliveryEvent(attempt_id=attempt.id, event_type="queued"))
    session.commit()
    result = deliver_pending_attempts(session, now=now)
    return {"queued": True, "delivery": result}


@router.get("/subscriptions", response_model=dict)
def list_subscriptions(
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    rows = (
        session.query(NotificationSubscription)
        .filter(NotificationSubscription.user_id == current_user.id)
        .order_by(NotificationSubscription.event_family, NotificationSubscription.id)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "event_family": row.event_family,
                "destination_id": row.destination_id,
                "frequency": row.frequency,
                "timezone": row.timezone,
                "quiet_start_local": row.quiet_start_local,
                "quiet_end_local": row.quiet_end_local,
                "cooldown_minutes": row.cooldown_minutes,
                "threshold_ratio": (
                    str(row.threshold_ratio) if row.threshold_ratio is not None else None
                ),
                "hysteresis_ratio": str(row.hysteresis_ratio),
                "is_enabled": row.is_enabled,
            }
            for row in rows
        ]
    }


@router.put("/subscriptions", response_model=dict)
def set_subscription(
    payload: SubscriptionInput,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        row = upsert_subscription(
            session,
            user_id=current_user.id,
            event_family=payload.event_family,
            destination_id=payload.destination_id,
            frequency=payload.frequency,
            timezone_name=payload.timezone,
            quiet_start_local=payload.quiet_start_local,
            quiet_end_local=payload.quiet_end_local,
            cooldown_minutes=payload.cooldown_minutes,
            threshold_ratio=payload.threshold_ratio,
            hysteresis_ratio=payload.hysteresis_ratio,
            is_enabled=payload.is_enabled,
        )
    except NotificationError as error:
        _raise(session, error)
    return {"subscription_id": row.id}


@router.get("/delivery-attempts", response_model=dict)
def list_delivery_attempts(
    session: SessionDep,
    current_user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    query = (
        session.query(
            NotificationDeliveryAttempt,
            LogicalNotification,
            NotificationDestination,
        )
        .join(
            LogicalNotification,
            LogicalNotification.id
            == NotificationDeliveryAttempt.logical_notification_id,
        )
        .join(
            NotificationDestination,
            NotificationDestination.id == NotificationDeliveryAttempt.destination_id,
        )
        .filter(
            LogicalNotification.user_id == current_user.id,
            NotificationDestination.user_id == current_user.id,
        )
    )
    total = query.count()
    rows = (
        query.order_by(
            NotificationDeliveryAttempt.created_at.desc(),
            NotificationDeliveryAttempt.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": attempt.id,
                "notification_id": notification.id,
                "notification_title": notification.title,
                "evidence_route": notification.evidence_route,
                "event_family": notification.event_family,
                "destination_label": destination.label,
                "destination_hint": destination.destination_hint,
                "channel": destination.channel,
                "status": attempt.status,
                "attempt_count": attempt.attempt_count,
                "provider_response_class": attempt.provider_response_class,
                "scheduled_for": attempt.scheduled_for.isoformat(),
                "last_attempt_at": (
                    attempt.last_attempt_at.isoformat()
                    if attempt.last_attempt_at
                    else None
                ),
                "succeeded_at": (
                    attempt.succeeded_at.isoformat() if attempt.succeeded_at else None
                ),
                "created_at": attempt.created_at.isoformat(),
            }
            for attempt, notification, destination in rows
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/admin/operations", response_model=dict)
def notification_operations(
    session: SessionDep,
    current_user: AdminUser,
) -> dict[str, Any]:
    backlog_statuses = ["queued", "leased", "retry_scheduled"]
    backlog = {
        row.status: int(row.count)
        for row in session.query(
            NotificationDeliveryAttempt.status.label("status"),
            func.count(NotificationDeliveryAttempt.id).label("count"),
        )
        .filter(NotificationDeliveryAttempt.status.in_(backlog_statuses))
        .group_by(NotificationDeliveryAttempt.status)
        .all()
    }
    for item_status in backlog_statuses:
        backlog.setdefault(item_status, 0)
    oldest_pending_at = session.query(
        func.min(NotificationDeliveryAttempt.created_at)
    ).filter(NotificationDeliveryAttempt.status.in_(backlog_statuses)).scalar()
    last_success_at = session.query(
        func.max(NotificationDeliveryAttempt.succeeded_at)
    ).filter(NotificationDeliveryAttempt.status == "succeeded").scalar()
    failures_by_class = {
        row.response_class: int(row.count)
        for row in session.query(
            NotificationDeliveryAttempt.provider_response_class.label(
                "response_class"
            ),
            func.count(NotificationDeliveryAttempt.id).label("count"),
        )
        .filter(
            NotificationDeliveryAttempt.provider_response_class.isnot(None),
            NotificationDeliveryAttempt.status != "succeeded",
        )
        .group_by(NotificationDeliveryAttempt.provider_response_class)
        .all()
    }
    destinations_by_status = {
        row.status: int(row.count)
        for row in session.query(
            NotificationDestination.status.label("status"),
            func.count(NotificationDestination.id).label("count"),
        )
        .group_by(NotificationDestination.status)
        .all()
    }
    latest_rotation = (
        session.query(JobRun)
        .filter(JobRun.job_type == "notification_secret_rotation")
        .order_by(JobRun.created_at.desc(), JobRun.id.desc())
        .first()
    )
    return {
        "configuration_readiness": {
            "scheduler_enabled": settings.RESEARCH_NOTIFICATION_SCHEDULER_ENABLED,
            "delivery_enabled": settings.NOTIFICATION_DELIVERY_ENABLED,
            "encryption_configured": bool(settings.NOTIFICATION_SECRET_KEYS),
            "email_transport_configured": bool(
                settings.SMTP_HOST
                and settings.SMTP_FROM
                and settings.SMTP_TLS_REQUIRED
            ),
        },
        "backlog": backlog,
        "oldest_pending_at": (
            oldest_pending_at.isoformat() if oldest_pending_at else None
        ),
        "last_success_at": last_success_at.isoformat() if last_success_at else None,
        "failures_by_class": failures_by_class,
        "destinations_by_status": destinations_by_status,
        "latest_secret_rotation": (
            {
                "job_id": latest_rotation.id,
                "status": latest_rotation.status,
                "created_at": latest_rotation.created_at.isoformat(),
                "finished_at": (
                    latest_rotation.finished_at.isoformat()
                    if latest_rotation.finished_at
                    else None
                ),
                "summary": latest_rotation.summary_json,
                "error_class": latest_rotation.error_message,
            }
            if latest_rotation
            else None
        ),
    }


@router.get("/inbox", response_model=dict)
def notification_inbox(
    session: SessionDep,
    current_user: CurrentUser,
    include_dismissed: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    query = (
        session.query(LogicalNotification, NotificationInboxState)
        .join(
            NotificationInboxState,
            NotificationInboxState.logical_notification_id == LogicalNotification.id,
        )
        .filter(
            LogicalNotification.user_id == current_user.id,
            NotificationInboxState.user_id == current_user.id,
        )
    )
    if not include_dismissed:
        query = query.filter(NotificationInboxState.dismissed_at.is_(None))
    total = query.count()
    rows = (
        query.order_by(LogicalNotification.created_at.desc(), LogicalNotification.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_notification(notification, inbox_state) for notification, inbox_state in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def _owned_inbox_state(
    session: SessionDep, *, user_id: int, notification_id: int
) -> NotificationInboxState:
    row = (
        session.query(NotificationInboxState)
        .join(
            LogicalNotification,
            LogicalNotification.id == NotificationInboxState.logical_notification_id,
        )
        .filter(
            NotificationInboxState.logical_notification_id == notification_id,
            NotificationInboxState.user_id == user_id,
            LogicalNotification.user_id == user_id,
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return row


@router.post("/inbox/{notification_id}/read", response_model=dict)
def mark_notification_read(
    notification_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    row = _owned_inbox_state(session, user_id=current_user.id, notification_id=notification_id)
    row.read_at = row.read_at or datetime.now(timezone.utc)
    session.commit()
    return {"read_at": row.read_at.isoformat()}


@router.post("/inbox/{notification_id}/dismiss", response_model=dict)
def dismiss_notification(
    notification_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    row = _owned_inbox_state(session, user_id=current_user.id, notification_id=notification_id)
    row.dismissed_at = row.dismissed_at or datetime.now(timezone.utc)
    session.commit()
    return {"dismissed_at": row.dismissed_at.isoformat()}
