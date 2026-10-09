"""Cotizacion de un plan con o sin cupon (docs/PLATAFORMA_COMPLETA.md §3.3).

Python puro: sin FastAPI, sin SQLAlchemy, sin red.

El precio lo calcula siempre el servidor con `quote`. Quien llama arma
`PlanPrice` y `CouponTerms` desde la base; aqui no se busca nada. Un cupon que
no aplica NO es un error: la cotizacion sale por el precio completo y dice por
que no aplico.

Montos en centavos enteros, con la moneda explicita. Nunca float.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

#: Un cupon de porcentaje nunca llega a 100: un total en cero no se puede
#: cobrar. Una cortesia total se da como acceso `invited` desde el admin
#: (§10 n.º 6, decidido el 2026-10-09).
MAX_PERCENT = 99


class CouponKind(str, Enum):
    """Debe coincidir con `COUPON_KINDS` de `app.models.billing`."""

    percent = "percent"
    fixed_cents = "fixed_cents"


class CouponRejection(str, Enum):
    """Por que un cupon no aplica a una cotizacion."""

    #: El codigo no existe. No lo decide `quote`: lo pone quien busca el cupon.
    not_found = "not_found"
    inactive = "inactive"
    not_started = "not_started"
    expired = "expired"
    exhausted = "exhausted"
    other_plan = "other_plan"
    currency_mismatch = "currency_mismatch"
    already_used = "already_used"
    #: El descuento dejaria el total en cero o menos.
    covers_total = "covers_total"


@dataclass(frozen=True)
class PlanPrice:
    """Lo que `quote` necesita de un plan: lo que se cobra y en que moneda."""

    id: str
    price_cents: int
    currency: str


@dataclass(frozen=True)
class CouponTerms:
    """Un cupon, mas lo que la base sabe de el para este usuario."""

    kind: CouponKind
    #: 1..99 si es porcentaje; centavos si es monto fijo.
    value: int
    #: Solo con monto fijo.
    currency: str | None
    active: bool
    valid_from: datetime
    #: None = sin vencimiento.
    valid_until: datetime | None
    #: None = sin tope de usos.
    max_redemptions: int | None
    redemptions_count: int
    #: Vacio = aplica a todos los planes.
    plan_ids: frozenset[str]
    already_used_by_user: bool


@dataclass(frozen=True)
class Quote:
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    currency: str
    #: None si no se mando cupon o si el cupon aplico.
    coupon_rejection: CouponRejection | None


def percent_discount(amount_cents: int, percent: int) -> int:
    """Descuento de un porcentaje, redondeado HACIA ABAJO al centavo.

    Division entera a proposito: el redondeo queda definido sin pasar por
    float. Redondear hacia abajo el descuento es la regla escrita de §3.3;
    la diferencia frente a redondear al mas cercano es de menos de un centavo.
    """
    return amount_cents * percent // 100


def coupon_rejection(
    plan: PlanPrice, coupon: CouponTerms, now: datetime
) -> CouponRejection | None:
    """El primer motivo por el que el cupon no aplica, o None si aplica.

    El orden va de lo que es del cupon (apagado, fuera de vigencia, agotado) a
    lo que es de esta compra (plan, moneda, usuario, monto).
    """
    if not coupon.active:
        return CouponRejection.inactive
    if now < coupon.valid_from:
        return CouponRejection.not_started
    # `valid_until` es exclusivo: en ese instante el cupon ya vencio.
    if coupon.valid_until is not None and now >= coupon.valid_until:
        return CouponRejection.expired
    if coupon.max_redemptions is not None and coupon.redemptions_count >= coupon.max_redemptions:
        return CouponRejection.exhausted
    if coupon.plan_ids and plan.id not in coupon.plan_ids:
        return CouponRejection.other_plan
    if coupon.kind is CouponKind.fixed_cents and coupon.currency != plan.currency:
        return CouponRejection.currency_mismatch
    if coupon.already_used_by_user:
        return CouponRejection.already_used
    if _discount(plan, coupon) >= plan.price_cents:
        return CouponRejection.covers_total
    return None


def _discount(plan: PlanPrice, coupon: CouponTerms) -> int:
    if coupon.kind is CouponKind.percent:
        return percent_discount(plan.price_cents, coupon.value)
    return coupon.value


def quote(plan: PlanPrice, coupon: CouponTerms | None, now: datetime) -> Quote:
    """Cuanto se cobra por un periodo del plan.

    Cotiza el primer cobro. Cuantos periodos dura el descuento (`duration` del
    cupon) es asunto de las renovaciones, que llegan con el paso 5.

    `now` debe traer zona horaria, igual que las fechas del cupon.
    """
    if plan.price_cents <= 0:
        raise ValueError("El precio del plan debe ser mayor que cero")
    if coupon is not None:
        if coupon.value <= 0:
            raise ValueError("El valor del cupon debe ser mayor que cero")
        if coupon.kind is CouponKind.percent and coupon.value > MAX_PERCENT:
            raise ValueError(f"Un cupon de porcentaje va de 1 a {MAX_PERCENT}")

    rejection = coupon_rejection(plan, coupon, now) if coupon is not None else None
    discount = _discount(plan, coupon) if coupon is not None and rejection is None else 0
    return Quote(
        subtotal_cents=plan.price_cents,
        discount_cents=discount,
        total_cents=plan.price_cents - discount,
        currency=plan.currency,
        coupon_rejection=rejection,
    )
