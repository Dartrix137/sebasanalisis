"""Las notas credito y las facturas que no se emiten (docs/PLATAFORMA_COMPLETA.md
§3.17, "Paso 5.4", punto 12; Fase 5, paso 5.4).

**Que hace un reembolso o una anulacion con la factura** (`on_reversal`, lo
unico que crea notas credito). Lo llaman dos caminos, en su misma transaccion:
el registro de un reembolso en el admin (`POST /admin/payments/:id/refunds`) y
la rama de `core/subscriptions.apply_transaction` que anula un pago aprobado.
Lo respondio la contadora el 2026-11-11:

- **Si la factura todavia no esta en Siigo** (pendiente, o fallida sin haber
  llegado) **y se devolvio todo**, la factura no se emite: queda `cancelled`.
  "Lo mejor seria no emitir la factura".
- **Si ya esta aceptada por la DIAN**, nota credito: motivo 2 si devuelve todo,
  1 si una parte (`billing/credit_note.reason_for`). Una anulacion de la
  pasarela cuenta como reembolso de lo que falte por devolver.
- **Una devolucion parcial antes de emitir** (decidido por el usuario el
  2026-11-11): la factura sale por el total y despues la nota credito, con
  motivo 1. Si no se emitiera, la parte que no se devolvio quedaria sin
  factura.
- **Si esta en camino** (`sending`, `issued`), la nota espera a que la DIAN
  responda.
- **Si esta en Siigo sin aceptar** (`rejected`, o fallida despues de llegar):
  "solo si la factura quedo aceptada por la DIAN" lleva nota credito. La nota
  queda esperando; si se corrige y la DIAN la acepta, sale. Si en cambio se
  anula en Siigo Nube, el admin la marca anulada (`cancel_in_siigo`) y la nota
  se cancela con ella.

**El valor en pesos** es el de la factura, con sus tasas congeladas, sin
importar la tasa del dia del reembolso (la contadora; `billing/credit_note`).
La fecha es la del dia en que se emite: Siigo no admite otra.

**La emision** va en la misma corrida que la de las facturas
(`core/invoices.run_emission`), con el mismo envio (`invoices.attempt`): la
misma espera ante un error pasajero, el mismo freno ante uno de configuracion,
la `Idempotency-Key` propia de cada nota.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing import credit_note as rules
from app.billing import fx
from app.billing.invoice_document import FrozenRates, idempotency_key, pesos
from app.core import invoices
from app.invoicing.base import (
    CreditNoteDraft,
    InvoiceIssuer,
    IssuedInvoice,
    IssuerError,
    IssuerMisconfigured,
)
from app.models import CreditNote, Invoice, Payment, PaymentRefund

if TYPE_CHECKING:
    from app.core.invoices import EmissionReport

logger = logging.getLogger(__name__)

PENDING = invoices.PENDING
SENDING = invoices.SENDING
ISSUED = invoices.ISSUED
ACCEPTED = invoices.ACCEPTED
REJECTED = invoices.REJECTED
FAILED = invoices.FAILED
CANCELLED = invoices.CANCELLED

#: Por que una nota credito todavia no sale.
WAITING_INVOICE = "invoice_not_accepted"
WAITING_CONFIG = "credit_note_type_missing"

#: Desde donde se puede reintentar una nota credito.
RETRYABLE = (FAILED, PENDING, SENDING)
#: Desde donde se puede volver a consultar.
REFRESHABLE = (ISSUED, REJECTED)


@dataclass(frozen=True)
class ReversalOutcome:
    """Lo que paso con la factura: `invoice_cancelled` (no se emite),
    `credit_note` (se creo una nota) o `none` (nada que hacer)."""

    action: Literal["invoice_cancelled", "credit_note", "none"]
    credit_note_id: uuid.UUID | None = None


def _in_siigo(invoice: Invoice) -> bool:
    """Si la factura pudo haber llegado a Siigo. `sending` cuenta: no se sabe."""
    if invoice.provider_id is not None:
        return True
    return invoice.status in (SENDING, ISSUED, ACCEPTED, REJECTED)


def _active_notes(db: Session, invoice: Invoice) -> list[CreditNote]:
    return list(
        db.scalars(
            select(CreditNote)
            .where(CreditNote.invoice_id == invoice.id, CreditNote.status != CANCELLED)
            .order_by(CreditNote.created_at, CreditNote.id)
        )
    )


def _cancel_notes(notes: list[CreditNote], now: datetime) -> None:
    for note in notes:
        note.status = CANCELLED
        note.cancelled_at = now
        note.next_attempt_at = None
        note.waiting_reason = None


def on_reversal(
    db: Session, payment: Payment, *, refund: PaymentRefund | None, now: datetime
) -> ReversalOutcome:
    """Lo que hace con la factura del pago un reembolso (`refund`) o una
    anulacion de la pasarela (`refund=None`). NO hace commit: va en la misma
    transaccion que el reembolso o la anulacion."""
    invoice = db.scalar(
        select(Invoice).where(Invoice.payment_id == payment.id).with_for_update()
    )
    if invoice is None or invoice.status == CANCELLED:
        return ReversalOutcome("none")
    notes = _active_notes(db, invoice)
    credited = sum(n.amount_cents for n in notes)
    amount = refund.amount_cents if refund is not None else payment.amount_cents - credited
    if amount <= 0:
        return ReversalOutcome("none")
    if credited + amount > payment.amount_cents:
        raise ValueError("Lo devuelto no puede pasar de lo que se cobro")

    if credited + amount == payment.amount_cents and not _in_siigo(invoice):
        invoice.status = CANCELLED
        invoice.cancelled_at = now
        invoice.cancel_reason = "refunded" if refund is not None else "voided"
        invoice.next_attempt_at = None
        invoice.waiting_reason = None
        _cancel_notes(notes, now)
        return ReversalOutcome("invoice_cancelled")

    note = CreditNote(
        id=uuid.uuid4(),
        invoice_id=invoice.id,
        refund_id=refund.id if refund is not None else None,
        status=PENDING,
        reason=rules.reason_for(amount, payment.amount_cents),
        amount_cents=amount,
        currency=payment.currency,
        waiting_reason=None if invoice.status == ACCEPTED else WAITING_INVOICE,
    )
    db.add(note)
    db.flush()
    return ReversalOutcome("credit_note", note.id)


def cancel_in_siigo(db: Session, invoice: Invoice, now: datetime) -> None:
    """El admin anulo en Siigo Nube una factura que no quedo aceptada, de un
    pago que se devolvio entero: la factura queda `cancelled` y sus notas
    pendientes, con ella. NO hace commit."""
    payment = db.get(Payment, invoice.payment_id)
    if payment is None:
        raise ValueError("La factura no tiene pago")
    if invoice.status not in (REJECTED, FAILED) or not invoice.provider_id:
        raise ValueError("Solo se marca anulada una factura que esta en Siigo sin aceptar")
    if invoice.cufe and invoice.status != REJECTED:
        raise ValueError("La DIAN ya acepto esa factura: se corrige con nota credito")
    refunded = db.scalar(
        select(func.coalesce(func.sum(PaymentRefund.amount_cents), 0)).where(
            PaymentRefund.payment_id == payment.id
        )
    ) or 0
    if payment.status != "voided" and refunded < payment.amount_cents:
        raise ValueError(
            "Solo se marca anulada la factura de un pago anulado o reembolsado entero"
        )
    notes = _active_notes(db, invoice)
    if any(n.status not in (PENDING, FAILED) or n.provider_id for n in notes):
        raise ValueError("Esa factura ya tiene una nota credito en Siigo")
    invoice.status = CANCELLED
    invoice.cancelled_at = now
    invoice.cancel_reason = "annulled_in_siigo"
    invoice.next_attempt_at = None
    invoice.waiting_reason = None
    _cancel_notes(notes, now)


# ---------- Emitir ----------


def due(
    db: Session, now: datetime, *, limit: int = 25, payment_id: object | None = None
) -> list[uuid.UUID]:
    """Las notas que tocan: por enviar (con su factura aceptada) o esperando a
    la DIAN. Las que esperan a su factura no se cuentan: no llaman a Siigo."""
    to_send = (
        select(CreditNote.id)
        .join(Invoice, Invoice.id == CreditNote.invoice_id)
        .where(
            CreditNote.status.in_((PENDING, SENDING)),
            Invoice.status == ACCEPTED,
            (CreditNote.next_attempt_at.is_(None)) | (CreditNote.next_attempt_at <= now),
        )
    )
    waiting_dian = (
        select(CreditNote.id)
        .join(Invoice, Invoice.id == CreditNote.invoice_id)
        .where(CreditNote.status == ISSUED)
    )
    if payment_id is not None:
        to_send = to_send.where(Invoice.payment_id == payment_id)
        waiting_dian = waiting_dian.where(Invoice.payment_id == payment_id)
    ids = list(db.scalars(to_send.order_by(CreditNote.created_at, CreditNote.id).limit(limit)))
    ids += list(
        db.scalars(waiting_dian.order_by(CreditNote.created_at, CreditNote.id).limit(limit))
    )
    return ids


def _frozen_rates(invoice: Invoice) -> FrozenRates | None:
    if invoice.usd_cop is None or invoice.usd_cop_date is None:
        return None
    return FrozenRates(
        eur_usd=invoice.eur_usd,
        eur_usd_date=invoice.eur_usd_date,
        eur_usd_source="Banco Central Europeo" if invoice.eur_usd is not None else None,
        usd_cop=invoice.usd_cop,
        usd_cop_date=invoice.usd_cop_date,
        usd_cop_source="Superintendencia Financiera",
    )


def prepare(db: Session, note: CreditNote, invoice: Invoice, now: datetime) -> None:
    """Congela la nota: el valor en pesos con las tasas de la factura, el
    texto y la llave. NO hace commit."""
    if note.prepared_at is not None:
        return
    payment = db.get(Payment, invoice.payment_id)
    if payment is None or invoice.cop_cents is None:
        raise ValueError("La nota credito sale de una factura preparada")
    before = sum(
        n.amount_cents
        for n in _active_notes(db, invoice)
        if (n.created_at, n.id) < (note.created_at, note.id)
    )
    cop_cents = rules.cop_cents_for(
        credited_before_cents=before,
        amount_cents=note.amount_cents,
        paid_cents=payment.amount_cents,
        currency=payment.currency,
        rates=fx.Rates(eur_usd=invoice.eur_usd, usd_cop=invoice.usd_cop),
        invoice_cop_cents=invoice.cop_cents,
    )
    note.cop_cents = cop_cents
    note.description = invoice.description
    note.observations = rules.observations(
        invoice_name=invoice.provider_name or "",
        reason=1 if note.reason == 1 else 2,
        amount_cents=note.amount_cents,
        currency=note.currency,
        cop_cents=cop_cents,
        rates=_frozen_rates(invoice),
        payment_reference=payment.reference,
        invoice_issue_date=invoice.issue_date,
    )
    if note.idempotency_key is None:
        note.idempotency_key = idempotency_key(note.id, "NC")
    note.prepared_at = now
    note.waiting_reason = None


def _draft(note: CreditNote, invoice: Invoice, now: datetime) -> CreditNoteDraft:
    assert note.cop_cents is not None and invoice.provider_id is not None
    return CreditNoteDraft(
        idempotency_key=note.idempotency_key or "",
        issue_date=fx.operation_date(now),
        invoice_provider_id=invoice.provider_id,
        reason=note.reason,
        description=note.description or "",
        amount=pesos(note.cop_cents),
        observations=note.observations or "",
    )


def _apply(note: CreditNote, result: IssuedInvoice, now: datetime) -> str:
    note.provider_id = result.provider_id
    note.provider_name = result.name or note.provider_name
    if result.total is not None:
        note.provider_total = result.total
    note.stamp_status = result.stamp_status
    note.cude = result.cufe or note.cude
    note.mail_status = result.mail_status or note.mail_status
    note.next_attempt_at = None
    expected = pesos(note.cop_cents) if note.cop_cents else None
    if result.total is not None and expected is not None and result.total != expected:
        note.status = FAILED
        note.last_error_codes = ["total_mismatch"]
        note.last_error_message = (
            f"Siigo calculo un total de {result.total} y se esperaba {expected}"
        )
        logger.error("Nota credito %s: el total de Siigo no cuadra", note.id)
        return FAILED
    if result.stamp_status == "Accepted":
        note.status = ACCEPTED
        note.accepted_at = now
        note.last_error_codes = None
        note.last_error_message = None
        return ACCEPTED
    if result.stamp_status == "Rejected":
        # Siigo no tiene un endpoint de errores de la DIAN para notas credito.
        note.status = REJECTED
        logger.error("Nota credito %s: la DIAN la rechazo", note.id)
        return REJECTED
    note.status = ISSUED
    return ISSUED


def _send(
    db: Session, issuer: InvoiceIssuer, note: CreditNote, invoice: Invoice, now: datetime
) -> str:
    """Un intento de envio de la nota, con el mismo envio de la factura."""
    return invoices.attempt(
        db,
        note,
        now,
        lambda: issuer.issue_credit_note(_draft(note, invoice, now)),
        lambda result: _apply(note, result, now),
        "Nota credito",
    )


def _locked(db: Session, note_id: uuid.UUID) -> CreditNote | None:
    return db.scalar(
        select(CreditNote).where(CreditNote.id == note_id).with_for_update(skip_locked=True)
    )


def process(
    db: Session,
    issuer: InvoiceIssuer,
    now: datetime,
    note_ids: list[uuid.UUID],
    report: EmissionReport,
) -> None:
    """Prepara, envia y reconsulta las notas. `IssuerMisconfigured` frena,
    como con las facturas."""
    for note_id in note_ids:
        note = _locked(db, note_id)
        if note is None:
            db.rollback()
            continue
        invoice = db.get(Invoice, note.invoice_id)
        assert invoice is not None
        if note.status == ISSUED and note.provider_id:
            try:
                state = _apply(note, issuer.fetch_credit_note(note.provider_id), now)
            except IssuerError as exc:
                db.rollback()
                if isinstance(exc, IssuerMisconfigured):
                    raise
                report.errors.append(f"nota {note_id}: {exc}")
                continue
            db.commit()
            _count(report, state)
            continue
        if note.status not in (PENDING, SENDING) or invoice.status != ACCEPTED:
            db.rollback()
            continue
        if not issuer.credit_notes_enabled:
            note.waiting_reason = WAITING_CONFIG
            db.commit()
            logger.error("Nota credito %s: falta SIIGO_CREDIT_NOTE_DOCUMENT_TYPE_ID", note.id)
            continue
        if note.prepared_at is None:
            try:
                prepare(db, note, invoice, now)
            except ValueError as exc:
                # Un monto que no cuadra con la factura: lo mira una persona.
                note.status = FAILED
                note.last_error_codes = ["invalid_amount"]
                note.last_error_message = str(exc)[:500]
                db.commit()
                logger.error("Nota credito %s: %s", note.id, exc)
                _count(report, FAILED)
                continue
            db.commit()
        _count(report, _send(db, issuer, note, invoice, now))


def _count(report: EmissionReport, state: str) -> None:
    if state in (ACCEPTED, ISSUED):
        report.credit_notes_sent += 1
    elif state in (FAILED, REJECTED):
        report.credit_notes_failed += 1


# ---------- Acciones del admin ----------


def reset_for_retry(note: CreditNote) -> None:
    """Deja la nota lista para otro intento ya. NO hace commit.

    Como la factura: una fallida que nunca llego a Siigo se vuelve a preparar
    con una llave nueva (una llave usada queda usada para siempre, soporte de
    Siigo 2026-11-09). Una fallida que si llego (el total no cuadro) no se
    reintenta desde aqui: Siigo no documenta como anular una nota credito, y
    se revisa en Siigo Nube. Una en `sending` conserva su llave."""
    if note.status not in RETRYABLE:
        raise ValueError(f"Una nota credito {note.status} no se reintenta")
    if note.status == FAILED:
        if note.provider_id:
            raise ValueError("Esa nota credito ya esta en Siigo: revisala en Siigo Nube")
        note.prepared_at = None
        note.idempotency_key = idempotency_key(uuid.uuid4(), "NC")
        note.stamp_status = None
        note.mail_status = None
    note.status = PENDING
    note.attempts = 0
    note.next_attempt_at = None
    note.last_error_codes = None
    note.last_error_message = None


def refresh(issuer: InvoiceIssuer, note: CreditNote, now: datetime) -> str:
    """Vuelve a consultar una nota emitida o rechazada. NO hace commit."""
    if note.status not in REFRESHABLE or note.provider_id is None:
        raise ValueError(f"Una nota credito {note.status} no se reconsulta")
    return _apply(note, issuer.fetch_credit_note(note.provider_id), now)
