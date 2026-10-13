"""Job de renovaciones (docs/PLATAFORMA_COMPLETA.md §3.5 y §3.8).

Lo corre `scripts/run_renewals.py` cada hora. Una corrida:

1. Suscripciones de renovacion automatica: resuelve los cobros que quedaron sin
   respuesta, avisa por correo antes del primer cobro, hace el intento que
   toque (48 h, 24 h y 0 h antes del vencimiento) y, agotados los tres, la deja
   vencida.
2. Suscripciones de pago manual: avisa que el periodo esta por vencer y, si
   vencio sin pagar, la deja vencida.
3. Suscripciones canceladas cuyo periodo termino: quedan vencidas.

Cuando toca cada cosa lo decide `billing/schedule.py` (puro). Un cobro y su
suscripcion solo los mueve `core/subscriptions.apply_transaction`.

Idempotencia, en dos capas:

- El job no corre en paralelo consigo mismo: `advisory_lock` toma un candado de
  Postgres y la segunda corrida sale sin hacer nada.
- Cada intento de cobro lleva una `reference` derivada de (suscripcion, periodo,
  numero de intento). `payments.reference` es unica: si dos corridas llegaran a
  intentar lo mismo, la segunda choca con la restriccion en vez de cobrar.

Aqui no se decide el acceso: eso es de `core/access.has_access`.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing import pricing, schedule
from app.core import billing_emails, subscriptions
from app.core.email import EmailMessage
from app.models import Payment, Subscription, User
from app.payments.base import PaymentProvider, PaymentProviderError

logger = logging.getLogger(__name__)

# Llave del candado de Postgres del job. Un numero cualquiera, fijo.
ADVISORY_LOCK_KEY = 5_005_202_610

# Un cobro guardado al que nunca se le llego a anotar la transaccion (el proceso
# murio entre guardar el pago y cobrar) se da por perdido pasado este tiempo.
ORPHAN_AFTER = timedelta(hours=1)


@dataclass
class RenewalReport:
    """Lo que hizo una corrida. Va al log."""

    notices: int = 0
    charges: int = 0
    approved: int = 0
    failed: int = 0
    expired: int = 0
    errors: int = 0
    #: Los correos que hay que enviar. El job los envia despues de confirmar.
    emails: list[EmailMessage] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"avisos={self.notices} cobros={self.charges} aprobados={self.approved} "
            f"fallidos={self.failed} vencidas={self.expired} errores={self.errors}"
        )


@contextmanager
def advisory_lock(engine: Engine) -> Iterator[bool]:
    """Candado del job. Entrega False si otra corrida lo tiene.

    Usa su propia conexion durante toda la corrida: el candado de Postgres es
    de la conexion, y la sesion del job cambia de conexion en cada commit.
    """
    with engine.connect() as conn:
        acquired = bool(
            conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY}
            ).scalar()
        )
        conn.commit()
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
                conn.commit()


def renewal_reference(subscription: Subscription, period_end: datetime, attempt: int) -> str:
    """La referencia del intento `attempt` del cobro del periodo que sigue a
    `period_end`. Es la misma en cualquier corrida: de ahi la idempotencia."""
    return f"{_reference_prefix(subscription, period_end)}{attempt}"


def _reference_prefix(subscription: Subscription, period_end: datetime) -> str:
    return f"SA-R-{subscription.id.hex}-{int(period_end.timestamp())}-"


def run_renewals(db: Session, provider: PaymentProvider, now: datetime) -> RenewalReport:
    """Una corrida del job. Quien llama debe tener el candado (`advisory_lock`)."""
    report = RenewalReport()
    ids = list(
        db.scalars(
            select(Subscription.id)
            .where(
                Subscription.status.in_(("active", "past_due", "canceled")),
                Subscription.current_period_end.is_not(None),
            )
            .order_by(Subscription.current_period_end)
        )
    )
    for subscription_id in ids:
        try:
            _process(db, provider, subscription_id, now, report)
        except Exception:
            # Una suscripcion con problemas no detiene a las demas.
            db.rollback()
            report.errors += 1
            logger.exception("Renovaciones: fallo la suscripcion %s", subscription_id)
    return report


def _process(
    db: Session,
    provider: PaymentProvider,
    subscription_id: object,
    now: datetime,
    report: RenewalReport,
) -> None:
    subscription = db.get(Subscription, subscription_id)
    if subscription is None or subscription.current_period_end is None:
        return
    user = db.get(User, subscription.user_id)
    if user is None:
        return

    if subscription.status == "canceled":
        # No se le cobra ni se le avisa: solo vence cuando termina lo que pago.
        if subscription.current_period_end <= now:
            _expire(db, subscription)
            report.expired += 1
        return

    if subscription.renewal_mode == "automatic" and provider.enabled:
        _process_automatic(db, provider, subscription, user, now, report)
    else:
        _process_manual(db, subscription, user, now, report)


def _process_manual(
    db: Session, subscription: Subscription, user: User, now: datetime, report: RenewalReport
) -> None:
    period_end = subscription.current_period_end
    assert period_end is not None
    if period_end <= now:
        message = billing_emails.subscription_expired(user, subscription, automatic=False)
        _expire(db, subscription)
        report.expired += 1
        report.emails.append(message)
        return
    if schedule.expiry_notice_due(now, period_end) and subscription.notice_sent_for != period_end:
        amount = _renewal_quote(db, subscription).total_cents
        message = billing_emails.period_ending(user, subscription, amount)
        subscription.notice_sent_for = period_end
        db.commit()
        report.notices += 1
        report.emails.append(message)


def _process_automatic(
    db: Session,
    provider: PaymentProvider,
    subscription: Subscription,
    user: User,
    now: datetime,
    report: RenewalReport,
) -> None:
    period_end = subscription.current_period_end
    assert period_end is not None
    prefix = _reference_prefix(subscription, period_end)

    # 1. Cobros de este periodo que quedaron sin resolver: se reconsultan.
    for payment in _attempts(db, prefix):
        if payment.status == "pending":
            _settle_in_flight(db, provider, payment, now, report)
    db.refresh(subscription)
    if subscription.current_period_end != period_end or subscription.status == "canceled":
        # Uno de esos cobros se aprobo y el periodo ya avanzo.
        return

    attempts = _attempts(db, prefix)
    in_flight = any(p.status == "pending" for p in attempts)

    # 2. El aviso va ANTES del primer intento (§3.8), una vez por periodo. Si
    #    todavia no ha salido, esta corrida avisa y no cobra: el cobro queda
    #    para la siguiente.
    if not attempts and subscription.notice_sent_for != period_end:
        if schedule.renewal_notice_due(now, period_end):
            quote = _renewal_quote(db, subscription)
            charge_at = max(schedule.first_charge_at(period_end), now)
            message = billing_emails.renewal_notice(
                user, subscription, quote.total_cents, charge_at
            )
            subscription.notice_sent_for = period_end
            db.commit()
            report.notices += 1
            report.emails.append(message)
        return

    # 3. El intento que toque.
    attempt = None if in_flight else schedule.next_attempt(now, period_end, len(attempts))
    if attempt is not None:
        _charge(db, provider, subscription, user, period_end, attempt, now, report)
        db.refresh(subscription)
        if subscription.current_period_end != period_end:
            return
        attempts = _attempts(db, prefix)
        in_flight = any(p.status == "pending" for p in attempts)

    # 4. Agotados los intentos y terminado el periodo: vence, sin gracia.
    if schedule.should_expire(now, period_end, len(attempts), attempt_in_flight=in_flight):
        message = billing_emails.subscription_expired(user, subscription, automatic=True)
        _expire(db, subscription)
        report.expired += 1
        report.emails.append(message)


def _attempts(db: Session, prefix: str) -> list[Payment]:
    db.expire_all()
    return list(
        db.scalars(
            select(Payment)
            .where(Payment.reference.like(f"{prefix}%"))
            .order_by(Payment.created_at, Payment.reference)
        )
    )


def _renewal_quote(db: Session, subscription: Subscription) -> pricing.Quote:
    return pricing.renewal_quote(
        subscription.price_cents,
        subscription.currency,
        subscriptions.renewal_discount(db, subscription),
    )


def _settle_in_flight(
    db: Session, provider: PaymentProvider, payment: Payment, now: datetime, report: RenewalReport
) -> None:
    if payment.provider_transaction_id is None:
        # Se guardo el pago y nunca se anoto su transaccion. Si de verdad se
        # cobro, el evento del proveedor todavia puede resolverlo.
        if payment.created_at <= now - ORPHAN_AFTER:
            payment.status = "error"
            payment.failure_reason = subscriptions.NO_PROVIDER_RESPONSE
            payment.resolved_at = now
            db.commit()
        return
    try:
        transaction = provider.fetch_transaction(payment.provider_transaction_id)
    except PaymentProviderError:
        logger.warning("Renovaciones: no se pudo reconsultar el pago %s", payment.id)
        return
    if transaction is not None:
        _count(db, subscriptions.apply_transaction(db, transaction, now), report)


def _charge(
    db: Session,
    provider: PaymentProvider,
    subscription: Subscription,
    user: User,
    period_end: datetime,
    attempt: int,
    now: datetime,
    report: RenewalReport,
) -> None:
    source = subscriptions.source_of(subscription)
    if source is None:
        logger.error("Renovaciones: la suscripcion %s no tiene medio de pago", subscription.id)
        return
    quote = _renewal_quote(db, subscription)
    payment = Payment(
        subscription_id=subscription.id,
        user_id=user.id,
        plan_id=subscription.plan_id,
        coupon_id=subscription.coupon_id if quote.discount_cents > 0 else None,
        provider=provider.name,
        reference=renewal_reference(subscription, period_end, attempt),
        kind="renewal",
        amount_cents=quote.total_cents,
        currency=quote.currency,
        discount_cents=quote.discount_cents,
        status="pending",
    )
    db.add(payment)
    try:
        # El pago se confirma ANTES de cobrar: si otra corrida ya creo este
        # intento, aqui choca con la referencia unica y no se cobra dos veces.
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.warning("Renovaciones: el intento %s ya existia", payment.reference)
        return
    report.charges += 1
    settlement = subscriptions.charge_payment(db, provider, payment, source, user.email, now)
    if settlement is None:
        # El proveedor no contesto. Cuenta como intento hecho; no como rechazo
        # de la tarjeta, asi que no se le escribe al cliente.
        subscription.status = "past_due"
        subscription.retry_count += 1
        db.commit()
        report.failed += 1
        return
    _count(db, settlement, report)


def _count(db: Session, settlement: subscriptions.Settlement | None, report: RenewalReport) -> None:
    if settlement is None or not settlement.changed:
        return
    if settlement.payment.status == "approved":
        report.approved += 1
    else:
        report.failed += 1
    report.emails.extend(billing_emails.payment_emails(db, settlement))


def _expire(db: Session, subscription: Subscription) -> None:
    subscription.status = "expired"
    subscription.next_charge_at = None
    db.commit()
