"""
Schemas: administracion de usuarios y bitacora (§4.2 y §4.6 de la Fase 4)
"""
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import ConfigDict

from app.schemas.auth import AccessType, UserResponse, UserRole
from app.schemas.base import ApiModel, Reason
from app.schemas.billing import AdminPaymentResponse, SubscriptionResponse
from app.schemas.legal import ConsentResponse


class SubscriptionFilter(str, Enum):
    """Filtro de `GET /admin/users` por la suscripcion de la cuenta.

    No es `subscriptions.status` tal cual: lo que el administrador necesita
    saber es si el periodo pagado sigue vigente, y eso depende de la fecha.
    """
    #: Con un periodo pagado que todavia no vence.
    in_force = "in_force"
    #: Pago alguna vez y el periodo ya vencio.
    lapsed = "lapsed"
    #: Abrio un pago y nunca lo completo.
    pending = "pending"
    #: Nunca abrio un pago.
    none = "none"


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


class UpdateUserRoleRequest(ApiModel):
    """PATCH /admin/users/:id/role: nombra un administrador o le quita el rol."""
    role: UserRole
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

    La suscripcion y los pagos son de solo lectura: las acciones sobre ellos
    llegan con el paso 6 (§4.3).
    """
    user: UserResponse
    # La que tiene un periodo pagado, vigente o no. Null si nunca pago.
    subscription: SubscriptionResponse | None = None
    # Los ultimos intentos de cobro, incluidos los que no se completaron.
    payments: list[AdminPaymentResponse]
    consents: list[ConsentResponse]
    sessions_count: int
    # Lo que los administradores han hecho sobre esta cuenta, lo mas reciente primero.
    audit: list[AuditLogEntry]
