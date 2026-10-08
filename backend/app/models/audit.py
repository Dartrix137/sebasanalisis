"""Bitacora de acciones de administradores (docs/PLATAFORMA_COMPLETA.md §4.6).

Se escribe con `core/audit.record`, en la misma transaccion que el cambio que
describe: si la bitacora falla, el cambio no ocurre. No se edita ni se borra.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (Index("ix_admin_audit_log_target", "target_type", "target_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    # SET NULL: si el administrador elimina su cuenta, lo que hizo sigue aqui.
    # Por eso se guarda tambien su correo.
    admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    admin_email: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'user.access.update', 'user.status.update', 'legal_document.publish', ...
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Texto y no FK: el objeto puede dejar de existir y la fila se conserva.
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    # Obligatorio en las acciones de acceso y de dinero (lo exige el endpoint).
    reason: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
