"""
Schemas: administracion de usuarios y bitacora (§4.2 y §4.6 de la Fase 4)
"""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.auth import AccessType, UserResponse
from app.schemas.base import ApiModel
from app.schemas.legal import ConsentResponse

# Toda accion de acceso lleva su motivo: es lo que se lee en la bitacora.
Reason = Field(min_length=3, max_length=500)


class AdminUserListResponse(ApiModel):
    items: list[UserResponse]
    # Cuantas cuentas cumplen el filtro, no cuantas vienen en esta pagina.
    total: int
    limit: int
    offset: int


class UpdateUserAccessRequest(ApiModel):
    """PATCH /admin/users/:id/access: otorga o retira el acceso manual."""
    access_type: AccessType
    # Solo con `invited`. Null = sin vencimiento.
    access_expires_at: datetime | None = None
    reason: str = Reason


class UpdateUserStatusRequest(ApiModel):
    """PATCH /admin/users/:id/status: suspende o reactiva la cuenta."""
    is_active: bool
    reason: str = Reason


class AuditLogEntry(ApiModel):
    id: UUID
    admin_user_id: UUID | None = None
    admin_email: str
    action: str
    target_type: str
    target_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    ip: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(ApiModel):
    items: list[AuditLogEntry]
    total: int
    limit: int
    offset: int


class AdminUserDetailResponse(ApiModel):
    """Una cuenta vista por el administrador (§4.2).

    La suscripcion y el historial de pagos se suman en el paso 5.
    """
    user: UserResponse
    consents: list[ConsentResponse]
    sessions_count: int
    # Lo que los administradores han hecho sobre esta cuenta, lo mas reciente primero.
    audit: list[AuditLogEntry]
