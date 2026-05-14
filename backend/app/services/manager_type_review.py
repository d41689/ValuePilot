"""MVP5-05 manager_type review service.

Single public entry point ``update_manager_type`` plus a read helper
``list_manager_type_review_events``. The admin editor in
``thirteenf_admin.py`` calls ``update_manager_type``; the audit-trail
read endpoint calls the list helper. Writing the audit row and the
column update happen in one session-scoped block so the audit log
can't drift from the actual column value.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.institutions import (
    MANAGER_TYPES,
    InstitutionManager,
    InstitutionManagerTypeReviewEvent,
)


class ManagerTypeUpdateError(ValueError):
    """Typed error so the endpoint can translate to a 400 / 404
    without parsing a generic ValueError message."""


def update_manager_type(
    session: Session,
    manager_id: int,
    *,
    new_manager_type: str,
    reviewer_user_id: int | None,
    note: str | None = None,
    evidence_json: dict | None = None,
) -> dict[str, Any]:
    """Apply an admin classification.

    Returns a dict shaped like::

        {
            "manager_id": int,
            "old_manager_type": str | None,
            "new_manager_type": str,
            "changed": bool,
            "audit_event_id": int | None,
        }

    ``changed=False`` and ``audit_event_id=None`` when the new value
    matches the existing value — the editor's save action is a no-op
    in that case and writes no audit row. The endpoint returns
    success regardless so the UI can close the dialog without
    distinguishing the two paths.
    """
    if new_manager_type not in MANAGER_TYPES:
        allowed = ", ".join(sorted(MANAGER_TYPES))
        raise ManagerTypeUpdateError(
            f"new_manager_type must be one of: {allowed}"
        )

    manager = session.get(InstitutionManager, manager_id)
    if manager is None:
        raise ManagerTypeUpdateError(f"manager not found: {manager_id}")

    old_manager_type = manager.manager_type
    if old_manager_type == new_manager_type:
        return {
            "manager_id": manager_id,
            "old_manager_type": old_manager_type,
            "new_manager_type": new_manager_type,
            "changed": False,
            "audit_event_id": None,
        }

    manager.manager_type = new_manager_type
    event = InstitutionManagerTypeReviewEvent(
        manager_id=manager_id,
        old_manager_type=old_manager_type,
        new_manager_type=new_manager_type,
        reviewed_by_user_id=reviewer_user_id,
        note=note,
        evidence_json=evidence_json,
    )
    session.add(event)
    session.flush()
    session.commit()

    return {
        "manager_id": manager_id,
        "old_manager_type": old_manager_type,
        "new_manager_type": new_manager_type,
        "changed": True,
        "audit_event_id": event.id,
    }


def list_manager_type_review_events(
    session: Session, manager_id: int, *, limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the most recent ``limit`` audit events for a manager."""
    rows = (
        session.query(InstitutionManagerTypeReviewEvent)
        .filter(InstitutionManagerTypeReviewEvent.manager_id == manager_id)
        # Tie-break by id so events from the same transaction
        # (identical ``created_at`` from ``server_default=func.now()``)
        # still come back newest-first deterministically.
        .order_by(
            InstitutionManagerTypeReviewEvent.created_at.desc(),
            InstitutionManagerTypeReviewEvent.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "manager_id": row.manager_id,
            "old_manager_type": row.old_manager_type,
            "new_manager_type": row.new_manager_type,
            "reviewed_by_user_id": row.reviewed_by_user_id,
            "note": row.note,
            "evidence_json": row.evidence_json,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
