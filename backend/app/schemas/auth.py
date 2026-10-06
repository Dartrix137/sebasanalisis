"""
Schemas: Auth & Users
"""
from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Optional
from pydantic import ConfigDict, EmailStr, Field
from app.schemas.base import ApiModel


class AccessType(str, Enum):
    trial = "trial"
    invited = "invited"
    full = "full"


class UserRole(str, Enum):
    user = "user"
    admin = "admin"


# ---------- Requests ----------

class RegisterRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: Optional[str] = Field(default=None, max_length=100)


class LoginRequest(ApiModel):
    email: EmailStr
    password: str


class RefreshRequest(ApiModel):
    refresh_token: str


# ---------- Responses ----------

class UserResponse(ApiModel):
    id: UUID
    email: EmailStr
    display_name: Optional[str] = None
    access_type: AccessType
    role: UserRole
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(ApiModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class UpdateUserAccessRequest(ApiModel):
    """PATCH /admin/users/:id/access — §3.4.

    Agregado en el paso 3: el endpoint estaba en el documento de arquitectura
    pero no tenia schema definido.
    """
    access_type: AccessType
