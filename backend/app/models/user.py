"""Usuarios, suscripciones, pagos y eventos del proveedor de pagos.

Modelo de datos de docs/PLATAFORMA_COMPLETA.md §3.2. La logica vive en
`app/core/subscriptions.py`; antes de tocarla lee "Pagos con Wompi: reglas no
negociables" en CLAUDE.md (firma verificada contra la documentacion oficial
vigente, el webhook no es fuente de verdad por si solo, idempotencia por
`provider_event_id`).

Nunca se guardan datos de tarjeta: solo la referencia del proveedor y, para
mostrar, la marca y los ultimos cuatro digitos.

Al eliminar una cuenta (decidido el 2026-10-13) la suscripcion se borra con
ella y los pagos y sus eventos se conservan sin usuario: por eso `payments` y
`payment_events` apuntan con SET NULL.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, enum_col, uuid_pk

if TYPE_CHECKING:
    from app.models.billing import Plan

# `none`: sin acceso hasta pagar o hasta que un administrador se lo otorgue.
ACCESS_TYPES = ("none", "invited", "full")
USER_ROLES = ("user", "admin")

SUBSCRIPTION_STATUSES = ("pending", "active", "past_due", "canceled", "expired")
# Las que cuentan como "la suscripcion de la cuenta": solo puede haber una.
LIVE_SUBSCRIPTION_STATUSES = ("pending", "active", "past_due")
# `manual`: el usuario paga cada periodo. `automatic`: se cobra a una fuente de
# pago tokenizada (entrega 2 del paso 5).
RENEWAL_MODES = ("manual", "automatic")
PAYMENT_KINDS = ("initial", "renewal")
PAYMENT_STATUSES = ("pending", "approved", "declined", "voided", "error")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Opcional: el formulario de registro lo pide, pero no es obligatorio (§3.3).
    display_name: Mapped[str | None] = mapped_column(String(100))
    # Se pone en True al confirmar el enlace del correo (§5.2 de la Fase 4). No
    # da ni quita acceso a la mesa por si solo: es requisito para pagar.
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Viaja en el JWT. Cambiar o restablecer la contrasena la incrementa, y con
    # eso todo token emitido antes deja de valer: cierra las demas sesiones sin
    # necesitar una tabla de refresh tokens (§5.3).
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    access_type: Mapped[str] = mapped_column(
        enum_col(*ACCESS_TYPES, name="access_type"), default="none", nullable=False
    )
    # Vencimiento del acceso `invited`. Null = sin vencimiento.
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # False = cuenta suspendida por un administrador: entra a su cuenta, no a la
    # mesa. Quien decide el acceso es `core/access.has_access`, no este campo.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    role: Mapped[str] = mapped_column(
        enum_col(*USER_ROLES, name="user_role"), default="user", nullable=False
    )
    # Declaracion de mayoria de edad (§6.3 de la Fase 4). Null en las cuentas
    # anteriores al paso 2 hasta que la confirmen al entrar a la mesa.
    adult_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Cuando leyo hasta el final la pantalla que explica que hace y que no hace
    # la plataforma. Es informativa: no es un consentimiento legal.
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user")


class Subscription(Base):
    """La suscripcion de una cuenta a un plan.

    Da acceso mientras `current_period_end` este en el futuro; quien lo decide
    es `core/access.has_access`. El precio queda congelado al suscribirse
    (§3.7): cambiar el precio del plan no toca esta fila.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("price_cents > 0", name="ck_subscriptions_price_positive"),
        # Una cuenta no tiene dos suscripciones pendientes, activas o en mora a
        # la vez (§3.4). En la base, no solo en el codigo.
        Index(
            "uq_subscriptions_one_live_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'active', 'past_due')"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # RESTRICT: un plan con suscripciones no se borra, se desactiva.
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        enum_col(*SUBSCRIPTION_STATUSES, name="subscription_status", length=50), nullable=False
    )
    renewal_mode: Mapped[str] = mapped_column(
        enum_col(*RENEWAL_MODES, name="subscription_renewal_mode", length=16),
        default="manual",
        server_default="manual",
        nullable=False,
    )
    # Congelados al suscribirse, en centavos.
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    coupon_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("coupons.id", ondelete="RESTRICT")
    )
    # Periodos que todavia llevan el descuento del cupon. Null con un cupon
    # `forever` (o sin cupon): no hay cuenta que llevar.
    discount_periods_remaining: Mapped[int | None] = mapped_column(Integer)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # Referencia de la fuente de pago en el proveedor. Nunca datos de tarjeta.
    payment_source_id: Mapped[str | None] = mapped_column(String(255))
    # CARD o NEQUI. Las cuotas solo se mandan al cobrar si es una tarjeta.
    payment_source_type: Mapped[str | None] = mapped_column(String(16))
    card_brand: Mapped[str | None] = mapped_column(String(50))
    card_last4: Mapped[str | None] = mapped_column(String(4))
    next_charge_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # El `current_period_end` del periodo cuyo aviso por correo ya se envio:
    # el aviso sale una vez por periodo aunque el job corra cada hora (§3.8).
    notice_sent_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="subscriptions")
    plan: Mapped["Plan"] = relationship()


class Payment(Base):
    """Un intento de cobro de un periodo.

    `reference` es unica: es lo que viaja al proveedor y lo que une su
    transaccion con esta fila. El plan y el cupon se anotan aqui, y no solo en
    la suscripcion, porque una cuenta puede abrir dos pagos distintos antes de
    completar uno: el que se aprueba decide que se compro.

    `period_start` y `period_end` se fijan al aprobarse: en el pago manual el
    periodo depende de cuando se paga.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_payments_amount_positive"),
        CheckConstraint("discount_cents >= 0", name="ck_payments_discount_not_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # SET NULL en los dos: el pago sobrevive, sin usuario, a la cuenta eliminada.
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    coupon_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("coupons.id", ondelete="RESTRICT")
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    reference: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(
        enum_col(*PAYMENT_KINDS, name="payment_kind", length=16), nullable=False
    )
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lo que se cobra, ya con el descuento, en centavos.
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    discount_cents: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    provider_transaction_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(
        enum_col(*PAYMENT_STATUSES, name="payment_status", length=16),
        default="pending",
        nullable=False,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped["Plan"] = relationship()


class PaymentEvent(Base):
    """Bitacora de TODO evento que manda el proveedor de pagos, con firma valida
    o no (`signature_verified`), para poder auditar intentos de falsificacion.

    `provider_event_id` es unico a proposito: es la clave de idempotencia frente
    a los reintentos del webhook. Un evento de una referencia que no es nuestra
    queda sin suscripcion ni pago.
    """

    __tablename__ = "payment_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), index=True
    )
    provider_event_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Null mientras no se haya terminado de procesar: un reintento lo retoma.
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()
