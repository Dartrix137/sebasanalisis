"""Las facturas de los pagos de prueba (Fase 5, paso 5.6; decidido por el
usuario el 2026-11-13).

Nada distingue un pago aprobado en el sandbox de Tipster Page de uno real: los
de prueba del VPS tienen su factura `pending`, y con `INVOICE_ISSUER=siigo` en
la empresa real saldrian a la DIAN como facturas de verdad. Antes de encender
la emision se apartan: `cancelled` con el motivo `test_payment`, con una fila
en la bitacora por cada una. Lo corre `scripts/cancel_test_invoices.py`.

Solo se aparta una factura que nunca se intento enviar a Siigo (`pending`, sin
intentos y sin id de Siigo), de un pago aprobado antes de `before`: el momento
en que la pasarela paso a produccion. Una que ya se intento, aunque fallara,
pudo haber llegado a Siigo y la mira una persona.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, credit_notes, invoices
from app.models import Invoice, Payment, User

TEST_PAYMENT = "test_payment"


@dataclass(frozen=True)
class SandboxInvoice:
    """Lo que se lista de cada una: sin datos del comprador."""

    invoice_id: object
    payment_id: object
    amount_cents: int
    currency: str
    approved_at: datetime


def candidates(db: Session, before: datetime) -> list[SandboxInvoice]:
    rows = db.execute(
        select(Invoice, Payment)
        .join(Payment, Payment.id == Invoice.payment_id)
        .where(
            Invoice.status == invoices.PENDING,
            Invoice.attempts == 0,
            Invoice.provider_id.is_(None),
            Payment.status == "approved",
            Payment.resolved_at < before,
        )
        .order_by(Payment.resolved_at, Invoice.id)
    ).all()
    return [
        SandboxInvoice(
            invoice_id=invoice.id,
            payment_id=payment.id,
            amount_cents=payment.amount_cents,
            currency=payment.currency,
            approved_at=payment.resolved_at,
        )
        for invoice, payment in rows
        if payment.resolved_at is not None
    ]


def cancel(
    db: Session, admin: User, before: datetime, reason: str, now: datetime
) -> list[SandboxInvoice]:
    """Aparta las facturas de `candidates`. NO hace commit: las facturas y sus
    filas de la bitacora se confirman juntas."""
    if admin.role != "admin":
        raise ValueError("Solo un administrador aparta facturas")
    if before > now:
        raise ValueError("La fecha de corte no puede ser futura")
    reason = reason.strip()
    if len(reason) < 3:
        raise ValueError("El motivo es obligatorio")
    done: list[SandboxInvoice] = []
    for item in candidates(db, before):
        invoice = db.scalar(
            select(Invoice).where(Invoice.id == item.invoice_id).with_for_update()
        )
        # Otra corrida pudo tomarla entre la lista y el candado.
        if (
            invoice is None
            or invoice.status != invoices.PENDING
            or invoice.attempts
            or invoice.provider_id
        ):
            continue
        invoice.status = invoices.CANCELLED
        invoice.cancelled_at = now
        invoice.cancel_reason = TEST_PAYMENT
        invoice.next_attempt_at = None
        invoice.waiting_reason = None
        # Una nota credito de una factura que no se emite tampoco sale.
        credit_notes._cancel_notes(credit_notes._active_notes(db, invoice), now)
        audit.record(
            db,
            admin,
            action="invoice.cancel_test_payment",
            target_type="payment",
            target_id=item.payment_id,
            before={"status": invoices.PENDING},
            after={"status": invoices.CANCELLED, "cancel_reason": TEST_PAYMENT},
            reason=reason,
        )
        done.append(item)
    return done
