"""La factura pendiente de cada pago aprobado (docs/PLATAFORMA_COMPLETA.md §3.17;
Fase 5, paso 5.2).

`create_pending` se llama desde un solo lugar: la rama de `core/subscriptions.
apply_transaction` que aprueba un pago, en su misma transaccion. Asi la cubren
todos los caminos que aprueban (webhook, consulta del estado del pago, cobro de
la renovacion automatica, "Reconsultar" en el admin) y no existe un pago
aprobado sin su factura.

La emision con Dataico es del paso 5.4: hasta entonces la fila se queda en
`pending` y nada sale de la aplicacion.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing import fx
from app.models import Invoice, Payment

PENDING = "pending"


def create_pending(db: Session, payment: Payment) -> Invoice:
    """Agrega a la sesion la factura pendiente del pago. NO hace commit: el pago
    aprobado y su factura se confirman juntos.

    Si el pago ya tiene factura, devuelve esa. La base, ademas, no admite dos
    por pago (`invoices.payment_id` es unico).
    """
    if payment.resolved_at is None:
        raise ValueError("La factura sale de un pago ya resuelto")
    existing = db.scalar(select(Invoice).where(Invoice.payment_id == payment.id))
    if existing is not None:
        return existing
    invoice = Invoice(
        payment_id=payment.id,
        status=PENDING,
        operation_date=fx.operation_date(payment.resolved_at),
    )
    db.add(invoice)
    return invoice
