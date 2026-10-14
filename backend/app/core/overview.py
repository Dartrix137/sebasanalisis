"""Resumen del admin (docs/PLATAFORMA_COMPLETA.md §4.7 y §4.9).

Todo se calcula aqui, en el servidor, con montos en centavos y la moneda al
lado. La pantalla solo lo muestra.

Dos clases de indicadores (decidido el 2026-10-14):

- **De flujo** (altas, cancelaciones, cobros fallidos, registros, lo cobrado):
  se cuentan dentro del mes calendario en curso, en hora de Bogota, hasta
  ahora, y se comparan con el mismo tramo del mes anterior (del dia 1 al mismo
  dia y hora). `periods` arma esas ventanas.
- **Fotos del momento** (suscripciones por estado, ingreso recurrente): dicen
  como esta la base ahora. No se comparan con el mes anterior: la base no
  guarda como estaban en una fecha pasada.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.billing import pricing
from app.models import Coupon, Payment, PaymentRefund, Plan, Subscription, User

#: La zona del negocio. Colombia no tiene horario de verano.
BOGOTA = ZoneInfo("America/Bogota")


@dataclass(frozen=True)
class Window:
    """[start, end): incluye el inicio, excluye el final."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class Periods:
    current: Window
    previous: Window


def periods(now: datetime) -> Periods:
    """El mes en curso hasta `now`, y el mismo tramo del mes anterior.

    El tramo anterior va del dia 1 del mes pasado al mismo dia y hora; si el mes
    pasado es mas corto (31 de marzo frente a febrero), termina al final de ese
    mes. Las fronteras son medianoche de Bogota; las fechas salen en UTC.
    """
    local = now.astimezone(BOGOTA)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 1:
        prev_start = start.replace(year=start.year - 1, month=12)
    else:
        prev_start = start.replace(month=start.month - 1)
    days_in_prev = monthrange(prev_start.year, prev_start.month)[1]
    if local.day > days_in_prev:
        prev_end = start
    else:
        prev_end = local.replace(year=prev_start.year, month=prev_start.month)
    return Periods(
        current=Window(start.astimezone(UTC), now.astimezone(UTC)),
        previous=Window(prev_start.astimezone(UTC), prev_end.astimezone(UTC)),
    )


def monthly_cents(amount_cents: int, interval: str, interval_count: int) -> int:
    """Lo que vale un cobro de cada `interval_count` intervalos, llevado a un
    mes. Redondea hacia abajo al centavo: `15000000` cada 2 meses -> `7500000`."""
    months = interval_count * (12 if interval == "year" else 1)
    return amount_cents // months


# ---------- Consultas ----------


def _in(column, window: Window):  # type: ignore[no-untyped-def]
    return (column >= window.start) & (column < window.end)


@dataclass(frozen=True)
class Recurring:
    currency: str
    total_cents: int
    automatic_cents: int
    manual_cents: int
    subscriptions: int


def recurring(db: Session, now: datetime) -> list[Recurring]:
    """Ingreso recurrente mensual, por moneda (decidido el 2026-10-14).

    Cuenta las suscripciones vigentes que siguen: activas y en mora, de los dos
    modos, sin las canceladas. Cada una con lo que costara su proximo periodo
    (precio congelado menos el descuento que todavia lleve), llevado a un mes.
    """
    rows = db.execute(
        select(Subscription, Plan)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Subscription.status.in_(("active", "past_due")),
            Subscription.current_period_end > now,
        )
    ).all()
    coupon_ids = {s.coupon_id for s, _ in rows if s.coupon_id is not None}
    coupons = (
        {c.id: c for c in db.scalars(select(Coupon).where(Coupon.id.in_(coupon_ids)))}
        if coupon_ids
        else {}
    )
    totals: dict[str, dict[str, int]] = {}
    for subscription, plan in rows:
        quote = pricing.renewal_quote(
            subscription.price_cents,
            subscription.currency,
            _discount(coupons.get(subscription.coupon_id), subscription),
        )
        cents = monthly_cents(quote.total_cents, plan.interval, plan.interval_count)
        bucket = totals.setdefault(
            subscription.currency, {"automatic": 0, "manual": 0, "count": 0}
        )
        bucket["automatic" if subscription.renewal_mode == "automatic" else "manual"] += cents
        bucket["count"] += 1
    return [
        Recurring(
            currency=currency,
            total_cents=b["automatic"] + b["manual"],
            automatic_cents=b["automatic"],
            manual_cents=b["manual"],
            subscriptions=b["count"],
        )
        for currency, b in sorted(totals.items())
    ]


