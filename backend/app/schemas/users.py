from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ---------- Enums (as constrained literals) ----------

ROLE_VALUES = ("admin", "user")
TIER_VALUES = ("free", "premium")


# ---------- Request schemas ----------

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """Fields an admin can patch on any user."""
    role: Optional[str] = Field(None, pattern=f"^({'|'.join(ROLE_VALUES)})$")
    tier: Optional[str] = Field(None, pattern=f"^({'|'.join(TIER_VALUES)})$")
    is_active: Optional[bool] = None


# ---------- Response schemas ----------

class UserRead(BaseModel):
    id: int
    email: str
    role: str
    tier: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserMe(UserRead):
    """Extended response for /auth/me – same fields for now, easy to extend."""
    pass


# ---------- Auth token schemas ----------

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: int  # user id
    role: str
    exp: Optional[datetime] = None
