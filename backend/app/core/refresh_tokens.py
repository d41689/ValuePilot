"""Refresh-token store: issuance, rotation, revocation, reuse detection.

Refresh tokens are JWTs, but each one is also mirrored by a row in the
``refresh_tokens`` table (``app.models.auth_tokens.RefreshToken``). The JWT
signature + ``exp`` still establish authenticity and time-validity; the table
adds *revocability* — the JWT carries a ``jti`` that keys its row.

Rows sharing a ``family_id`` form one rotation lineage: login starts a family,
each ``/auth/refresh`` spends the presented token and appends a successor in the
same family. Presenting an already-spent token is a replay — the whole family
(the live successor included) is burned, so a stolen-then-rotated token is dead
and the legitimate holder is forced to re-authenticate.
"""

import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_refresh_token, decode_token
from app.models.auth_tokens import RefreshToken
from app.models.users import User


class RefreshTokenError(Exception):
    """A presented refresh token cannot be honoured.

    ``reuse_detected`` is True when the failure is a replay of an already-spent
    token (as opposed to an ordinary invalid/unknown one) — the caller has
    revoked the family and must persist that before responding.
    """

    def __init__(self, message: str, *, reuse_detected: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.reuse_detected = reuse_detected


def issue_refresh_token(db: Session, user: User, *, family_id: str | None = None) -> str:
    """Mint a refresh token, persist its row, and return the encoded JWT.

    Omitting ``family_id`` starts a fresh rotation lineage (login); passing an
    existing one continues that lineage (rotation). The row is added to the
    session but not committed — the caller owns the transaction.
    """
    jti = uuid.uuid4().hex
    family = family_id or uuid.uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user.id,
            family_id=family,
            expires_at=expires_at,
        )
    )
    return create_refresh_token(user.id, user.role, jti)


def revoke_family(db: Session, family_id: str, *, reason: str) -> int:
    """Revoke every still-live token in a rotation family. Returns the count.

    Already-revoked rows keep their original ``revoked_reason`` so the audit
    trail stays accurate.
    """
    result = db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc), revoked_reason=reason)
    )
    return result.rowcount or 0


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[User, str]:
    """Validate and rotate a presented refresh token.

    Returns ``(user, new_refresh_token)``. Raises :class:`RefreshTokenError` on
    any failure; on a reuse replay it first revokes the whole family (the caller
    must commit). The successor row is added to the session, not committed.
    """
    try:
        payload = decode_token(raw_token)
    except JWTError:
        raise RefreshTokenError("Invalid refresh token")

    if payload.get("type") != "refresh":
        raise RefreshTokenError("Token is not a refresh token")

    jti = payload.get("jti")
    if not jti:
        # No jti at all — e.g. a token minted before this feature shipped.
        raise RefreshTokenError("Invalid refresh token")

    # Lock the row for the rest of the transaction: two concurrent refreshes of
    # the same token must serialize, so the second sees the first's revocation
    # and is caught as reuse instead of both minting a successor.
    row = db.execute(
        select(RefreshToken).where(RefreshToken.jti == jti).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise RefreshTokenError("Invalid refresh token")

    if row.revoked_at is not None:
        # The token was already spent, logged out, or part of a burned family.
        # Presenting it again is a replay: burn the whole family so neither the
        # attacker's copy nor the legitimate holder's live token survives.
        revoke_family(db, row.family_id, reason="reuse_detected")
        raise RefreshTokenError("Refresh token reuse detected", reuse_detected=True)

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise RefreshTokenError("User not found or disabled")

    # Spend the presented token, then mint its successor in the same family.
    row.revoked_at = datetime.now(timezone.utc)
    row.revoked_reason = "rotated"
    new_token = issue_refresh_token(db, user, family_id=row.family_id)
    return user, new_token


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """Logout: revoke the presented token's whole family.

    Idempotent and silent on an invalid/unknown/expired token — logout must
    always succeed from the caller's point of view. The change is added to the
    session, not committed.
    """
    try:
        payload = decode_token(raw_token)
    except JWTError:
        return
    jti = payload.get("jti")
    if not jti:
        return
    row = db.execute(
        select(RefreshToken).where(RefreshToken.jti == jti)
    ).scalar_one_or_none()
    if row is None:
        return
    revoke_family(db, row.family_id, reason="logout")
