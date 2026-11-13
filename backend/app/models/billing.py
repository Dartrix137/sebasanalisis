"""Planes, cupones y facturas (docs/PLATAFORMA_COMPLETA.md §3.2, §3.10 y §3.17).

Montos en centavos enteros, con la moneda explicita. El precio se calcula en
`app/billing/pricing.py`; aqui solo se guardan los datos.

Lo que ya se uso no se borra, se desactiva (`active`): por eso las llaves que
apuntan a un plan o a un cupon son RESTRICT.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_col, enum_col, uuid_pk

if TYPE_CHECKING:
    from app.models.game import Game

PLAN_INTERVALS = ("month", "year")
# Deben coincidir con `CouponKind` de `app.billing.pricing`.
COUPON_KINDS = ("percent", "fixed_cents")
COUPON_DURATIONS = ("once", "repeating", "forever")


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("price_cents > 0", name="ck_plans_price_positive"),
        CheckConstraint("interval_count > 0", name="ck_plans_interval_count_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Identificador estable ('mensual'). No cambia despues de creado.
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Lo que se cobra y en que moneda.
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
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

    # Juegos incluidos (§7.4). Vacio = todos, tambien los que se creen despues.
    games: Mapped[list["Game"]] = relationship(
        secondary="plan_games", order_by="Game.sort_order"
    )

    @property
    def all_games(self) -> bool:
        return not self.games

    @property
    def game_ids(self) -> list[uuid.UUID]:
        return [g.id for g in self.games]


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

    `user_id` es SET NULL (paso 5, entrega 3): al eliminar la cuenta el uso
    queda, sin nada que la identifique, igual que sus pagos. Asi
    `coupons.redemptions_count` sigue coincidiendo con las filas.
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
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_col()



class PriceChange(Base):
    """Un traslado del precio actual de un plan a sus suscripciones vigentes
    (§10 n.º 5; decidido el 2026-10-14, construido en el paso 6).

    El precio congelado de una suscripcion (§3.7) solo cambia por aqui, y cada
    suscripcion alcanzada lleva su fila en `subscription_price_changes`: su
    aviso, cuando le aplica y si se aplico. Lo registra un administrador con
    motivo; los avisos los envia el job de renovaciones.
    """

    __tablename__ = "price_changes"
    __table_args__ = (
        CheckConstraint("new_price_cents > 0", name="ck_price_changes_price_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # RESTRICT: un plan con historia no se borra.
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    # El precio del plan al registrar el traslado: el que pasa a cobrarse.
    new_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # SET NULL: si ese administrador elimina su cuenta, el traslado queda.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    # Cancelado antes de aplicarse a todas: las que faltaban conservan su precio.
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[Plan] = relationship()


class SubscriptionPriceChange(Base):
    """Lo que un traslado de precio le hace a una suscripcion.

    - Subida: el precio nuevo aplica 30 dias despues de que su aviso se envio de
      verdad (`notice_sent_at`), no de cuando se registro el traslado.
    - Bajada: se aplica al registrar el traslado; el aviso es informativo.

    `applied_at` dice cuando se cambio `subscriptions.price_cents`. Una fila
    cancelada (`canceled_at`) no se aplica; si su aviso ya habia salido, el
    cliente recibe otro que dice que el precio no cambia
    (`cancel_notice_sent_at`).
    """

    __tablename__ = "subscription_price_changes"
    __table_args__ = (
        UniqueConstraint(
            "price_change_id", "subscription_id", name="uq_subscription_price_changes_pair"
        ),
        CheckConstraint("old_price_cents > 0", name="ck_subscription_price_changes_old_positive"),
        CheckConstraint("new_price_cents > 0", name="ck_subscription_price_changes_new_positive"),
        CheckConstraint(
            "old_price_cents <> new_price_cents", name="ck_subscription_price_changes_changes"
        ),
        # Una suscripcion no tiene dos traslados abiertos a la vez.
        Index(
            "uq_subscription_price_changes_one_open",
            "subscription_id",
            unique=True,
            postgresql_where=text("applied_at IS NULL AND canceled_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    price_change_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("price_changes.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    # CASCADE: la suscripcion se borra con la cuenta (§3.15), y esto con ella.
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    old_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    new_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Desde cuando se cobra el precio nuevo. Null mientras no haya salido el
    # aviso de una subida.
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    price_change: Mapped[PriceChange] = relationship()


# Deben coincidir con los estados de `core/invoices.py`.
INVOICE_STATUSES = (
    "pending", "sending", "issued", "accepted", "rejected", "failed", "cancelled"
)
#: Por que una factura no se emite (`invoices.cancel_reason`).
INVOICE_CANCEL_REASONS = ("refunded", "voided", "annulled_in_siigo", "test_payment")


class Invoice(Base):
    """La factura electronica de un pago aprobado (§3.17; Fase 5, paso 5.2).

    Nace `pending` en la misma transaccion en que `apply_transaction` aprueba el
    pago (`core/invoices.create_pending`), y es unica por pago: un webhook
    repetido no deja dos. La emision con Siigo es del paso 5.4; hasta
    entonces ninguna sale de `pending`.

    Desde el paso 5.4 se emite con Siigo (`core/invoices.py`). Antes del primer
    envio se congela todo lo que lleva: el monto en pesos, las tasas con su dia
    y su fuente, y una copia de los datos de facturacion del comprador (la
    factura va a cada comprador). Los reintentos mandan lo mismo, con la misma
    `idempotency_key`.

    Estados (§3.17, "Paso 5.4", punto 3): `pending` (sin enviar), `sending`
    (salio y no se sabe el resultado), `issued` (creada en Siigo, esperando a
    la DIAN), `accepted` (con CUFE), `rejected` (la DIAN la rechazo) y
    `failed` (Siigo rechazo los datos: no se reintenta sola). Y `cancelled`
    (2026-11-11, la contadora): no se emite, porque su pago se reembolso entero
    o se anulo antes de que la DIAN la aceptara (`core/credit_notes.py`).

    Es un documento tributario: no se borra al eliminar la cuenta, y por eso la
    llave al pago es RESTRICT (los pagos tampoco se borran).
    """

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = uuid_pk()
    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        enum_col(*INVOICE_STATUSES, name="invoice_status", length=20), nullable=False
    )
    # El dia de la aprobacion del pago en hora de Colombia (`billing/fx`),
    # congelado al crear la fila.
    operation_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    # --- Lo congelado antes del primer envio (`prepared_at`) ---
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(30), unique=True)
    cop_cents: Mapped[int | None] = mapped_column(BigInteger)
    eur_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    eur_usd_date: Mapped[date | None] = mapped_column(Date)
    eur_usd_source: Mapped[str | None] = mapped_column(String(200))
    usd_cop: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    usd_cop_date: Mapped[date | None] = mapped_column(Date)
    usd_cop_source: Mapped[str | None] = mapped_column(String(200))
    observations: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(String(500))
    # Copia de los datos de facturacion del comprador al preparar.
    buyer_first_names: Mapped[str | None] = mapped_column(String(50))
    buyer_last_names: Mapped[str | None] = mapped_column(String(50))
    buyer_id_type: Mapped[str | None] = mapped_column(String(2))
    buyer_id_number: Mapped[str | None] = mapped_column(String(20))
    buyer_email: Mapped[str | None] = mapped_column(String(255))
    buyer_country_code: Mapped[str | None] = mapped_column(String(4))
    buyer_state_code: Mapped[str | None] = mapped_column(String(10))
    buyer_city_code: Mapped[str | None] = mapped_column(String(10))
    buyer_address: Mapped[str | None] = mapped_column(String(256))

    # --- La emision ---
    # Por que todavia no sale: `billing_profile_missing`, `rates_pending`...
    waiting_reason: Mapped[str | None] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # El dia con el que se mando a Siigo (no puede ser anterior a hoy).
    issue_date: Mapped[date | None] = mapped_column(Date)
    provider_id: Mapped[str | None] = mapped_column(String(64))
    provider_name: Mapped[str | None] = mapped_column(String(40))
    provider_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    stamp_status: Mapped[str | None] = mapped_column(String(20))
    cufe: Mapped[str | None] = mapped_column(String(200))
    mail_status: Mapped[str | None] = mapped_column(String(20))
    last_error_codes: Mapped[list[str] | None] = mapped_column(JSONB)
    last_error_message: Mapped[str | None] = mapped_column(String(500))
    dian_errors: Mapped[list[str] | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Cuando y por que no se emite (`cancelled`).
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(
        enum_col(*INVOICE_CANCEL_REASONS, name="invoice_cancel_reason", length=20)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# Deben coincidir con los estados de `core/credit_notes.py`.
CREDIT_NOTE_STATUSES = (
    "pending", "sending", "issued", "accepted", "rejected", "failed", "cancelled"
)
#: Los motivos de la DIAN que usamos (Siigo, crear nota credito; la contadora,
#: 2026-11-11): 2 si devuelve la factura entera, 1 si una parte.
CREDIT_NOTE_REASONS = (1, 2)


class CreditNote(Base):
    """La nota credito electronica de un reembolso o una anulacion (§3.17,
    "Paso 5.4", punto 12; Fase 5, paso 5.4).

    La crea `core/credit_notes.py` en la misma transaccion en que se registra
    el reembolso (`payment_refunds`) o en que la pasarela anula el pago. Se
    emite solo sobre una factura aceptada por la DIAN (la contadora): mientras
    tanto espera. Lleva el valor en pesos de la factura, con sus tasas
    congeladas, sin importar la tasa del dia del reembolso (la contadora).

    Estados, como los de la factura: `pending`, `sending`, `issued`,
    `accepted`, `rejected`, `failed` y `cancelled` (su factura no se emitio).
    Es un documento tributario: no se borra.
    """

    __tablename__ = "credit_notes"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_credit_notes_amount_positive"),
        CheckConstraint("cop_cents IS NULL OR cop_cents > 0", name="ck_credit_notes_cop_positive"),
        CheckConstraint("reason IN (1, 2)", name="ck_credit_notes_reason"),
        # Un reembolso tiene a lo sumo una nota credito.
        UniqueConstraint("refund_id", name="uq_credit_notes_refund_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    # El reembolso que la origino; null si fue una anulacion de la pasarela.
    refund_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_refunds.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(
        enum_col(*CREDIT_NOTE_STATUSES, name="credit_note_status", length=20), nullable=False
    )
    #: 2 (anulacion de la factura) o 1 (devolucion parcial).
    reason: Mapped[int] = mapped_column(Integer, nullable=False)
    # Lo devuelto, en la moneda del pago.
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    # --- Lo congelado antes del primer envio ---
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(30), unique=True)
    cop_cents: Mapped[int | None] = mapped_column(BigInteger)
    observations: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(String(500))

    # --- La emision ---
    waiting_reason: Mapped[str | None] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issue_date: Mapped[date | None] = mapped_column(Date)
    provider_id: Mapped[str | None] = mapped_column(String(64))
    provider_name: Mapped[str | None] = mapped_column(String(40))
    provider_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    stamp_status: Mapped[str | None] = mapped_column(String(20))
    # El CUDE de la nota (la factura lleva CUFE).
    cude: Mapped[str | None] = mapped_column(String(200))
    mail_status: Mapped[str | None] = mapped_column(String(20))
    last_error_codes: Mapped[list[str] | None] = mapped_column(JSONB)
    last_error_message: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# Deben coincidir con `Pair` de `app.billing.exchange_rates`.
EXCHANGE_RATE_PAIRS = ("USD/COP", "EUR/USD")


class ExchangeRate(Base):
    """Una tasa de cambio con su vigencia y su fuente (§3.17, "Paso 5.4",
    punto 5; Fase 5, paso 5.4).

    La TRM (`USD/COP`) sale de datos.gov.co y cubre a veces varios dias (un fin
    de semana); la del BCE (`EUR/USD`) es de un dia. Se guardan al consultarlas
    (`core/exchange_rates.py`) y no se editan: una factura congela las suyas, y
    la tabla deja constancia de donde salieron. Una sola fila por par y dia de
    inicio.
    """

    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("pair", "valid_from", name="uq_exchange_rates_pair_valid_from"),
        CheckConstraint("rate > 0", name="ck_exchange_rates_rate_positive"),
        CheckConstraint("valid_to >= valid_from", name="ck_exchange_rates_validity"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    pair: Mapped[str] = mapped_column(
        enum_col(*EXCHANGE_RATE_PAIRS, name="exchange_rate_pair", length=10), nullable=False
    )
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    # Numeric, nunca float: la TRM trae 2 decimales y el BCE hasta 5.
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    fetched_at: Mapped[datetime] = created_at_col()


# Deben coincidir con `IdType` de `app.billing.billing_profile`.
BILLING_ID_TYPES = ("13", "22", "50", "41", "42")


class BillingProfile(Base):
    """Los datos de facturacion de una cuenta (§3.17, "Paso 5.4", punto 8;
    Fase 5, paso 5.4).

    Se piden al pagar, no al registrarse, y los valida `billing/billing_profile`.
    Una fila por cuenta, que se borra con ella (CASCADE). La factura emitida
    guarda su propia copia: un cambio posterior no altera una factura, y la
    eliminacion de la cuenta no borra lo que ya se facturo.

    Son datos personales: el documento no va en un log, ni en GlitchTip, ni en
    una URL.
    """

    __tablename__ = "billing_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    first_names: Mapped[str] = mapped_column(String(50), nullable=False)
    last_names: Mapped[str] = mapped_column(String(50), nullable=False)
    id_type: Mapped[str] = mapped_column(
        enum_col(*BILLING_ID_TYPES, name="billing_id_type", length=2), nullable=False
    )
    id_number: Mapped[str] = mapped_column(String(20), nullable=False)
    # Los codigos de Siigo (`billing/places`), tal como vienen en su lista.
    country_code: Mapped[str] = mapped_column(String(4), nullable=False)
    state_code: Mapped[str] = mapped_column(String(10), nullable=False)
    city_code: Mapped[str] = mapped_column(String(10), nullable=False)
    address: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
