from typing import Any
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from app.api.deps import SessionDep
from app.models.users import User

router = APIRouter()

@router.post("/", response_model=dict)
def create_user(
    *,
    session: SessionDep,
    email: str,
) -> Any:
    """
    Create new user.
    """
    user = session.scalar(select(User).where(User.email == email))
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    user = User(email=email)
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"id": user.id, "email": user.email, "created_at": user.created_at}

@router.get("/", response_model=list[dict])
def read_users(
    session: SessionDep,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Retrieve users.
    """
    stmt = select(User).offset(skip).limit(limit)
    users = session.scalars(stmt).all()
    return [{"id": u.id, "email": u.email, "created_at": u.created_at} for u in users]
