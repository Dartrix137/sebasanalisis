"""
Schemas: Auth & Users
"""
from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, ConfigDict, EmailStr, Field
from pydantic_core import PydanticCustomError

from app.core.password_policy import PasswordPolicyError, validate_password
from app.schemas.base import ApiModel
from app.schemas.bets import BetResponse
from app.schemas.legal import ConsentResponse
from app.schemas.sessions import SessionResponse
from app.schemas.spins import SpinResponse


class AccessType(str, Enum):
    trial = "trial"
    invited = "invited"
    full = "full"


class UserRole(str, Enum):
    user = "user"
    admin = "admin"


def _check_password_policy(value: str) -> str:
    try:
        validate_password(value)
    except PasswordPolicyError as exc:
        # Error propio para que el mensaje llegue al usuario tal cual, sin el
        # prefijo "Value error" que Pydantic le pone a un ValueError.
        raise PydanticCustomError("password_policy", str(exc)) from exc  # type: ignore[arg-type]
    return value


# Toda contrasena NUEVA pasa por la politica (§5.3 de la Fase 4). La de login no:
# una cuenta anterior a la politica tiene que poder seguir entrando.
NewPassword = Annotated[str, AfterValidator(_check_password_policy)]


# ---------- Requests ----------

class RegisterRequest(ApiModel):
    email: EmailStr
    password: NewPassword
    display_name: str | None = Field(default=None, max_length=100)
    # Consentimientos del registro (§6.3 de la Fase 4). Los ids son los de las
    # versiones que el formulario mostro (`GET /legal/required`): la aceptacion
    # queda atada al texto exacto que la persona tuvo delante. Tienen valor por
    # defecto para que, si faltan, responda el endpoint con un mensaje claro.
    accepted_document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    adult_confirmed: bool = False


class LoginRequest(ApiModel):
    email: EmailStr
    password: str


class RefreshRequest(ApiModel):
    refresh_token: str


class TokenRequest(ApiModel):
    """El token de un solo uso que llego en el enlace del correo."""
    token: str = Field(min_length=1, max_length=200)


class ForgotPasswordRequest(ApiModel):
    email: EmailStr


class ResetPasswordRequest(ApiModel):
    token: str = Field(min_length=1, max_length=200)
    new_password: NewPassword


class ChangePasswordRequest(ApiModel):
    current_password: str
    new_password: NewPassword


class UpdateProfileRequest(ApiModel):
    display_name: str | None = Field(max_length=100)


class ChangeEmailRequest(ApiModel):
    new_email: EmailStr
    # Se pide la contrasena: quien encuentra una sesion abierta no puede
    # llevarse la cuenta cambiandole el correo.
    password: str


class DeleteAccountRequest(ApiModel):
    # Eliminar la cuenta no se puede deshacer: se confirma con la contrasena.
    password: str


# ---------- Responses ----------

class UserResponse(ApiModel):
    id: UUID
    email: EmailStr
    display_name: str | None = None
    email_verified: bool
    access_type: AccessType
    role: UserRole
    created_at: datetime
    adult_confirmed_at: datetime | None = None
    # Null hasta que lee la pantalla de bienvenida de la mesa (§6.3).
    onboarding_completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(ApiModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class MessageResponse(ApiModel):
    """Respuesta de las acciones que no devuelven un recurso."""
    message: str


class ExportSession(ApiModel):
    """Una mesa con todo lo que el usuario registro en ella."""
    session: SessionResponse
    spins: list[SpinResponse]
    bets: list[BetResponse]


class ExportResponse(ApiModel):
    """GET /auth/me/export: los datos de la cuenta (§6.4 de la Fase 4)."""
    exported_at: datetime
    account: UserResponse
    sessions: list[ExportSession]
    consents: list[ConsentResponse]
    # Vacio hasta el paso 5: todavia no hay cobros.
    payments: list[dict[str, str]]


class UpdateUserAccessRequest(ApiModel):
    """PATCH /admin/users/:id/access — §3.4.

    Agregado en el paso 3: el endpoint estaba en el documento de arquitectura
    pero no tenia schema definido.
    """
    access_type: AccessType
