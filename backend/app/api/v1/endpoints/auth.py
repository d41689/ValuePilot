"""Authentication endpoints: register, login, refresh, logout, me."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import SessionDep, CurrentUser
from app.core.refresh_tokens import (
    RefreshTokenError,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.users import User
from app.schemas.users import (
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserMe,
    UserRead,
)

router = APIRouter()


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, db: SessionDep):
    existing = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: UserLogin, db: SessionDep):
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    # Start a fresh rotation family for this session.
    refresh_token = issue_refresh_token(db, user)
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: SessionDep):
    try:
        user, refresh_token = rotate_refresh_token(db, body.refresh_token)
    except RefreshTokenError as exc:
        # A reuse replay revokes the token family inside rotate_refresh_token;
        # commit so that revocation persists. A no-op for an ordinary bad token.
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=refresh_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, db: SessionDep):
    """Revoke the presented refresh token's whole rotation family.

    Idempotent, and deliberately requires no access token: the refresh token is
    itself the proof of session ownership, and an expired access token must not
    be able to block a sign-out.
    """
    revoke_refresh_token(db, body.refresh_token)
    db.commit()


@router.get("/me", response_model=UserMe)
def me(current_user: CurrentUser):
    return current_user
