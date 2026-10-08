"""Escritura de la bitacora de administradores (docs/PLATAFORMA_COMPLETA.md §4.6)."""

from typing import Any

from sqlalchemy.orm import Session

from app.models import AdminAuditLog, User


def record(
    db: Session,
    admin: User,
    *,
    action: str,
    target_type: str,
    target_id: object,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    ip: str | None = None,
) -> None:
    """Agrega la fila a la sesion. NO hace commit: quien llama confirma el
    cambio y su fila juntos, asi que no existe uno sin la otra."""
    db.add(
        AdminAuditLog(
            admin_user_id=admin.id,
            admin_email=admin.email,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            before=before,
            after=after,
            reason=reason,
            ip=ip,
        )
    )
