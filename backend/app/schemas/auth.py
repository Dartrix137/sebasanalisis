"""
Schemas: Auth & Users
"""
from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AccessType(str, Enum):
    trial = "trial"
    invited = "invited"
    full = "full"


class UserRole(str, Enum):
    user = "user"
    admin = "admin"


# ---------- Requests ----------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: Optional[str] = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


# ---------- Responses ----------

class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    display_name: Optional[str] = None
    access_type: AccessType
    role: UserRole
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class UpdateUserAccessRequest(BaseModel):
    """PATCH /admin/users/:id/access — §3.4.

    Agregado en el paso 3: el endpoint estaba en el documento de arquitectura
    pero no tenia schema definido.
    """
    access_type: AccessType
