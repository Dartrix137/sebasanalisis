"""Lo que queda de los pagos al eliminar una cuenta (docs/PLATAFORMA_COMPLETA.md §5.4).

Decidido el 2026-10-13: los pagos se conservan anonimizados por obligacion
contable, y la suscripcion se borra con la cuenta.

- `payments`: la base pone `user_id` en null (`ON DELETE SET NULL`). La fila no
  tiene nada mas que identifique a nadie: plan, monto, estado, referencia.
- `subscriptions`: se borra en cascada, y con ella la referencia del medio de
  pago, la marca y los ultimos cuatro digitos. Sin esa referencia no hay como
  volver a cobrar.
- `payment_events`: el evento del proveedor trae el correo del cliente y datos
  de su medio de pago. `anonymize_payment_trail` lo reduce a lo que explica el
  pago.
- `coupon_redemptions`: `user_id` queda en null; el uso sigue contando.
"""

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Payment, PaymentEvent, Subscription

# Lo unico que se conserva de la transaccion de un evento. Nada de esto
# identifica a una persona.
_KEPT_TRANSACTION_FIELDS = (
    "id",
    "reference",
    "status",
    "status_message",
    "amount_in_cents",
    "currency",
    "payment_method_type",
    "created_at",
    "finalized_at",
)
_KEPT_EVENT_FIELDS = ("event", "environment", "timestamp", "sent_at")


def scrub_event_payload(payload: Any) -> dict[str, Any] | None:
    """El cuerpo de un evento sin el correo, el nombre, el telefono ni los
    datos del medio de pago: solo que transaccion fue y como termino."""
    if not isinstance(payload, dict):
        return None
    scrubbed: dict[str, Any] = {k: payload[k] for k in _KEPT_EVENT_FIELDS if k in payload}
    data = payload.get("data")
    transaction = data.get("transaction") if isinstance(data, dict) else None
    if isinstance(transaction, dict):
        scrubbed["data"] = {
            "transaction": {
                k: transaction[k] for k in _KEPT_TRANSACTION_FIELDS if k in transaction
            }
        }
    scrubbed["anonymized"] = True
    return scrubbed


def payment_in_flight(db: Session, user_id: uuid.UUID) -> bool:
    """La cuenta tiene un cobro que el proveedor ya recibio y todavia no
    resuelve. Un pago abierto que nunca llego al proveedor no cuenta."""
    return (
        db.scalar(
            select(Payment.id)
            .where(
                Payment.user_id == user_id,
                Payment.status == "pending",
                Payment.provider_transaction_id.is_not(None),
            )
            .limit(1)
        )
        is not None
    )


def anonymize_payment_trail(db: Session, user_id: uuid.UUID) -> None:
    """Quita los datos personales de los eventos de los pagos de la cuenta.
    Se llama antes de borrarla, en la misma transaccion. No hace commit."""
    events = db.scalars(
        select(PaymentEvent).where(
            or_(
                PaymentEvent.payment_id.in_(select(Payment.id).where(Payment.user_id == user_id)),
                PaymentEvent.subscription_id.in_(
                    select(Subscription.id).where(Subscription.user_id == user_id)
                ),
            )
        )
    )
    for event in events:
        event.raw_payload = scrub_event_payload(event.raw_payload)
