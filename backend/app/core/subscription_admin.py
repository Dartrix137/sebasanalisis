"""Acciones del administrador sobre una suscripcion (docs/PLATAFORMA_COMPLETA.md §4.3 y §4.8).

Tres, decididas por el usuario el 2026-10-14:

- `extend`: corre `current_period_end` unos dias, como compensacion. En la
  renovacion automatica se corren tambien el proximo cobro y su aviso, porque
  el job los deriva del vencimiento.
- `cancel_at_period_end`: lo mismo que cancela el cliente desde `/cuenta`. Solo
  aplica a la renovacion automatica; la de pago manual no se cobra sola.
- `cancel_now`: el acceso cae en el acto (el periodo termina ahora y la
  suscripcion vence) y se borra la referencia del medio de pago. No devuelve
  nada: si corresponde, se reembolsa en el panel del proveedor y se registra.

Cada una deja su fila en `admin_audit_log` (`core/audit.record`) en la misma
transaccion que el cambio, con el motivo. Ninguna toca un pago: los pagos solo
los mueve `core/subscriptions.apply_transaction`.

Aqui no se decide el acceso: lo decide `core/access.has_access` con `status` y
`current_period_end`. Un administrador entra por su rol, asi que nada de esto lo
deja sin acceso aunque la suscripcion sea la suya.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.schedule import first_charge_at
from app.core import audit, subscriptions
from app.core.subscriptions import SubscribeError
from app.models import Payment, Subscription, User

AdminAction = Literal["extend", "cancel_at_period_end", "cancel_now"]

#: Cuantos dias se puede extender de una vez.
MAX_EXTENSION_DAYS = 90


@dataclass(frozen=True)
class AdminChange:
    subscription: Subscription
    action: AdminAction


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _snapshot(subscription: Subscription) -> dict[str, Any]:
    """Lo que la bitacora guarda de la suscripcion, antes y despues."""
    return {
        "status": subscription.status,
        "renewal_mode": subscription.renewal_mode,
        "current_period_end": _iso(subscription.current_period_end),
        "next_charge_at": _iso(subscription.next_charge_at),
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "payment_source": subscription.payment_source_id is not None,
    }


def _charge_in_flight(db: Session, subscription: Subscription) -> bool:
    """Un cobro que el proveedor ya recibio y no ha resuelto. Si se aprobara
    despues de la accion, daria un periodo que el administrador no vio."""
    return (
        db.scalar(
            select(Payment.id)
            .where(
                Payment.user_id == subscription.user_id,
                Payment.status == "pending",
                Payment.provider_transaction_id.is_not(None),
            )
            .limit(1)
        )
        is not None
    )


def apply(
    db: Session,
    *,
    admin: User,
    subscription_id: uuid.UUID,
    action: AdminAction,
    days: int | None,
    reason: str,
    ip: str | None,
    now: datetime,
) -> AdminChange:
    """Aplica la accion y confirma el cambio con su fila de bitacora."""
    subscription = db.scalar(
        select(Subscription).where(Subscription.id == subscription_id).with_for_update()
    )
    if subscription is None:
        raise SubscribeError(404, "not_found", "Suscripción no encontrada")
    if not subscriptions.in_force(subscription, now):
        raise SubscribeError(
            409,
            "not_in_force",
            "La suscripción no tiene un período vigente. Para darle acceso a esa cuenta, usa el "
            "acceso manual.",
        )
    if _charge_in_flight(db, subscription):
        raise SubscribeError(
            409,
            "charge_in_progress",
            "La cuenta tiene un cobro en proceso. Espera a que se resuelva (o reconsúltalo en "
            "Pagos) y vuelve a intentarlo.",
        )

    before = _snapshot(subscription)
    if action == "extend":
        _extend(subscription, days)
    elif action == "cancel_at_period_end":
        _cancel_at_period_end(subscription, now)
    else:
        _cancel_now(subscription, now)

    audit.record(
        db,
        admin,
        action=f"subscription.{action}",
        target_type="subscription",
        target_id=subscription.id,
        before=before,
        after={**_snapshot(subscription), **({"days": days} if action == "extend" else {})},
        reason=reason,
        ip=ip,
    )
    db.commit()
    db.refresh(subscription)
    return AdminChange(subscription=subscription, action=action)


def _extend(subscription: Subscription, days: int | None) -> None:
    if days is None or not 1 <= days <= MAX_EXTENSION_DAYS:
        raise SubscribeError(
            422, "invalid_days", f"Indica entre 1 y {MAX_EXTENSION_DAYS} días."
        )
    assert subscription.current_period_end is not None
    subscription.current_period_end += timedelta(days=days)
    if subscription.status == "past_due":
        # Los intentos fallidos eran del cobro del vencimiento anterior. El
        # proximo es el del vencimiento nuevo, con sus tres intentos.
        subscription.status = "active"
        subscription.retry_count = 0
    if subscription.renewal_mode == "automatic" and subscription.status == "active":
        subscription.next_charge_at = first_charge_at(subscription.current_period_end)
    # `notice_sent_for` se queda: apunta al vencimiento anterior, asi que el
    # aviso del cobro (o del vencimiento) vuelve a salir para la fecha nueva.


def _cancel_at_period_end(subscription: Subscription, now: datetime) -> None:
    if subscription.status == "canceled":
        raise SubscribeError(
            409, "already_canceled", "La renovación de esta suscripción ya está cancelada."
        )
    if subscription.renewal_mode != "automatic":
        raise SubscribeError(
            409,
            "not_automatic",
            "Esta suscripción es de pago manual: no se cobra sola, así que no hay renovación "
            "que cancelar. Para quitarle el acceso ya, cancélala de inmediato.",
        )
    subscriptions.stop_renewal(subscription, now)


def _cancel_now(subscription: Subscription, now: datetime) -> None:
    # El periodo termina ahora y la suscripcion vence: `has_access` deja de
    # darle acceso y reporta `expired` con esta fecha.
    subscription.status = "expired"
    subscription.current_period_end = now
    subscription.canceled_at = now
    subscription.cancel_at_period_end = False
    subscription.next_charge_at = None
    subscription.retry_count = 0
    # Sin la referencia del medio de pago ya no hay a que cobrarle.
    subscription.renewal_mode = "manual"
    subscription.payment_source_id = None
    subscription.payment_source_type = None
    subscription.card_brand = None
    subscription.card_last4 = None