def _discount(coupon: Coupon | None, subscription: Subscription) -> pricing.RenewalDiscount | None:
    """Lo mismo que `core/subscriptions.renewal_discount`, con el cupon ya leido."""
    if coupon is None:
        return None
    return pricing.RenewalDiscount(
        kind=pricing.CouponKind(coupon.kind),
        value=coupon.value,
        currency=coupon.currency,
        periods_remaining=subscription.discount_periods_remaining,
    )


def subscriptions_by_status(db: Session) -> dict[str, int]:
    found = dict(
        db.execute(  # type: ignore[arg-type]
            select(Subscription.status, func.count()).group_by(Subscription.status)
        ).all()
    )
    return {
        status: int(found.get(status, 0))
        for status in ("pending", "active", "past_due", "canceled", "expired")
    }


def in_force_count(db: Session, now: datetime) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(
                Subscription.status.in_(("active", "canceled", "past_due")),
                Subscription.current_period_end > now,
            )
        )
        or 0
    )


def new_subscriptions(db: Session, window: Window) -> int:
    """Altas: suscripciones cuyo primer pago se aprobo en la ventana. Volver
    despues de vencida tambien es un alta (es una suscripcion nueva). Un pago
    anulado despues no cuenta."""
    return (
        db.scalar(
            select(func.count(distinct(Payment.subscription_id))).where(
                Payment.kind == "initial",
                Payment.status == "approved",
                _in(Payment.resolved_at, window),
            )
        )
        or 0
    )


def cancellations(db: Session, window: Window) -> int:
    """Suscripciones canceladas en la ventana, por el cliente o por un
    administrador. Una que se reanudo ya no cuenta: reanudar borra la fecha."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(_in(Subscription.canceled_at, window))
        )
        or 0
    )


def in_force_at(db: Session, moment: datetime) -> int:
    """Suscripciones con un periodo pagado que cubria `moment`, segun sus pagos
    aprobados. Es la base de la tasa de cancelacion. Aproxima: una extension
    hecha a mano por un administrador no tiene pago que la respalde."""
    return (
        db.scalar(
            select(func.count(distinct(Payment.subscription_id))).where(
                Payment.status == "approved",
                Payment.subscription_id.is_not(None),
                Payment.period_start <= moment,
                Payment.period_end > moment,
            )
        )
        or 0
    )


def rate_bp(numerator: int, denominator: int) -> int | None:
    """Una tasa en puntos basicos (1 % = 100), redondeada hacia abajo. Null sin base."""
    if denominator <= 0:
        return None
    return numerator * 10_000 // denominator


def failed_charges(db: Session, window: Window) -> int:
    """Cobros rechazados o con error resueltos en la ventana. No cuenta los que
    nunca se completaron (`pending`): casi siempre son pagos que el cliente
    abrio y no termino."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.status.in_(("declined", "error")), _in(Payment.resolved_at, window))
        )
        or 0
    )


def registrations(db: Session, window: Window) -> tuple[int, int]:
    """Cuentas creadas en la ventana, y cuantas de ellas ya confirmaron el
    correo. Una cuenta que se elimino ya no cuenta."""
    total, verified = db.execute(
        select(
            func.count(),
            func.count().filter(User.email_verified.is_(True)),
        ).where(_in(User.created_at, window))
    ).one()
    return int(total), int(verified)


def collected(db: Session, window: Window) -> dict[str, int]:
    """Lo cobrado en la ventana, por moneda: pagos aprobados menos los
    reembolsos registrados con fecha en la ventana (decidido el 2026-10-14). Un
    pago anulado despues no cuenta: el dinero no se quedo."""
    paid = dict(
        db.execute(  # type: ignore[arg-type]
            select(Payment.currency, func.sum(Payment.amount_cents))
            .where(Payment.status == "approved", _in(Payment.resolved_at, window))
            .group_by(Payment.currency)
        ).all()
    )
    refunded = dict(
        db.execute(  # type: ignore[arg-type]
            select(PaymentRefund.currency, func.sum(PaymentRefund.amount_cents))
            .where(_in(PaymentRefund.refunded_at, window))
            .group_by(PaymentRefund.currency)
        ).all()
    )
    return {
        currency: int(paid.get(currency, 0)) - int(refunded.get(currency, 0))
        for currency in sorted(set(paid) | set(refunded))
    }
