from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import SessionDep, AdminUser, CurrentUser
from app.core.security import hash_password
from app.models.users import User
from app.schemas.users import AccountErasureRequest, UserCreate, UserRead
from app.services.account_erasure import AccountErasureError, erase_account

router = APIRouter()


@router.post("/me/erase", response_model=dict)
def erase_current_user(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: AccountErasureRequest,
) -> dict:
    try:
        return erase_account(
            session,
            user=current_user,
            password=body.password,
        )
    except AccountErasureError as error:
        session.rollback()
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    *,
    session: SessionDep,
    current_user: AdminUser,
    body: UserCreate,
) -> Any:
    existing = session.scalar(select(User).where(User.email == body.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/", response_model=list[UserRead])
def read_users(
    *,
    session: SessionDep,
    current_user: AdminUser,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    stmt = select(User).offset(skip).limit(limit)
    return list(session.scalars(stmt).all())
