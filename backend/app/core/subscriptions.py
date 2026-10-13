"""Suscripciones y pagos (docs/PLATAFORMA_COMPLETA.md §3.4 a §3.6 y §3.10).

Operaciones:

- `start_payment`: abre el pago de un periodo, manual (el cliente paga en la
  pagina del proveedor) o con un medio de pago guardado (renovacion
  automatica). El monto sale siempre de `billing/pricing`; nunca de lo que
  mande el cliente.
- `apply_transaction`: la UNICA funcion que mueve un pago y su suscripcion. La
  usan el webhook, la consulta del estado del pago y el job de renovaciones, y
  siempre con una transaccion que salio de la API del proveedor
  (`fetch_transaction` o la respuesta de `charge`), no del cuerpo de un evento.
  Es idempotente: un pago se resuelve una sola vez, asi lleguen el mismo evento
  repetido, dos eventos distintos o el webhook y la consulta a la vez.
- `cancel` y `resume`: detener y reanudar la renovacion automatica.

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
from app.billing.schedule import first_charge_at
from app.core import legal
from app.core.access import has_access
from app.models import Coupon, CouponRedemption, Payment, Plan, Subscription, User
from app.models.user import LIVE_SUBSCRIPTION_STATUSES
from app.payments.base import (
    PAYMENT_SOURCE_TYPES,
    PaymentProvider,
    PaymentProviderError,
    PaymentSource,
    PaymentSourceRejected,
    PaymentSourceType,
    ProviderTransaction,
)

logger = logging.getLogger(__name__)

# Con estos estados la suscripcion tiene un periodo pagado que cuenta.
_STATUSES_WITH_PAID_PERIOD = ("active", "canceled", "past_due")
# Accesos que no salen de una suscripcion: a esas cuentas no se les cobra.
_ACCESS_WITHOUT_SUBSCRIPTION = ("admin", "full", "invited")

#: Lo que queda en `failure_reason` cuando el proveedor no contesto al cobrar.
#: Un pago en ese estado todavia se puede resolver si despues llega su evento.
NO_PROVIDER_RESPONSE = "El proveedor no respondió al iniciar el cobro"


class SubscribeError(Exception):
    """Por que no se pudo completar la operacion. `code` viaja al cliente."""

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
class SourceInput:
    """El medio de pago que el cliente tokenizo en su navegador, con los dos
    contratos del proveedor que acepto. Nunca trae datos de tarjeta."""

    type: str
    token: str
    acceptance_token: str
    personal_data_token: str


@dataclass(frozen=True)
class Settlement:
    """Lo que paso al aplicar una transaccion a un pago."""

    payment: Payment
    #: Esta llamada resolvio el pago. False si ya estaba resuelto o sigue pendiente.
    changed: bool = False
    #: Esta llamada activo la suscripcion (alta, o volver despues de vencida).
    activated: bool = False
    #: Esta llamada dejo un cobro automatico de renovacion sin aprobar.
    renewal_failed: bool = False


@dataclass(frozen=True)
class StartedPayment:
    payment: Payment
    subtotal_cents: int
    #: Solo en el alta con medio de pago guardado: lo que respondio el cobro.
    settlement: Settlement | None = None


def live_subscription(db: Session, user_id: uuid.UUID) -> Subscription | None:
    """La suscripcion pendiente, activa o en mora de la cuenta. Hay a lo sumo una."""
    return db.scalar(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        )
    )


def current_subscription(db: Session, user_id: uuid.UUID) -> Subscription | None:
    """La suscripcion que se le muestra a la cuenta: la del periodo pagado mas
    reciente, vigente o no. Una que nunca se pago (`pending`) no cuenta."""
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status.in_((*_STATUSES_WITH_PAID_PERIOD, "expired")),
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


def renewal_discount(db: Session, subscription: Subscription) -> pricing.RenewalDiscount | None:
    """El descuento que la suscripcion todavia lleva, para `pricing.renewal_quote`."""
    if subscription.coupon_id is None:
        return None
    coupon = db.get(Coupon, subscription.coupon_id)
    if coupon is None:
        return None
    return pricing.RenewalDiscount(
        kind=pricing.CouponKind(coupon.kind),
        value=coupon.value,
        currency=coupon.currency,
        periods_remaining=subscription.discount_periods_remaining,
    )


def in_force(subscription: Subscription, now: datetime) -> bool:
    """Tiene un periodo pagado que todavia no vence."""
    return (
        subscription.status in _STATUSES_WITH_PAID_PERIOD
        and subscription.current_period_end is not None
        and subscription.current_period_end > now
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


def _check_source(provider: PaymentProvider, source: SourceInput | None) -> SourceInput:
    if provider.tokenizer() is None:
        raise SubscribeError(
            503, "automatic_unavailable", "La renovación automática todavía no está disponible."
        )
    if source is None or not source.token.strip():
        raise SubscribeError(
            400, "payment_source_required", "Falta el medio de pago para la renovación automática."
        )
    if source.type not in PAYMENT_SOURCE_TYPES:
        raise SubscribeError(
            400,
            "payment_source_type_not_supported",
            "Ese medio de pago no se puede guardar para la renovación automática.",
        )
    if not source.acceptance_token.strip() or not source.personal_data_token.strip():
        raise SubscribeError(
            400,
            "acceptance_required",
            "Debes aceptar los términos del procesador de pagos para guardar tu medio de pago.",
        )
    return source


def start_payment(
    db: Session,
    *,
    user: User,
    plan_id: uuid.UUID,
    coupon_code: str | None,
    provider: PaymentProvider,
    now: datetime,
    renewal_mode: str = "manual",
    source: SourceInput | None = None,
) -> StartedPayment:
    """Abre el pago de un periodo y lo confirma en la base.

    Sin una suscripcion vigente es el alta: precio del plan menos el cupon, si
    aplica. Con `renewal_mode="automatic"` guarda el medio de pago en el
    proveedor y le hace el primer cobro; con `manual`, el cliente paga en la
    pagina del proveedor.

    Con una suscripcion vigente de pago manual, es el pago del periodo
    siguiente del mismo plan: precio congelado, con el descuento que todavia
    lleve la suscripcion.
    """
    if not provider.enabled:
        raise SubscribeError(503, "payments_unavailable", "El pago todavía no está disponible.")
    _check_can_pay(db, user, now)
    automatic = renewal_mode == "automatic"
    if automatic:
        source = _check_source(provider, source)

    # Serializa los intentos simultaneos de la misma cuenta.
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    subscription = live_subscription(db, user.id)
    code = normalize_code(coupon_code or "")

    if (
        subscription is not None
        and subscription.status != "pending"
        and not in_force(subscription, now)
    ):
        # Su periodo ya termino: es lo mismo que haria el job de renovaciones.
        # Lo que sigue es un alta nueva.
        subscription.status = "expired"
        subscription.next_charge_at = None
        db.flush()
        subscription = None

    stored: PaymentSource | None = None
    if subscription is not None and subscription.status != "pending":
        # Periodo siguiente de una suscripcion pagada y todavia vigente.
        if subscription.renewal_mode == "automatic":
            raise SubscribeError(
                409,
                "renews_automatically",
                "Tu suscripción se renueva sola: no hace falta pagar el siguiente período.",
            )
        if automatic:
            raise SubscribeError(
                409,
                "mode_change_not_available",
                "Todavía no se puede pasar a renovación automática con un período ya pagado.",
            )
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
        quote = pricing.renewal_quote(
            subscription.price_cents, subscription.currency, renewal_discount(db, subscription)
        )
        coupon_id = subscription.coupon_id if quote.discount_cents > 0 else None
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
        coupon_id = coupon.id if coupon is not None else None

        if automatic and source is not None:
            # Antes de escribir nada: si el proveedor no acepta el medio de
            # pago, no queda ni suscripcion ni pago.
            stored = _store_source(provider, source, user)

        if subscription is None:
            subscription = Subscription(user_id=user.id, status="pending")
            db.add(subscription)
        # Una suscripcion que nunca se pago se reutiliza con lo que se eligio ahora.
        subscription.plan_id = plan.id
        subscription.provider = provider.name
        subscription.price_cents = quote.subtotal_cents
        subscription.currency = quote.currency
        subscription.coupon_id = coupon_id
        subscription.renewal_mode = "automatic" if automatic else "manual"
        subscription.payment_source_id = stored.id if stored else None
        subscription.payment_source_type = stored.type if stored else None
        subscription.card_brand = stored.brand if stored else None
        subscription.card_last4 = stored.last4 if stored else None
        db.flush()

    payment = Payment(
        subscription_id=subscription.id,
        user_id=user.id,
        plan_id=plan.id,
        coupon_id=coupon_id,
        provider=provider.name,
        # Una referencia nueva por intento: Wompi rechaza una repetida.
        reference=f"SA-{uuid.uuid4().hex}",
        kind=kind,
        amount_cents=quote.total_cents,
        currency=quote.currency,
        discount_cents=quote.discount_cents,
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    settlement: Settlement | None = None
    if stored is not None:
        settlement = charge_payment(db, provider, payment, stored, user.email, now)
        if settlement is None:
            raise SubscribeError(
                502,
                "provider_unavailable",
                "No pudimos iniciar el cobro. Intenta de nuevo en unos minutos.",
            )
        payment = settlement.payment
    return StartedPayment(
        payment=payment, subtotal_cents=quote.subtotal_cents, settlement=settlement
    )


def _store_source(provider: PaymentProvider, source: SourceInput, user: User) -> PaymentSource:
    try:
        return provider.create_payment_source(
            source_type=_source_type(source.type),
            token=source.token.strip(),
            customer_email=user.email,
            acceptance_token=source.acceptance_token.strip(),
            personal_data_token=source.personal_data_token.strip(),
        )
    except PaymentSourceRejected as exc:
        raise SubscribeError(
            400,
            "payment_source_rejected",
            "El procesador de pagos no aceptó ese medio de pago. Intenta de nuevo o usa otro.",
        ) from exc
    except PaymentProviderError as exc:
        raise SubscribeError(
            502,
            "provider_unavailable",
            "No pudimos guardar tu medio de pago. Intenta de nuevo en unos minutos.",
        ) from exc


def _source_type(value: str) -> PaymentSourceType:
    for known in PAYMENT_SOURCE_TYPES:
        if value == known:
            return known
    raise ValueError(f"Medio de pago no soportado: {value}")


def source_of(subscription: Subscription) -> PaymentSource | None:
    """El medio de pago guardado de la suscripcion, como lo espera el proveedor."""
    if subscription.payment_source_id is None or subscription.payment_source_type is None:
        return None
    return PaymentSource(
        id=subscription.payment_source_id,
        type=_source_type(subscription.payment_source_type),
        brand=subscription.card_brand,
        last4=subscription.card_last4,
    )


def charge_payment(
    db: Session,
    provider: PaymentProvider,
    payment: Payment,
    source: PaymentSource,
    customer_email: str,
    now: datetime,
) -> Settlement | None:
    """Cobra un pago ya guardado a un medio de pago y aplica lo que responda el
    proveedor. Devuelve None si el proveedor no contesto: el pago queda en
    `error`, sin transaccion, y todavia lo puede resolver un evento posterior.
    """
    try:
        transaction = provider.charge(
            reference=payment.reference,
            amount_cents=payment.amount_cents,
            currency=payment.currency,
            customer_email=customer_email,
            source=source,
        )
    except PaymentProviderError:
        logger.warning("El proveedor no respondio al cobrar el pago %s", payment.id)
        payment.status = "error"
        payment.failure_reason = NO_PROVIDER_RESPONSE
        payment.resolved_at = now
        db.commit()
        return None
    return apply_transaction(db, transaction, now)


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


def _resolvable(payment: Payment) -> bool:
    """Un pago que todavia admite la respuesta del proveedor.

    El que quedo en `error` porque el proveedor no contesto al cobrar tambien:
    si el cobro si llego a hacerse, su evento lo dira despues.
    """
    return payment.status == "pending" or (
        payment.status == "error" and payment.provider_transaction_id is None
    )


def apply_transaction(db: Session, transaction: ProviderTransaction, now: datetime) -> Settlement | None:
    """Aplica al pago lo que el proveedor reporta de su transaccion. Hace commit.

    `transaction` debe venir de la API del proveedor (`fetch_transaction` o la
    respuesta de `charge`). Devuelve None si la referencia no es de ningun pago
    nuestro.
    """
    payment = db.scalar(
        select(Payment).where(Payment.reference == transaction.reference).with_for_update()
    )
    if payment is None:
        db.rollback()
        return None
    # Idempotencia: un pago resuelto no se vuelve a tocar.
    if not _resolvable(payment):
        db.rollback()
        return Settlement(payment=payment)

    payment.provider_transaction_id = transaction.id
    if transaction.status == "pending":
        payment.status = "pending"
        payment.failure_reason = None
        payment.resolved_at = None
        db.commit()
        return Settlement(payment=payment)

    payment.resolved_at = now
    activated = False
    renewal_failed = False
    if transaction.status != "approved":
        payment.status = transaction.status
        payment.failure_reason = transaction.status_message
        renewal_failed = _note_failed_renewal(db, payment)
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
        payment.failure_reason = None
        activated = _grant_period(db, payment, now)
    db.commit()
    db.refresh(payment)
    return Settlement(
        payment=payment, changed=True, activated=activated, renewal_failed=renewal_failed
    )


def _note_failed_renewal(db: Session, payment: Payment) -> bool:
    """Un cobro automatico de renovacion que no se aprobo deja la suscripcion
    en mora (§3.5). El acceso no cambia: el periodo pagado sigue corriendo."""
    if payment.kind != "renewal" or payment.subscription_id is None:
        return False
    subscription = db.scalar(
        select(Subscription).where(Subscription.id == payment.subscription_id).with_for_update()
    )
    if (
        subscription is None
        or subscription.renewal_mode != "automatic"
        or subscription.status not in ("active", "past_due")
    ):
        return False
    subscription.status = "past_due"
    subscription.retry_count += 1
    return True


def _grant_period(db: Session, payment: Payment, now: datetime) -> bool:
    """El pago aprobado activa la suscripcion y fija hasta cuando vale.

    Devuelve si la suscripcion se activo (alta, o volver despues de vencida).
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
    first_activation = subscription.status == "pending" or subscription.current_period_end is None

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
    else:
        if subscription.current_period_end is None or subscription.current_period_end <= now:
            subscription.current_period_start = period.start
        if payment.kind == "renewal":
            # Cada renovacion aprobada gasta un periodo con descuento (§3.5).
            subscription.discount_periods_remaining = pricing.periods_remaining_after_renewal(
                subscription.discount_periods_remaining
            )
    subscription.current_period_end = period.end
    subscription.retry_count = 0
    if subscription.cancel_at_period_end:
        # El cliente cancelo la renovacion con un cobro ya en curso: el periodo
        # que se cobro se le da, pero la cancelacion se respeta.
        subscription.status = "canceled"
        subscription.next_charge_at = None
    else:
        subscription.status = "active"
        subscription.canceled_at = None
        subscription.next_charge_at = (
            first_charge_at(period.end) if subscription.renewal_mode == "automatic" else None
        )

    if coupon is not None and first_activation:
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


