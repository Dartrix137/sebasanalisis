"""Tokens de un solo uso que viajan por correo (docs/PLATAFORMA_COMPLETA.md §5.1).

En la base solo vive el hash del token: el token en claro existe unicamente en el
enlace del correo. Quien lea esta tabla no puede verificar un correo ni
restablecer una contrasena ajena.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, enum_col, uuid_pk

TOKEN_PURPOSES = ("verify_email", "reset_password", "change_email")


class UserToken(Base):
    __tablename__ = "user_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(
        enum_col(*TOKEN_PURPOSES, name="user_token_purpose", length=32), nullable=False
    )
    # SHA-256 en hexadecimal. Unico: es por donde se busca el token.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Solo con `change_email`: el correo que se aplica al confirmar.
    new_email: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
