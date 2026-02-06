from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import SessionDep, AdminUser
from app.models.users import User
from app.schemas.users import UserRead, UserUpdate

router = APIRouter()


@router.get("/users", response_model=list[UserRead])
def list_users(
    *,
    session: SessionDep,
    current_user: AdminUser,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    stmt = select(User).offset(skip).limit(limit)
    return list(session.scalars(stmt).all())


@router.patch("/users/{user_id}", response_model=UserRead)
def patch_user(
    *,
    session: SessionDep,
    current_user: AdminUser,
    user_id: int,
    payload: UserUpdate,
) -> Any:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    changed = False
    if payload.role is not None and payload.role != user.role:
        user.role = payload.role
        changed = True
    if payload.tier is not None and payload.tier != user.tier:
        user.tier = payload.tier
        changed = True
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        changed = True

    if changed:
        session.add(user)
        session.commit()
        session.refresh(user)

    return user


@router.delete("/users/{user_id}", response_model=dict)
def disable_user(
    *,
    session: SessionDep,
    current_user: AdminUser,
    user_id: int,
) -> Any:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot disable current admin user")

    user.is_active = False
    session.add(user)
    session.commit()
    return {"status": "disabled", "user_id": user.id}