# ---------- Cancelar y reanudar la renovacion automatica (§3.6) ----------


def cancel(db: Session, user: User, now: datetime) -> Subscription:
    """Detiene la renovacion automatica. Conserva el acceso hasta
    `current_period_end`; el job no vuelve a cobrar. Hace commit."""
    subscription = db.scalar(
        select(Subscription)
        .where(
            Subscription.user_id == user.id, Subscription.status.in_(("active", "past_due"))
        )
        .with_for_update()
    )
    if subscription is None or not in_force(subscription, now):
        raise SubscribeError(
            409, "nothing_to_cancel", "No tienes una suscripción vigente que cancelar."
        )
    if subscription.renewal_mode != "automatic":
        raise SubscribeError(
            409,
            "not_automatic",
            "Tu suscripción es de pago manual: no se renueva sola, así que no hay nada que cancelar.",
        )
    subscription.status = "canceled"
    subscription.cancel_at_period_end = True
    subscription.canceled_at = now
    subscription.next_charge_at = None
    db.commit()
    db.refresh(subscription)
    return subscription


def resume(db: Session, user: User, now: datetime) -> Subscription:
    """Revierte la cancelacion antes del vencimiento. Hace commit."""
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    subscription = db.scalar(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "canceled")
        .order_by(Subscription.current_period_end.desc())
        .limit(1)
        .with_for_update()
    )
    if subscription is None or not in_force(subscription, now):
        raise SubscribeError(
            409, "nothing_to_resume", "No tienes una suscripción cancelada que reanudar."
        )
    if source_of(subscription) is None:
        raise SubscribeError(
            409, "no_payment_source", "La suscripción no tiene un medio de pago guardado."
        )
    # Si despues de cancelar abrio otro pago sin completarlo, esa suscripcion
    # pendiente estorba ("una sola viva") y ya no hace falta.
    other = live_subscription(db, user.id)
    if other is not None:
        if other.status != "pending":
            raise SubscribeError(
                409, "other_subscription", "Ya tienes otra suscripción activa."
            )
        db.delete(other)
        db.flush()
    subscription.status = "active"
    subscription.cancel_at_period_end = False
    subscription.canceled_at = None
    subscription.retry_count = 0
    assert subscription.current_period_end is not None
    subscription.next_charge_at = first_charge_at(subscription.current_period_end)
    db.commit()
    db.refresh(subscription)
    return subscription
