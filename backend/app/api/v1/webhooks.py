"""Webhook del proveedor de pagos (docs/PLATAFORMA_COMPLETA.md §3.1 y §3.4).

Sin JWT: lo autentica la firma del evento. Tres reglas, en este orden:

1. TODO evento se guarda en `payment_events`, con firma valida o no.
2. Un evento sin firma valida se rechaza y no mueve nada.
3. Un evento con firma valida tampoco es la fuente de verdad: solo dice que
   transaccion reconsultar. Lo que se aplica es la respuesta de la API del
   proveedor, con `core/subscriptions.apply_transaction`.

Idempotencia por `provider_event_id`: un evento ya procesado no se repite.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.api.v1.billing import EmailSenderDep, PaymentProviderDep, queue_payment_emails
from app.core import subscriptions
from app.models import PaymentEvent
from app.payments.base import PaymentProviderError, ProviderEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Un evento legitimo pesa unos pocos KB.
MAX_BODY_BYTES = 256 * 1024


async def _raw_body(request: Request) -> bytes:
    """El cuerpo tal como llego: la firma se calcula sobre el, no sobre un modelo."""
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    return body


def _store_event(db: DbSession, event: ProviderEvent) -> PaymentEvent:
    """Guarda el evento, o devuelve la fila si ya habia llegado."""
    existing = db.scalar(
        select(PaymentEvent).where(PaymentEvent.provider_event_id == event.event_id)
    )
    if existing is not None:
        return existing
    row = PaymentEvent(
        provider_event_id=event.event_id,
        event_type=event.event_type[:100],
        status=event.status[:50],
        raw_payload=event.payload,
        signature_verified=event.signature_verified,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Dos entregas del mismo evento a la vez: gana la que guardo primero.
        db.rollback()
        return db.scalars(
            select(PaymentEvent).where(PaymentEvent.provider_event_id == event.event_id)
        ).one()
    return row


@router.post("/wompi")
def wompi_webhook(
    request: Request,
    body: Annotated[bytes, Depends(_raw_body)],
    db: DbSession,
    background: BackgroundTasks,
    sender: EmailSenderDep,
    provider: PaymentProviderDep,
) -> dict[str, str]:
    """Recibe un evento de Wompi. Responde 200 cuando quedo procesado; cualquier
    otra respuesta hace que Wompi lo reintente."""
    event = provider.parse_event(body, request.headers)
    row = _store_event(db, event)

    if not event.signature_verified:
        # Queda guardado para auditar; el acceso no cambia.
        logger.warning("Webhook de pagos con firma invalida (evento %s)", row.id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Firma inválida")
    if row.processed_at is not None:
        return {"status": "duplicate"}

    now = datetime.now(UTC)
    settlement = None
    if event.transaction_id is not None:
        try:
            transaction = provider.fetch_transaction(event.transaction_id)
        except PaymentProviderError as exc:
            # Sin reconsulta no se mueve nada. El evento queda sin procesar y el
            # reintento del proveedor lo retoma.
            logger.warning("No se pudo reconsultar la transaccion del evento %s", row.id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No se pudo confirmar la transacción con el proveedor",
            ) from exc
        if transaction is not None:
            settlement = subscriptions.apply_transaction(db, transaction, now)

    row = db.get(PaymentEvent, row.id) or row
    if settlement is not None:
        row.payment_id = settlement.payment.id
        row.subscription_id = settlement.payment.subscription_id
        queue_payment_emails(db, settlement, background, sender)
    # Sin pago: la referencia no es nuestra. Se guarda y no mueve nada.
    row.processed_at = now
    db.commit()
    return {"status": "processed" if settlement is not None else "ignored"}
