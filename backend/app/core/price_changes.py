"""Traslado del precio actual de un plan a sus suscripciones vigentes
(docs/PLATAFORMA_COMPLETA.md §4.10 y §10 n.º 5).

El precio congelado de una suscripcion (§3.7) solo cambia por aqui. Decidido
por el usuario el 2026-10-14:

- Alcanza a todas las suscripciones vigentes del plan, en los dos modos de pago,
  cuyo precio congelado sea distinto al del plan. No a las canceladas.
- **Subida**: el precio nuevo se cobra desde 30 dias despues de que a ese
  cliente le llego el aviso. Los avisos los envia el job de renovaciones por
  lotes (`send_notices`), y la fecha se anota solo si el envio salio bien: un
  cliente al que no le llego el correo sigue pagando el precio viejo.
- **Bajada**: aplica al registrar el traslado; el aviso es informativo.
- Un cupon que todavia descuenta sigue descontando sobre el precio nuevo
  (`pricing.renewal_quote` calcula desde `subscriptions.price_cents`).
- Se puede cancelar mientras no se haya aplicado: las suscripciones que faltaban
  conservan su precio, y quien ya habia recibido el aviso recibe otro que dice
  que no cambia.

Cuando aplica cada cosa lo dice `billing/price_change.py` (puro). Aqui no se
toca ningun pago: un pago solo lo mueve `core/subscriptions.apply_transaction`.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.billing import price_change
from app.billing.price_change import Direction, PendingChange
from app.core import audit
from app.core.email import EmailMessage, EmailSender
from app.models import Plan, PriceChange, Subscription, SubscriptionPriceChange, User

logger = logging.getLogger(__name__)

#: Cuantos avisos envia una corrida del job, como mucho. El job corre cada hora
#: y el tope diario de correos (`EMAIL_DAILY_LIMIT`) es de 300 por defecto: con
#: 40 por hora quedan cupos para los demas correos del dia.
NOTICES_PER_RUN = 40

# Las que reciben el traslado y su aviso de subida.
_RENEWING = ("active", "past_due")
# Las que tienen un periodo pagado (las canceladas tambien).
_PAID = ("active", "past_due", "canceled")


class PriceChangeError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class Preview:
    """Lo que haria un traslado del precio actual del plan, ahora."""

    increases: int
    decreases: int
    open_change: PriceChange | None


@dataclass(frozen=True)
class Progress:
    total: int
    applied: int
    notified: int
    waiting_notice: int
    canceled: int


def _eligible(db: Session, plan: Plan, now: datetime) -> list[Subscription]:
    return list(
        db.scalars(
            select(Subscription)
            .where(
                Subscription.plan_id == plan.id,
                Subscription.status.in_(_RENEWING),
                Subscription.current_period_end > now,
                Subscription.currency == plan.currency,
                Subscription.price_cents != plan.price_cents,
            )
            .order_by(Subscription.created_at, Subscription.id)
        )
    )


def open_change(db: Session, plan_id: uuid.UUID) -> PriceChange | None:
    """El traslado del plan que todavia tiene suscripciones sin aplicar."""
    return db.scalar(
        select(PriceChange)
        .where(
            PriceChange.plan_id == plan_id,
            PriceChange.canceled_at.is_(None),
            select(SubscriptionPriceChange.id)
            .where(
                SubscriptionPriceChange.price_change_id == PriceChange.id,
                SubscriptionPriceChange.applied_at.is_(None),
                SubscriptionPriceChange.canceled_at.is_(None),
            )
            .exists(),
        )
        .order_by(PriceChange.created_at.desc())
        .limit(1)
    )


def preview(db: Session, plan: Plan, now: datetime) -> Preview:
    subscriptions = _eligible(db, plan, now)
    increases = sum(1 for s in subscriptions if s.price_cents < plan.price_cents)
    return Preview(
        increases=increases,
        decreases=len(subscriptions) - increases,
        open_change=open_change(db, plan.id),
    )


def progress(db: Session, change: PriceChange) -> Progress:
    rows = list(
        db.scalars(
            select(SubscriptionPriceChange).where(
                SubscriptionPriceChange.price_change_id == change.id
            )
        )
    )
    return Progress(
        total=len(rows),
        applied=sum(1 for r in rows if r.applied_at is not None),
        notified=sum(1 for r in rows if r.notice_sent_at is not None),
        waiting_notice=sum(
            1 for r in rows if r.notice_sent_at is None and r.canceled_at is None
        ),
        canceled=sum(1 for r in rows if r.canceled_at is not None),
    )


def create(
    db: Session, *, admin: User, plan: Plan, reason: str, ip: str | None, now: datetime
) -> PriceChange:
    """Registra el traslado del precio actual del plan. Hace commit."""
    # Serializa dos traslados del mismo plan a la vez.
    db.execute(select(Plan.id).where(Plan.id == plan.id).with_for_update())
    if open_change(db, plan.id) is not None:
        raise PriceChangeError(
            409,
            "Este plan ya tiene un traslado de precio en curso. Cancélalo antes de registrar otro.",
        )
    subscriptions = _eligible(db, plan, now)
    if not subscriptions:
        raise PriceChangeError(
            409, "Ninguna suscripción vigente de este plan tiene un precio distinto al actual."
        )

    change = PriceChange(
        plan_id=plan.id,
        new_price_cents=plan.price_cents,
        currency=plan.currency,
        reason=reason,
        created_by=admin.id,
        created_by_email=admin.email,
    )
    db.add(change)
    db.flush()
    increases = decreases = 0
    for subscription in subscriptions:
        row = SubscriptionPriceChange(
            price_change_id=change.id,
            subscription_id=subscription.id,
            old_price_cents=subscription.price_cents,
            new_price_cents=plan.price_cents,
        )
        if price_change.direction(row.old_price_cents, row.new_price_cents) is Direction.decrease:
            # Una bajada aplica ya: desde su proximo cobro o pago.
            row.effective_at = now
            row.applied_at = now
            subscription.price_cents = row.new_price_cents
            decreases += 1
        else:
            increases += 1
        db.add(row)

    audit.record(
        db,
        admin,
        action="plan.price.transfer",
        target_type="plan",
        target_id=plan.id,
        before=None,
        after={
            "price_change_id": str(change.id),
            "new_price_cents": plan.price_cents,
            "currency": plan.currency,
            "increases": increases,
            "decreases": decreases,
        },
        reason=reason,
        ip=ip,
    )
    db.commit()
    db.refresh(change)
    return change


def cancel(
    db: Session, *, admin: User, change: PriceChange, reason: str, ip: str | None, now: datetime
) -> PriceChange:
    """Cancela lo que falta por aplicar de un traslado. Hace commit."""
    rows = list(
        db.scalars(
            select(SubscriptionPriceChange)
            .where(
                SubscriptionPriceChange.price_change_id == change.id,
                SubscriptionPriceChange.applied_at.is_(None),
                SubscriptionPriceChange.canceled_at.is_(None),
            )
            .with_for_update()
        )
    )
    if change.canceled_at is not None or not rows:
        raise PriceChangeError(
            409, "Este traslado ya no tiene nada por aplicar: no hay qué cancelar."
        )
    for row in rows:
        row.canceled_at = now
    change.canceled_at = now
    change.cancel_reason = reason
    audit.record(
        db,
        admin,
        action="plan.price.transfer.cancel",
        target_type="plan",
        target_id=change.plan_id,
        before={"price_change_id": str(change.id), "pending": len(rows)},
        after={
            "price_change_id": str(change.id),
            "pending": 0,
            "notified": sum(1 for r in rows if r.notice_sent_at is not None),
        },
        reason=reason,
        ip=ip,
    )
    db.commit()
    db.refresh(change)
    return change


def pending_for(db: Session, subscription_id: uuid.UUID) -> SubscriptionPriceChange | None:
    """El traslado abierto de la suscripcion, si tiene uno."""
    return db.scalar(
        select(SubscriptionPriceChange).where(
            SubscriptionPriceChange.subscription_id == subscription_id,
            SubscriptionPriceChange.applied_at.is_(None),
            SubscriptionPriceChange.canceled_at.is_(None),
        )
    )


def price_at(db: Session, subscription: Subscription, moment: datetime) -> int:
    """El precio congelado que correra en `moment`, con el traslado abierto
    que ya le aplique para entonces. Para los avisos y la pantalla: el cobro
    usa `price_cents`, que `apply_due` pone al dia antes de cobrar."""
    row = pending_for(db, subscription.id)
    pending = (
        PendingChange(new_price_cents=row.new_price_cents, effective_at=row.effective_at)
        if row is not None
        else None
    )
    return price_change.price_at(subscription.price_cents, pending, moment)


def charge_price(db: Session, subscription: Subscription, first_charge_at: datetime) -> int:
    """El precio de los tres intentos del cobro automatico del periodo cuyo
    primer intento va en `first_charge_at` (y de su aviso): el que corria
    entonces, aunque el job haya aplicado despues una subida (2026-10-15)."""
    row = pending_for(db, subscription.id)
    pending = (
        PendingChange(new_price_cents=row.new_price_cents, effective_at=row.effective_at)
        if row is not None
        else None
    )
    applied = [
        price_change.AppliedChange(
            old_price_cents=r.old_price_cents,
            new_price_cents=r.new_price_cents,
            effective_at=r.effective_at,
        )
        for r in db.scalars(
            select(SubscriptionPriceChange).where(
                SubscriptionPriceChange.subscription_id == subscription.id,
                SubscriptionPriceChange.applied_at.is_not(None),
                SubscriptionPriceChange.effective_at > first_charge_at,
            )
        )
        if r.effective_at is not None
    ]
    return price_change.charge_price(subscription.price_cents, pending, applied, first_charge_at)


def first_charge_with_new_price(
    subscription: Subscription, effective_at: datetime | None
) -> datetime | None:
    """El primer cobro automatico que sale con el precio nuevo. None en el pago
    manual (el precio nuevo corre para los pagos desde `effective_at`) o si
    todavia no se sabe la fecha."""
    period_end = subscription.current_period_end
    if effective_at is None or period_end is None or subscription.renewal_mode != "automatic":
        return None
    plan = subscription.plan
    return price_change.first_charge_with_new_price(
        effective_at,
        period_end,
        plan.interval,  # type: ignore[arg-type]
        plan.interval_count,
    )


def apply_due(db: Session, now: datetime, subscription_id: uuid.UUID | None = None) -> int:
    """Pone en `subscriptions.price_cents` los precios nuevos cuya fecha ya
    llego. No hace commit. Devuelve cuantos aplico.

    Lo llaman el job (antes de cobrar) y quien abre un pago o reintenta un
    cobro, para que ningun cobro salga con un precio que ya no corre.
    """
    query = (
        select(SubscriptionPriceChange)
        .where(
            SubscriptionPriceChange.applied_at.is_(None),
            SubscriptionPriceChange.canceled_at.is_(None),
            SubscriptionPriceChange.effective_at.is_not(None),
            SubscriptionPriceChange.effective_at <= now,
        )
        .with_for_update()
    )
    if subscription_id is not None:
        query = query.where(SubscriptionPriceChange.subscription_id == subscription_id)
    count = 0
    for row in db.scalars(query):
        subscription = db.get(Subscription, row.subscription_id, with_for_update=True)
        if subscription is None:
            continue
        subscription.price_cents = row.new_price_cents
        row.applied_at = now
        count += 1
    if count:
        db.flush()
    return count


# ---------- Avisos (los envia el job) ----------


@dataclass
class NoticeReport:
    sent: int = 0
    failed: int = 0
    closed: int = 0


def send_notices(
    db: Session, sender: EmailSender, now: datetime, limit: int = NOTICES_PER_RUN
) -> NoticeReport:
    """Envia los avisos pendientes, uno por uno, y anota cada uno solo si el
    envio salio bien. Hace commit por aviso.

    - Subida: a una suscripcion activa o en mora. Al anotar el aviso queda su
      fecha: 30 dias despues. Una cancelada espera (si la reanuda, se le
      avisa); una que ya vencio sale del traslado sin correo.
    - Bajada: informativo, a toda suscripcion con el periodo vigente.
    - Traslado cancelado: a quien ya habia recibido el aviso de la subida.
    """
    # Aqui y no arriba: `billing_emails` importa `core/subscriptions`, que
    # importa este modulo.
    from app.core import billing_emails

    report = NoticeReport()
    _close_lapsed(db, now, report)

    rows = list(
        db.scalars(
            select(SubscriptionPriceChange)
            .join(Subscription, Subscription.id == SubscriptionPriceChange.subscription_id)
            .where(
                SubscriptionPriceChange.notice_sent_at.is_(None),
                SubscriptionPriceChange.canceled_at.is_(None),
                Subscription.current_period_end > now,
                # Una subida espera si la suscripcion esta cancelada; asi las
                # que esperan no ocupan el lote de las demas.
                or_(
                    and_(
                        SubscriptionPriceChange.applied_at.is_(None),
                        Subscription.status.in_(_RENEWING),
                    ),
                    and_(
                        SubscriptionPriceChange.applied_at.is_not(None),
                        Subscription.status.in_(_PAID),
                    ),
                ),
            )
            .order_by(SubscriptionPriceChange.created_at, SubscriptionPriceChange.id)
            .limit(limit)
        )
    )
    for row in rows:
        subscription = db.get(Subscription, row.subscription_id)
        user = db.get(User, subscription.user_id) if subscription is not None else None
        if subscription is None or user is None:
            continue
        increase = row.applied_at is None
        sent_at = now
        if increase:
            effective = price_change.effective_at(
                row.old_price_cents,
                row.new_price_cents,
                registered_at=row.created_at,
                notice_sent_at=sent_at,
            )
            message = billing_emails.price_increase(user, subscription, row, effective)
        else:
            message = billing_emails.price_decrease(user, subscription, row)
        if not _send(sender, message, report):
            continue
        row.notice_sent_at = sent_at
        if increase:
            row.effective_at = effective
        db.commit()

    remaining = max(limit - report.sent - report.failed, 0)
    for row in db.scalars(
        select(SubscriptionPriceChange)
        .where(
            SubscriptionPriceChange.canceled_at.is_not(None),
            SubscriptionPriceChange.notice_sent_at.is_not(None),
            SubscriptionPriceChange.applied_at.is_(None),
            SubscriptionPriceChange.cancel_notice_sent_at.is_(None),
        )
        .order_by(SubscriptionPriceChange.canceled_at, SubscriptionPriceChange.id)
        .limit(remaining)
    ).all():
        subscription = db.get(Subscription, row.subscription_id)
        user = db.get(User, subscription.user_id) if subscription is not None else None
        if subscription is None or user is None:
            continue
        if not _send(sender, billing_emails.price_change_canceled(user, subscription, row), report):
            continue
        row.cancel_notice_sent_at = now
        db.commit()
    return report


def _send(sender: EmailSender, message: EmailMessage, report: NoticeReport) -> bool:
    try:
        sender.send(message)
    except Exception:
        # Sin el correo no corre el plazo: se reintenta en la siguiente corrida.
        logger.exception("Traslado de precio: no se pudo enviar el aviso a %s", message.to)
        report.failed += 1
        return False
    report.sent += 1
    return True


def _close_lapsed(db: Session, now: datetime, report: NoticeReport) -> None:
    """Una subida pendiente de una suscripcion que ya no tiene periodo vigente
    no se le va a cobrar nunca: sale del traslado, sin correo."""
    rows = db.scalars(
        select(SubscriptionPriceChange)
        .join(Subscription, Subscription.id == SubscriptionPriceChange.subscription_id)
        .where(
            SubscriptionPriceChange.applied_at.is_(None),
            SubscriptionPriceChange.canceled_at.is_(None),
            (Subscription.status.not_in(_PAID)) | (Subscription.current_period_end <= now),
        )
    ).all()
    for row in rows:
        row.canceled_at = now
        # No hay a quien decirle que el precio no cambia: ya no tiene un periodo
        # vigente. Sin esto, si el traslado se cancelara despues, le llegaria.
        row.cancel_notice_sent_at = now
        report.closed += 1
    if rows:
        db.commit()

