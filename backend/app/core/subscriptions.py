"""Suscripciones y pagos (docs/PLATAFORMA_COMPLETA.md §3.4 y §3.10).

Dos operaciones:

- `start_payment`: abre el pago de un periodo. El monto sale siempre de
  `billing/pricing.quote` o del precio congelado de la suscripcion; nunca de lo
  que mande el cliente.
- `apply_transaction`: la UNICA funcion que mueve un pago y su suscripcion. La
  usan el webhook y la consulta del estado del pago, y siempre con una
  transaccion que salio de reconsultar al proveedor (`fetch_transaction`), no
  del cuerpo de un evento. Es idempotente: un pago se resuelve una sola vez,
  asi lleguen el mismo evento repetido, dos eventos distintos o el webhook y la
  consulta a la vez.

Aqui no se decide el acceso: lo decide `core/access.has_access` a partir de
`status` y `current_period_end`.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.billing import pricing
from app.billing.coupon_codes import normalize_code
from app.billing.periods import next_period
from app.billing.pricing import CouponRejection
from app.core import legal
from app.core.access import has_access
from app.models import Coupon, CouponRedemption, Payment, Plan, Subscription, User
from app.models.user import LIVE_SUBSCRIPTION_STATUSES
from app.payments.base import PaymentProvider, ProviderTransaction

logger = logging.getLogger(__name__)

# Con estos estados la suscripcion tiene un periodo pagado que cuenta.
_STATUSES_WITH_PAID_PERIOD = ("active", "canceled", "past_due")
# Accesos que no salen de una suscripcion: a esas cuentas no se les cobra.
_ACCESS_WITHOUT_SUBSCRIPTION = ("admin", "full", "invited")


class SubscribeError(Exception):
    """Por que no se pudo abrir el pago. `code` viaja al cliente."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        coupon_reason: CouponRejection | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.coupon_reason = coupon_reason


@dataclass(frozen=True)
class StartedPayment:
    payment: Payment
    subtotal_cents: int


@dataclass(frozen=True)
class Settlement:
    """Lo que paso al aplicar una transaccion a un pago."""

    payment: Payment
    #: Esta llamada resolvio el pago. False si ya estaba resuelto o sigue pendiente.
    changed: bool = False
    #: Esta llamada activo la suscripcion por primera vez.
    activated: bool = False


def live_subscription(db: Session, user_id: uuid.UUID) -> Subscription | None:
    """La suscripcion pendiente, activa o en mora de la cuenta. Hay a lo sumo una."""
    return db.scalar(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        )
    )


def current_subscription(db: Session, user_id: uuid.UUID) -> Subscription | None:
    """La suscripcion que se le muestra a la cuenta: la que tiene un periodo
    pagado, vigente o no. Una que nunca se pago (`pending`) no cuenta."""
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status.in_(_STATUSES_WITH_PAID_PERIOD),
            Subscription.current_period_end.is_not(None),
        )
        .order_by(Subscription.current_period_end.desc())
        .limit(1)
    )


def coupon_terms(db: Session, coupon: Coupon, user: User) -> pricing.CouponTerms:
    """Lo que `pricing.quote` necesita saber de un cupon para esta cuenta."""
    already_used = (
        db.scalar(
            select(CouponRedemption.id).where(
                CouponRedemption.coupon_id == coupon.id, CouponRedemption.user_id == user.id
            )
        )
        is not None
    )
    return pricing.CouponTerms(
        kind=pricing.CouponKind(coupon.kind),
        value=coupon.value,
        currency=coupon.currency,
        active=coupon.active,
        valid_from=coupon.valid_from,
        valid_until=coupon.valid_until,
        max_redemptions=coupon.max_redemptions,
        redemptions_count=coupon.redemptions_count,
        plan_ids=frozenset(str(p.id) for p in coupon.plans),
        already_used_by_user=already_used,
    )


def _check_can_pay(db: Session, user: User, now: datetime) -> None:
    """Requisitos de la cuenta para pagar (§3.4)."""
    if not user.is_active:
        raise SubscribeError(403, "suspended", "Tu cuenta está suspendida.")
    if not user.email_verified:
        raise SubscribeError(
            403, "email_not_verified", "Confirma tu correo antes de suscribirte."
        )
    if legal.pending_consent(db, user).any:
        raise SubscribeError(
            403,
            "consent_required",
            "Antes de suscribirte debes aceptar la versión vigente de los documentos legales.",
        )
    # Un administrador o una cuenta con acceso manual ya entra a la mesa sin
    # pagar (decidido el 2026-10-13): no se le ofrece suscribirse.
    if has_access(db, user, now).reason in _ACCESS_WITHOUT_SUBSCRIPTION:
        raise SubscribeError(
            409, "already_has_access", "Tu cuenta ya tiene acceso: no necesita una suscripción."
        )


