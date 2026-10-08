"""Admin: usuarios, acceso manual y bitacora (docs/PLATAFORMA_COMPLETA.md §4.2 y §4.6).

Dos reglas:

- Toda accion que cambia el acceso o el estado de una cuenta pide un motivo y
  escribe su fila en `admin_audit_log` en la misma transaccion que el cambio.
- Aqui no se decide quien tiene acceso: se cambian los datos de la cuenta
  (`access_type`, `access_expires_at`, `is_active`) y la decision que se muestra
  es la de `core/access.has_access`.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import AdminUser, DbSession
from app.api.presenters import user_response
from app.api.v1.legal import client_ip, list_consents
from app.core import audit
from app.models import AdminAuditLog, GameSession, User
from app.schemas.admin import (
    AdminUserDetailResponse,
    AdminUserListResponse,
    AuditLogEntry,
    AuditLogListResponse,
    UpdateUserAccessRequest,
    UpdateUserStatusRequest,
)
from app.schemas.auth import AccessType, UserResponse, UserRole

router = APIRouter(prefix="/admin", tags=["admin"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]

ADMIN_ACCESS_MESSAGE = (
    "Un administrador siempre tiene acceso a la mesa por su rol: el acceso manual no le aplica"
)

# Cuantas filas de bitacora trae el detalle de una cuenta.
_DETAIL_AUDIT_ROWS = 20


def _get_or_404(db: DbSession, user_id: UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return user


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    db: DbSession,
    admin: AdminUser,
    query: Annotated[str | None, Query(max_length=255)] = None,
    access_type: AccessType | None = None,
    role: UserRole | None = None,
    email_verified: bool | None = None,
    is_active: bool | None = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminUserListResponse:
    """Cuentas por pagina, las mas recientes primero. Busca por correo o nombre."""
    filters = []
    text = (query or "").strip()
    if text:
        # Los comodines que escriba el admin se buscan literales.
        pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(
            or_(
                User.email.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
            )
        )
    if access_type is not None:
        filters.append(User.access_type == access_type.value)
    if role is not None:
        filters.append(User.role == role.value)
    if email_verified is not None:
        filters.append(User.email_verified.is_(email_verified))
    if is_active is not None:
        filters.append(User.is_active.is_(is_active))

    total = db.scalar(select(func.count()).select_from(User).where(*filters)) or 0
    users = db.scalars(
        select(User)
        .where(*filters)
        .order_by(User.created_at.desc(), User.id)
        .limit(limit)
        .offset(offset)
    )
    now = datetime.now(UTC)
    return AdminUserListResponse(
        items=[user_response(db, u, now) for u in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
def get_user(user_id: UUID, db: DbSession, admin: AdminUser) -> AdminUserDetailResponse:
    user = _get_or_404(db, user_id)
    sessions_count = (
        db.scalar(select(func.count()).select_from(GameSession).where(GameSession.user_id == user.id))
        or 0
    )
    rows = db.scalars(
        select(AdminAuditLog)
        .where(AdminAuditLog.target_type == "user", AdminAuditLog.target_id == str(user.id))
        .order_by(AdminAuditLog.created_at.desc())
        .limit(_DETAIL_AUDIT_ROWS)
    )
    return AdminUserDetailResponse(
        user=user_response(db, user),
        consents=list_consents(db, user.id),
        sessions_count=sessions_count,
        audit=[AuditLogEntry.model_validate(r) for r in rows],
    )


@router.patch("/users/{user_id}/access", response_model=UserResponse)
def update_user_access(
    user_id: UUID,
    payload: UpdateUserAccessRequest,
    db: DbSession,
    admin: AdminUser,
    request: Request,
) -> UserResponse:
    """Otorga acceso manual (`invited` con vencimiento opcional, o `full`) o lo
    retira (`none`)."""
    user = _get_or_404(db, user_id)
    # Un administrador entra por su rol (§2.2), no por el acceso manual: el
    # cambio se guardaria sin tener ningun efecto, y eso confunde a quien lo hace.
    if user.role == "admin":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ADMIN_ACCESS_MESSAGE)
    now = datetime.now(UTC)
    expires_at = payload.access_expires_at
    if expires_at is not None:
        if payload.access_type is not AccessType.invited:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="El vencimiento solo aplica al acceso invitado",
            )
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="El vencimiento debe ser una fecha futura",
            )

    before = {
        "access_type": user.access_type,
        "access_expires_at": _iso(user.access_expires_at),
    }
    user.access_type = payload.access_type.value
    user.access_expires_at = expires_at
    audit.record(
        db,
        admin,
        action="user.access.update",
        target_type="user",
        target_id=user.id,
        before=before,
        after={"access_type": user.access_type, "access_expires_at": _iso(expires_at)},
        reason=payload.reason.strip(),
        ip=client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return user_response(db, user)


@router.patch("/users/{user_id}/status", response_model=UserResponse)
def update_user_status(
    user_id: UUID,
    payload: UpdateUserStatusRequest,
    db: DbSession,
    admin: AdminUser,
    request: Request,
) -> UserResponse:
    """Suspende o reactiva una cuenta. Suspendida, entra a su cuenta pero no a la mesa."""
    user = _get_or_404(db, user_id)
    # Sin esto un administrador podria dejar la plataforma sin nadie que la opere.
    if user.id == admin.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No puedes suspender tu propia cuenta"
        )
    before = {"is_active": user.is_active}
    user.is_active = payload.is_active
    audit.record(
        db,
        admin,
        action="user.status.update",
        target_type="user",
        target_id=user.id,
        before=before,
        after={"is_active": user.is_active},
        reason=payload.reason.strip(),
        ip=client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return user_response(db, user)


@router.get("/audit-log", response_model=AuditLogListResponse)
def list_audit_log(
    db: DbSession, admin: AdminUser, limit: Limit = 50, offset: Offset = 0
) -> AuditLogListResponse:
    """La bitacora, lo mas reciente primero. Solo lectura: no hay como borrarla."""
    total = db.scalar(select(func.count()).select_from(AdminAuditLog)) or 0
    rows = db.scalars(
        select(AdminAuditLog)
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id)
        .limit(limit)
        .offset(offset)
    )
    return AuditLogListResponse(
        items=[AuditLogEntry.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
