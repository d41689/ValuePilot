"""Database-bound authorization for narrow user-content tombstones."""

from __future__ import annotations

import hashlib
import hmac

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


_CAPABILITY_DOMAIN = b"valuepilot:privacy-erasure-db-capability:v1"
PRIVACY_ERASURE_KINDS = frozenset({"account_erasure", "revision_redaction"})


class PrivacyErasureBarrierError(ValueError):
    """The target user's permanent erasure barrier rejects new private work."""


def privacy_erasure_db_capability() -> str:
    """Derive a DB-only capability without sending the JWT signing key itself."""

    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        _CAPABILITY_DOMAIN,
        hashlib.sha256,
    ).hexdigest()


def begin_privacy_erasure_operation(
    session: Session,
    *,
    user_id: int,
    operation_kind: str,
) -> int:
    if operation_kind not in PRIVACY_ERASURE_KINDS:
        raise ValueError("unsupported privacy erasure operation")
    return int(
        session.scalar(
            text(
                "SELECT begin_privacy_erasure_operation("
                ":user_id,:operation_kind,:capability)"
            ),
            {
                "user_id": user_id,
                "operation_kind": operation_kind,
                "capability": privacy_erasure_db_capability(),
            },
        )
    )


def lock_user_privacy_write(session: Session, *, user_id: int) -> None:
    """Take the canonical first lock for a user-owned write.

    Database triggers remain the final boundary. Calling this before any child
    stock/case/fact lock also prevents lock-order inversion with account erase.
    """

    allowed = session.scalar(
        text("SELECT lock_user_privacy_write(:user_id)"), {"user_id": user_id}
    )
    if allowed is not True:
        raise PrivacyErasureBarrierError("Account is permanently erased.")
