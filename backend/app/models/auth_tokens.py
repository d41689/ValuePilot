"""Server-side refresh-token store.

Each issued refresh token gets one row here so it can be revoked and so a
replayed (already-rotated) token can be detected. Rows sharing a ``family_id``
form one rotation lineage: login starts a family, every ``/auth/refresh``
appends the next link, and reuse of any spent link burns the whole family.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The JWT `jti` claim of this refresh token — the lookup key.
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    # Shared by every token descended from one login; the unit of revocation.
    family_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # NULL while the token is live; set when it is rotated, logged out, or
    # invalidated by reuse detection.
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Why the token was revoked: 'rotated' | 'logout' | 'reuse_detected'.
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
