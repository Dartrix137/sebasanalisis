"""
Schemas: planes, cotizacion y cupones (§3.2, §3.3, §4.4 y §4.5 de la Fase 4)

Montos siempre en centavos enteros, con la moneda al lado. Ninguna peticion
del cliente lleva un monto: el precio lo calcula el servidor.
"""
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.billing.pricing import CouponKind, CouponRejection
from app.schemas.admin import Reason
from app.schemas.base import ApiModel

# Tope de un INTEGER de Postgres.
_MAX_CENTS = 2_147_483_647

# Wompi opera en pesos colombianos (§3.10): es la unica moneda de cobro.
ChargeCurrency = Literal["COP"]


class PlanInterval(str, Enum):
    month = "month"
    year = "year"


class CouponDuration(str, Enum):
    once = "once"
    repeating = "repeating"
    forever = "forever"


# ---------- Publico y usuario ----------

class PlanResponse(ApiModel):
    """Un plan que se ofrece."""
    id: UUID
    code: str
    name: str
    description: str
    # Lo que se cobra. Es el unico precio del plan.
    price_cents: int
    currency: str
    interval: PlanInterval
    interval_count: int

    model_config = ConfigDict(from_attributes=True)


class QuoteRequest(ApiModel):
    """POST /billing/quote. No lleva montos: un monto que mande el cliente se ignora."""
    plan_id: UUID
    coupon_code: str | None = Field(default=None, max_length=80)


class QuoteCoupon(ApiModel):
    """Que paso con el codigo que se mando."""
    code: str
    applied: bool
    # Por que no aplico. Null si aplico.
    reason: CouponRejection | None = None
    message: str | None = None


class QuoteResponse(ApiModel):
    plan_id: UUID
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    currency: str
    # Null si no se mando codigo.
    coupon: QuoteCoupon | None = None


# ---------- Admin: planes ----------

class AdminPlanResponse(PlanResponse):
    active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class AdminPlanListResponse(ApiModel):
    items: list[AdminPlanResponse]
    total: int
    limit: int
    offset: int


class CreatePlanRequest(ApiModel):
    # Identificador estable; no se puede cambiar despues.
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,49}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    price_cents: int = Field(gt=0, le=_MAX_CENTS)
    currency: ChargeCurrency = "COP"
    interval: PlanInterval
    interval_count: int = Field(default=1, ge=1, le=36)
    active: bool = True
    sort_order: int = Field(default=0, ge=0, le=10_000)
    reason: str = Reason


class UpdatePlanRequest(ApiModel):
    """PATCH /admin/plans/:id. Solo cambia los campos que se mandan."""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    price_cents: int | None = Field(default=None, gt=0, le=_MAX_CENTS)
    interval: PlanInterval | None = None
    interval_count: int | None = Field(default=None, ge=1, le=36)
    active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    reason: str = Reason


# ---------- Admin: cupones ----------

class AdminCouponResponse(ApiModel):
    id: UUID
    code: str
    kind: CouponKind
    # 1..99 si es porcentaje; centavos si es monto fijo.
    value: int
    currency: str | None = None
    duration: CouponDuration
    duration_periods: int | None = None
    max_redemptions: int | None = None
    redemptions_count: int
    valid_from: datetime
    valid_until: datetime | None = None
    active: bool
    # Vacio = aplica a todos los planes.
    plan_ids: list[UUID]
    created_at: datetime


class AdminCouponListResponse(ApiModel):
    items: list[AdminCouponResponse]
    total: int
    limit: int
    offset: int


class CreateCouponRequest(ApiModel):
    # Se guarda en mayusculas; no se puede cambiar despues.
    code: str = Field(min_length=1, max_length=80)
    kind: CouponKind
    value: int = Field(gt=0, le=_MAX_CENTS)
    currency: ChargeCurrency | None = None
    duration: CouponDuration
    duration_periods: int | None = Field(default=None, ge=1, le=120)
    max_redemptions: int | None = Field(default=None, ge=1, le=_MAX_CENTS)
    # Null = desde ahora.
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    plan_ids: list[UUID] = Field(default_factory=list, max_length=50)
    active: bool = True
    reason: str = Reason


class UpdateCouponRequest(ApiModel):
    """PATCH /admin/coupons/:id. Solo cambia los campos que se mandan.

    Con redenciones, el descuento (`kind`, `value`, `currency`, `duration`,
    `duration_periods`) ya no se puede cambiar.
    """
    kind: CouponKind | None = None
    value: int | None = Field(default=None, gt=0, le=_MAX_CENTS)
    currency: ChargeCurrency | None = None
    duration: CouponDuration | None = None
    duration_periods: int | None = Field(default=None, ge=1, le=120)
    max_redemptions: int | None = Field(default=None, ge=1, le=_MAX_CENTS)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    plan_ids: list[UUID] | None = Field(default=None, max_length=50)
    active: bool | None = None
    reason: str = Reason


class CouponRedemptionResponse(ApiModel):
    id: UUID
    user_id: UUID
    user_email: str
    subscription_id: UUID | None = None
    created_at: datetime


class CouponRedemptionListResponse(ApiModel):
    items: list[CouponRedemptionResponse]
    total: int
    limit: int
    offset: int

