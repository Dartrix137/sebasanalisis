"""Usuarios, suscripciones y eventos de pago.

Las tablas de suscripciones/pagos existen en el schema desde el MVP (decision de
`docs/ARQUITECTURA_Y_ESTADISTICA.md` §3.3) y todavia no tienen logica asociada.
Wompi entra en la Fase 2, que ya esta en alcance: antes de escribir esa logica lee
las reglas de §4 del doc de arquitectura y de la seccion "Fase 2" de CLAUDE.md
(firma verificada contra la documentacion oficial vigente, el webhook no es fuente
de verdad por si solo, idempotencia por `provider_event_id`).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, enum_col, uuid_pk

ACCESS_TYPES = ("trial", "invited", "full")
USER_ROLES = ("user", "admin")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Opcional: el formulario de registro lo pide, pero no es obligatorio (§3.3).
    display_name: Mapped[str | None] = mapped_column(String(100))
    # Campo preparado, sin logica todavia: el registro deja la cuenta activa de
    # inmediato con access_type='trial'. Existe para no necesitar otra migracion
    # si mas adelante se agrega verificacion por correo.
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    access_type: Mapped[str] = mapped_column(
        enum_col(*ACCESS_TYPES, name="access_type"), default="trial", nullable=False
    )
    role: Mapped[str] = mapped_column(
        enum_col(*USER_ROLES, name="user_role"), default="user", nullable=False
    )
    created_at: Mapped[datetime] = created_at_col()

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user")


class Subscription(Base):
    """Estado de la suscripcion de un usuario. Estructura creada en el MVP; la
    logica de Wompi se implementa en la Fase 2 (ver el docstring del modulo).
    """

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_token_ref: Mapped[str | None] = mapped_column(String(255))
    plan_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="subscriptions")


class PaymentEvent(Base):
    """Bitacora de eventos del proveedor de pagos. Estructura creada en el MVP;
    la logica de Wompi se implementa en la Fase 2. `provider_event_id` es unico
    a proposito: es la clave de idempotencia frente a reintentos del webhook.
    """

    __tablename__ = "payment_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider_event_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
