"""Password hashing and JWT token utilities."""

from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
from jose import jwt

from app.core.config import settings

# --------------- Password hashing (bcrypt) ---------------


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(
        plain.encode("utf-8"), _bcrypt.gensalt(rounds=12)
    ).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# --------------- JWT tokens ---------------


def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "role": role, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int, role: str, jti: str) -> str:
    """Encode a refresh token. ``jti`` is the token's unique id; it ties the
    JWT to its row in the ``refresh_tokens`` store for revocation / reuse
    detection (see app.core.refresh_tokens)."""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "type": "refresh",
        "jti": jti,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises jose.JWTError on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