def start_payment(
    db: Session,
    *,
    user: User,
    plan_id: uuid.UUID,
    coupon_code: str | None,
    provider: PaymentProvider,
    now: datetime,
) -> StartedPayment:
    """Abre el pago manual de un periodo y lo confirma en la base.

    Con una suscripcion ya pagada, el pago es del periodo siguiente del mismo
    plan, por el precio congelado. Sin ella, es el alta: precio del plan menos
    el cupon, si aplica.
    """
    if not provider.enabled:
        raise SubscribeError(503, "payments_unavailable", "El pago todavía no está disponible.")
    _check_can_pay(db, user, now)

    # Serializa los intentos simultaneos de la misma cuenta.
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    subscription = live_subscription(db, user.id)
    code = normalize_code(coupon_code or "")

    in_force = (
        subscription is not None
        and subscription.status != "pending"
        and subscription.current_period_end is not None
        and subscription.current_period_end > now
    )
    if subscription is not None and in_force:
        # Periodo siguiente de una suscripcion pagada y todavia vigente.
        if subscription.plan_id != plan_id:
            raise SubscribeError(
                409,
                "other_plan",
                "Ya tienes una suscripción a otro plan. Para cambiar de plan, espera a que "
                "termine el período que ya pagaste.",
            )
        if code:
            raise SubscribeError(
                400,
                "coupon_only_on_first_payment",
                "Los cupones solo aplican al primer pago de una suscripción.",
            )
        plan = subscription.plan
        kind = "renewal"
        subtotal, discount, currency = subscription.price_cents, 0, subscription.currency
        coupon: Coupon | None = None
    else:
        found = db.get(Plan, plan_id)
        # Un plan desactivado ya no se ofrece: para quien paga, no existe.
        if found is None or not found.active:
            raise SubscribeError(404, "plan_not_found", "Plan no encontrado")
        plan = found
        kind = "initial"
        coupon = db.scalar(select(Coupon).where(Coupon.code == code)) if code else None
        if code and coupon is None:
            raise _coupon_rejected(CouponRejection.not_found)
        quote = pricing.quote(
            pricing.PlanPrice(id=str(plan.id), price_cents=plan.price_cents, currency=plan.currency),
            coupon_terms(db, coupon, user) if coupon is not None else None,
            now,
        )
        # Al cotizar, un cupon que no aplica no es un error. Al pagar si: cobrar
        # el precio completo a quien escribio un codigo seria una sorpresa.
        if quote.coupon_rejection is not None:
            raise _coupon_rejected(quote.coupon_rejection)
        subtotal, discount, currency = quote.subtotal_cents, quote.discount_cents, quote.currency

        if subscription is None:
            subscription = Subscription(
                user_id=user.id, provider=provider.name, status="pending", renewal_mode="manual"
            )
            db.add(subscription)
        if subscription.status == "pending":
            # Una suscripcion que nunca se pago se reutiliza con lo que se eligio
            # ahora. Una que ya vencio no se toca hasta que el pago se apruebe.
            subscription.plan_id = plan.id
            subscription.provider = provider.name
            subscription.price_cents = subtotal
            subscription.currency = currency
            subscription.coupon_id = coupon.id if coupon is not None else None
        db.flush()

    payment = Payment(
        subscription_id=subscription.id,
        user_id=user.id,
        plan_id=plan.id,
        coupon_id=coupon.id if coupon is not None else None,
        provider=provider.name,
        # Una referencia nueva por intento: Wompi rechaza una repetida.
        reference=f"SA-{uuid.uuid4().hex}",
        kind=kind,
        amount_cents=subtotal - discount,
        currency=currency,
        discount_cents=discount,
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return StartedPayment(payment=payment, subtotal_cents=subtotal)


def _coupon_rejected(reason: CouponRejection) -> SubscribeError:
    return SubscribeError(
        400, "coupon_rejected", COUPON_MESSAGES[reason], coupon_reason=reason
    )


# Lo que se le dice al cliente por cada motivo. Ninguno promete nada.
COUPON_MESSAGES: dict[CouponRejection, str] = {
    CouponRejection.not_found: "Ese código no existe.",
    CouponRejection.inactive: "Ese cupón ya no está disponible.",
    CouponRejection.not_started: "Ese cupón todavía no está vigente.",
    CouponRejection.expired: "Ese cupón ya venció.",
    CouponRejection.exhausted: "Ese cupón ya no tiene cupos.",
    CouponRejection.other_plan: "Ese cupón no aplica a este plan.",
    CouponRejection.currency_mismatch: "Ese cupón no aplica a la moneda de este plan.",
    CouponRejection.already_used: "Ya usaste ese cupón.",
    CouponRejection.covers_total: "Ese cupón no se puede usar con este plan.",
}


def apply_transaction(db: Session, transaction: ProviderTransaction, now: datetime) -> Settlement | None:
    """Aplica al pago lo que el proveedor reporta de su transaccion. Hace commit.

    `transaction` debe venir de `PaymentProvider.fetch_transaction`. Devuelve
    None si la referencia no es de ningun pago nuestro.
    """
    payment = db.scalar(
        select(Payment).where(Payment.reference == transaction.reference).with_for_update()
    )
    if payment is None:
        db.rollback()
        return None
    # Idempotencia: un pago resuelto no se vuelve a tocar.
    if payment.status != "pending":
        db.rollback()
        return Settlement(payment=payment)

    payment.provider_transaction_id = transaction.id
    if transaction.status == "pending":
        db.commit()
        return Settlement(payment=payment)

    payment.resolved_at = now
    activated = False
    if transaction.status != "approved":
        payment.status = transaction.status
        payment.failure_reason = transaction.status_message
    elif (transaction.amount_cents, transaction.currency) != (
        payment.amount_cents,
        payment.currency,
    ):
        # Aprobada, pero por un monto que no es el que se pidio cobrar: no se
        # concede nada y alguien tiene que mirarlo.
        payment.status = "error"
        payment.failure_reason = (
            f"El proveedor reporta {transaction.amount_cents} {transaction.currency}; "
            f"se esperaban {payment.amount_cents} {payment.currency}"
        )
        logger.error("Pago %s: monto o moneda no coinciden con la transaccion", payment.id)
    else:
        payment.status = "approved"
        activated = _grant_period(db, payment, now)
    db.commit()
    db.refresh(payment)
    return Settlement(payment=payment, changed=True, activated=activated)


def _grant_period(db: Session, payment: Payment, now: datetime) -> bool:
    """El pago aprobado activa la suscripcion y fija hasta cuando vale.

    Devuelve si la suscripcion se activo por primera vez.
    """
    subscription = (
        db.scalar(
            select(Subscription)
            .where(Subscription.id == payment.subscription_id)
            .with_for_update()
        )
        if payment.subscription_id is not None
        else None
    )
    if subscription is None or payment.user_id is None:
        # La cuenta se elimino con el pago en curso. Queda aprobado, sin a quien
        # darle el periodo.
        logger.error("Pago %s aprobado sin suscripcion a la cual aplicarlo", payment.id)
        return False

    # Un pago viejo de una suscripcion que ya no es la de la cuenta extiende la
    # que si lo es, para no chocar con "una sola suscripcion viva".
    if subscription.status not in LIVE_SUBSCRIPTION_STATUSES:
        subscription = live_subscription(db, payment.user_id) or subscription
    # Tambien cuenta como activacion volver despues de vencido: es un alta
    # nueva, con el plan y el precio de ese pago.
    first_activation = (
        subscription.status == "pending"
        or subscription.current_period_end is None
        or (payment.kind == "initial" and subscription.current_period_end <= now)
    )

    paid_until = db.scalar(
        select(Subscription.current_period_end)
        .where(
            Subscription.user_id == payment.user_id,
            Subscription.status.in_(_STATUSES_WITH_PAID_PERIOD),
            Subscription.current_period_end.is_not(None),
        )
        .order_by(Subscription.current_period_end.desc())
        .limit(1)
    )
    plan = payment.plan
    period = next_period(now, paid_until, plan.interval, plan.interval_count)  # type: ignore[arg-type]
    payment.period_start, payment.period_end = period.start, period.end

    coupon = db.get(Coupon, payment.coupon_id) if payment.coupon_id is not None else None
    if first_activation:
        # Lo que se compro lo dice el pago aprobado, no el ultimo boton pulsado.
        subscription.plan_id = payment.plan_id
        subscription.price_cents = payment.amount_cents + payment.discount_cents
        subscription.currency = payment.currency
        subscription.coupon_id = payment.coupon_id
        subscription.discount_periods_remaining = _discount_periods_after_first(coupon)
        subscription.current_period_start = period.start
    elif subscription.current_period_end is None or subscription.current_period_end <= now:
        subscription.current_period_start = period.start
    subscription.status = "active"
    subscription.current_period_end = period.end
    subscription.cancel_at_period_end = False
    subscription.canceled_at = None

    if coupon is not None:
        _redeem_coupon(db, coupon, payment.user_id, subscription.id)
    return first_activation


def _discount_periods_after_first(coupon: Coupon | None) -> int | None:
    """Periodos con descuento que quedan despues del primero, ya cobrado."""
    if coupon is None or coupon.duration == "forever":
        return None
    if coupon.duration == "repeating":
        return max((coupon.duration_periods or 1) - 1, 0)
    return 0


def _redeem_coupon(
    db: Session, coupon: Coupon, user_id: uuid.UUID, subscription_id: uuid.UUID
) -> None:
    """Una sola redencion por cuenta, y el contador sube con ella."""
    already = db.scalar(
        select(CouponRedemption.id).where(
            CouponRedemption.coupon_id == coupon.id, CouponRedemption.user_id == user_id
        )
    )
    if already is not None:
        return
    db.add(
        CouponRedemption(coupon_id=coupon.id, user_id=user_id, subscription_id=subscription_id)
    )
    # En SQL y no en Python: dos pagos aprobados a la vez no pierden una cuenta.
    db.execute(
        update(Coupon)
        .where(Coupon.id == coupon.id)
        .values(redemptions_count=Coupon.redemptions_count + 1)
    )
