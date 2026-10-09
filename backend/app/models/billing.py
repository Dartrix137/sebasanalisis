"""Planes y cupones (docs/PLATAFORMA_COMPLETA.md §3.2 y §3.10).

Montos en centavos enteros, con la moneda explicita. El precio se calcula en
`app/billing/pricing.py`; aqui solo se guardan los datos.

Lo que ya se uso no se borra, se desactiva (`active`): por eso las llaves que
apuntan a un plan o a un cupon son RESTRICT.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, enum_col, uuid_pk

PLAN_INTERVALS = ("month", "year")
# Deben coincidir con `CouponKind` de `app.billing.pricing`.
COUPON_KINDS = ("percent", "fixed_cents")
COUPON_DURATIONS = ("once", "repeating", "forever")


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("price_cents > 0", name="ck_plans_price_positive"),
        CheckConstraint("interval_count > 0", name="ck_plans_interval_count_positive"),
        # El precio de presentacion va completo o no va.
        CheckConstraint(
            "(display_price_cents IS NULL) = (display_currency IS NULL)",
            name="ck_plans_display_price_pair",
        ),
        CheckConstraint(
            "display_price_cents IS NULL OR display_price_cents > 0",
            name="ck_plans_display_price_positive",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Identificador estable ('mensual'). No cambia despues de creado.
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Lo que se cobra y en que moneda.
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Precio de presentacion (§3.10): SOLO visual. Es una cifra fija que escribe
    # el administrador; no sale de una tasa de cambio y nunca se usa para
    # cobrar ni para cotizar.
    display_price_cents: Mapped[int | None] = mapped_column(Integer)
    display_currency: Mapped[str | None] = mapped_column(String(3))
    interval: Mapped[str] = mapped_column(
        enum_col(*PLAN_INTERVALS, name="plan_interval", length=16), nullable=False
    )
    # 1 = cada mes; 3 = trimestral.
    interval_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # False = deja de ofrecerse. Las suscripciones que ya lo tienen siguen igual.
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint("value > 0", name="ck_coupons_value_positive"),
        # Un porcentaje nunca llega a 100: el total no puede quedar en cero
        # (§10 n.º 6). El tope es `MAX_PERCENT` de `app.billing.pricing`.
        CheckConstraint("kind <> 'percent' OR value <= 99", name="ck_coupons_percent_range"),
        CheckConstraint(
            "(kind = 'fixed_cents') = (currency IS NOT NULL)", name="ck_coupons_fixed_currency"
        ),
        CheckConstraint(
            "(duration = 'repeating') = (duration_periods IS NOT NULL)",
            name="ck_coupons_repeating_periods",
        ),
        CheckConstraint(
            "duration_periods IS NULL OR duration_periods > 0",
            name="ck_coupons_duration_periods_positive",
        ),
        CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions > 0",
            name="ck_coupons_max_redemptions_positive",
        ),
        CheckConstraint("redemptions_count >= 0", name="ck_coupons_redemptions_count"),
        CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from", name="ck_coupons_validity_order"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # En mayusculas. No cambia despues de creado.
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(
        enum_col(*COUPON_KINDS, name="coupon_kind", length=16), nullable=False
    )
    # 1..99 si es porcentaje; centavos si es monto fijo.
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    # Solo con monto fijo.
    currency: Mapped[str | None] = mapped_column(String(3))
    # Cuantos cobros lleva el descuento. Lo aplican las renovaciones (paso 5);
    # la cotizacion solo calcula el primer cobro.
    duration: Mapped[str] = mapped_column(
        enum_col(*COUPON_DURATIONS, name="coupon_duration", length=16), nullable=False
    )
    duration_periods: Mapped[int | None] = mapped_column(Integer)
    # Null = sin tope de usos.
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    redemptions_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Null = sin vencimiento. Exclusivo: en ese instante ya vencio.
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    # Null si ese administrador elimino su cuenta.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()

    # Sin filas = aplica a todos los planes.
    plans: Mapped[list[Plan]] = relationship(secondary="coupon_plans", order_by=Plan.sort_order)


class CouponPlan(Base):
    __tablename__ = "coupon_plans"

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coupons.id", ondelete="CASCADE"), primary_key=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class CouponRedemption(Base):
    """Un uso de un cupon. Las escribe el pago aprobado (paso 5); hasta
    entonces la tabla solo se lee.

    `user_id` es CASCADE como el resto de lo que hoy cuelga de la cuenta. El
    paso 5 revisa ese `ON DELETE` junto con el de `subscriptions` (§5.7.1):
    con CASCADE, eliminar la cuenta borra tambien el rastro de que uso el cupon.
    """

    __tablename__ = "coupon_redemptions"
    __table_args__ = (
        # Un cupon se usa una sola vez por cuenta.
        UniqueConstraint("coupon_id", "user_id", name="uq_coupon_redemptions_coupon_user"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # RESTRICT: un cupon con redenciones no se borra.
    coupon_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coupons.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()

