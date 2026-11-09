"""La factura electronica de cada pago aprobado (docs/PLATAFORMA_COMPLETA.md §3.17,
"Paso 5.4"; Fase 5, pasos 5.2 y 5.4).

**Donde nace.** `create_pending` se llama desde un solo lugar: la rama de
`core/subscriptions.apply_transaction` que aprueba un pago, en su misma
transaccion. Asi la cubren todos los caminos que aprueban (webhook, consulta
del estado del pago, cobro de la renovacion automatica, "Reconsultar" en el
admin) y no existe un pago aprobado sin su factura.

**Como se emite** (paso 5.4). La emision nunca va dentro del pago: si Siigo
esta caido, el cobro no puede fallar. La hace `run_emission`, por dos caminos:

- Enseguida, como tarea de fondo despues del commit del pago
  (`emit_in_background`): Siigo no admite una factura con fecha anterior a hoy,
  asi que conviene emitirla el mismo dia.
- El job de cada hora (`scripts/run_renewals.py`), como respaldo.

Antes del primer envio se congela todo (`prepare`): los datos del comprador,
las tasas del dia del pago, el monto en pesos, los textos y la llave de
idempotencia. Los reintentos mandan lo mismo; solo cambia la fecha de emision,
que es la del dia en que sale (la contadora: esta bien con la TRM del dia del
pago).

Estados: `pending` -> `sending` -> `issued` -> `accepted`, o `rejected` (la
DIAN) o `failed` (Siigo rechazo los datos, o el total no cuadra; no se
reintenta sola). Un error pasajero vuelve a `pending` con un proximo intento;
un tiempo agotado deja `sending` y el reintento manda la misma llave. Un error
de configuracion frena la corrida entera.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.billing import checkout_text, fx
from app.billing.invoice_document import FrozenRates, idempotency_key, observations, pesos
from app.core import billing_profiles
from app.core.exchange_rates import RateSources, RateUnavailable, rates_for
from app.invoicing.base import (
    Buyer,
    InvoiceDraft,
    InvoiceIssuer,
    IssuedInvoice,
    IssuerError,
    IssuerMisconfigured,
    IssuerRejected,
    IssuerTransient,
)
from app.models import Invoice, Payment, Plan, User

logger = logging.getLogger(__name__)

PENDING = "pending"
SENDING = "sending"
ISSUED = "issued"
ACCEPTED = "accepted"
REJECTED = "rejected"
FAILED = "failed"

#: Intentos de envio antes de darla por fallida (los pasajeros).
MAX_ATTEMPTS = 8
#: Espera tras cada intento pasajero; el ultimo valor se repite.
_BACKOFF = (
    timedelta(minutes=10),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=3),
    timedelta(hours=6),
    timedelta(hours=12),
    timedelta(hours=24),
)
#: Mientras una factura esta `sending`, otra corrida no la toca durante esto.
_SENDING_GUARD = timedelta(minutes=10)

# Motivos por los que una factura todavia no sale.
WAITING_PROFILE = "billing_profile_missing"
WAITING_RATES = "rates_pending"
WAITING_RATES_SOURCE = "rates_unavailable"
WAITING_PAYMENT = "payment_not_approved"


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


@dataclass
class EmissionReport:
    prepared: int = 0
    issued: int = 0
    accepted: int = 0
    rejected: int = 0
    failed: int = 0
    waiting: int = 0
    retried: int = 0
    #: Por que se detuvo la corrida, si se detuvo (configuracion o caida).
    stopped: str | None = None
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"preparadas={self.prepared} emitidas={self.issued} aceptadas={self.accepted}"
            f" rechazadas={self.rejected} fallidas={self.failed} en_espera={self.waiting}"
            f" a_reintentar={self.retried}" + (f" detenida={self.stopped}" if self.stopped else "")
        )


# ---------- Preparar: congelar lo que lleva ----------


def prepare(db: Session, invoice: Invoice, sources: RateSources, now: datetime) -> bool:
    """Congela la factura si todavia no lo esta. True si quedo lista para
    enviar; si no, deja el motivo en `waiting_reason`. NO hace commit."""
    if invoice.prepared_at is not None:
        return True
    payment = db.get(Payment, invoice.payment_id)
    if payment is None or payment.status != "approved":
        invoice.waiting_reason = WAITING_PAYMENT
        return False
    profile = billing_profiles.get(db, payment.user_id) if payment.user_id else None
    user = db.get(User, payment.user_id) if payment.user_id else None
    if profile is None or user is None:
        invoice.waiting_reason = WAITING_PROFILE
        return False

    rates: FrozenRates | None = None
    if payment.currency == fx.FUNCTIONAL_CURRENCY:
        cop_cents = payment.amount_cents
    else:
        try:
            found = rates_for(db, invoice.operation_date, payment.currency, sources)
        except RateUnavailable as exc:
            logger.warning("Factura %s: sin tasas todavia (%s)", invoice.id, exc)
            invoice.waiting_reason = WAITING_RATES_SOURCE
            return False
        if found is None:
            invoice.waiting_reason = WAITING_RATES
            return False
        cop_cents = fx.to_cop_cents(payment.amount_cents, payment.currency, found.as_fx())
        rates = FrozenRates(
            eur_usd=found.eur_usd.value if found.eur_usd else None,
            eur_usd_date=found.eur_usd.valid_from if found.eur_usd else None,
            eur_usd_source="Banco Central Europeo" if found.eur_usd else None,
            usd_cop=found.trm.value,
            usd_cop_date=found.trm.valid_from,
            usd_cop_source="Superintendencia Financiera",
        )
        invoice.eur_usd = rates.eur_usd
        invoice.eur_usd_date = rates.eur_usd_date
        invoice.eur_usd_source = found.eur_usd.source if found.eur_usd else None
        invoice.usd_cop = rates.usd_cop
        invoice.usd_cop_date = rates.usd_cop_date
        invoice.usd_cop_source = found.trm.source

    plan = db.get(Plan, payment.plan_id)
    invoice.description = (
        f"{plan.name}: {checkout_text.product_description(plan.interval, plan.interval_count)}"
        if plan
        else "Suscripcion a Sebasanalisis"
    )[:500]
    invoice.cop_cents = cop_cents
    invoice.observations = observations(
        paid_cents=payment.amount_cents,
        paid_currency=payment.currency,
        cop_cents=cop_cents,
        rates=rates,
        payment_reference=payment.reference,
    )
    invoice.buyer_first_names = profile.first_names
    invoice.buyer_last_names = profile.last_names
    invoice.buyer_id_type = profile.id_type
    invoice.buyer_id_number = profile.id_number
    invoice.buyer_email = user.email
    invoice.buyer_country_code = profile.country_code
    invoice.buyer_state_code = profile.state_code
    invoice.buyer_city_code = profile.city_code
    invoice.buyer_address = profile.address
    invoice.idempotency_key = idempotency_key(invoice.id)
    invoice.prepared_at = now
    invoice.waiting_reason = None
    return True


def _draft(invoice: Invoice, now: datetime) -> InvoiceDraft:
    assert invoice.prepared_at is not None and invoice.cop_cents is not None
    return InvoiceDraft(
        idempotency_key=invoice.idempotency_key or "",
        issue_date=fx.operation_date(now),
        buyer=Buyer(
            id_type=invoice.buyer_id_type or "",
            id_number=invoice.buyer_id_number or "",
            first_names=invoice.buyer_first_names or "",
            last_names=invoice.buyer_last_names or "",
            email=invoice.buyer_email or "",
            address=invoice.buyer_address or "",
            country_code=invoice.buyer_country_code or "",
            state_code=invoice.buyer_state_code or "",
            city_code=invoice.buyer_city_code or "",
        ),
        description=invoice.description or "",
        amount=pesos(invoice.cop_cents),
        observations=invoice.observations or "",
    )


# ---------- Enviar y confirmar ----------


def _record_error(invoice: Invoice, exc: IssuerError) -> None:
    invoice.last_error_codes = exc.codes or None
    invoice.last_error_message = str(exc)[:500]


def _apply(db: Session, issuer: InvoiceIssuer, invoice: Invoice, result: IssuedInvoice,
           now: datetime) -> str:
    """Guarda lo que respondio el emisor y deja el estado que corresponde."""
    invoice.provider_id = result.provider_id
    invoice.provider_name = result.name or invoice.provider_name
    if result.total is not None:
        invoice.provider_total = result.total
    invoice.stamp_status = result.stamp_status
    invoice.cufe = result.cufe or invoice.cufe
    invoice.mail_status = result.mail_status or invoice.mail_status
    invoice.next_attempt_at = None
    expected = pesos(invoice.cop_cents) if invoice.cop_cents else None
    if result.total is not None and expected is not None and result.total != expected:
        # La factura existe en Siigo con otro total: no se toca sola.
        invoice.status = FAILED
        invoice.last_error_codes = ["total_mismatch"]
        invoice.last_error_message = (
            f"Siigo calculo un total de {result.total} y se esperaba {expected}"
        )
        logger.error("Factura %s: el total de Siigo no cuadra", invoice.id)
        return FAILED
    if result.stamp_status == "Accepted":
        invoice.status = ACCEPTED
        invoice.accepted_at = now
        invoice.last_error_codes = None
        invoice.last_error_message = None
        return ACCEPTED
    if result.stamp_status == "Rejected":
        invoice.status = REJECTED
        try:
            invoice.dian_errors = issuer.stamp_errors(result.provider_id)[:20] or None
        except IssuerError:
            invoice.dian_errors = None
        logger.error("Factura %s: la DIAN la rechazo", invoice.id)
        return REJECTED
    invoice.status = ISSUED
    return ISSUED


def _send(db: Session, issuer: InvoiceIssuer, invoice: Invoice, now: datetime) -> str:
    """Un intento de envio. Confirma en la base antes y despues de llamar."""
    invoice.status = SENDING
    invoice.attempts += 1
    invoice.sent_at = now
    invoice.issue_date = fx.operation_date(now)
    # Otra corrida no la toca mientras sale; si el proceso muere aqui, el
    # reintento manda la misma llave.
    invoice.next_attempt_at = now + _SENDING_GUARD
    db.commit()
    try:
        result = issuer.issue(_draft(invoice, now))
    except IssuerTransient as exc:
        _record_error(invoice, exc)
        if invoice.attempts >= MAX_ATTEMPTS:
            invoice.status = FAILED
            logger.error("Factura %s: sin respuesta de Siigo tras %s intentos",
                         invoice.id, invoice.attempts)
            db.commit()
            return FAILED
        invoice.status = SENDING if exc.uncertain else PENDING
        wait = _BACKOFF[min(invoice.attempts - 1, len(_BACKOFF) - 1)]
        if exc.retry_after:
            wait = max(wait, timedelta(seconds=exc.retry_after))
        invoice.next_attempt_at = now + wait
        db.commit()
        return "retry"
    except IssuerMisconfigured as exc:
        _record_error(invoice, exc)
        # No es culpa de esta factura: vuelve a esperar, sin gastar el intento.
        invoice.status = PENDING
        invoice.attempts -= 1
        invoice.next_attempt_at = None
        db.commit()
        raise
    except IssuerRejected as exc:
        _record_error(invoice, exc)
        invoice.status = FAILED
        invoice.next_attempt_at = None
        logger.error("Factura %s: Siigo rechazo los datos (%s)", invoice.id, exc.codes or "-")
        db.commit()
        return FAILED
    state = _apply(db, issuer, invoice, result, now)
    db.commit()
    return state


def _refresh(db: Session, issuer: InvoiceIssuer, invoice: Invoice, now: datetime) -> str:
    """Una factura emitida que espera a la DIAN: se vuelve a consultar."""
    assert invoice.provider_id is not None
    state = _apply(db, issuer, invoice, issuer.fetch(invoice.provider_id), now)
    db.commit()
    return state


def _locked(db: Session, invoice_id: object) -> Invoice | None:
    return db.scalar(
        select(Invoice).where(Invoice.id == invoice_id).with_for_update(skip_locked=True)
    )


def run_emission(
    db: Session,
    issuer: InvoiceIssuer,
    sources: RateSources,
    now: datetime,
    *,
    limit: int = 25,
    payment_id: object | None = None,
) -> EmissionReport:
    """Prepara y emite las facturas que tocan, y reconsulta las que esperan a
    la DIAN. Con `payment_id`, solo la de ese pago (la tarea de fondo)."""
    report = EmissionReport()
    if not issuer.enabled:
        report.stopped = "disabled"
        return report

    due = select(Invoice.id).where(
        Invoice.status.in_((PENDING, SENDING)),
        or_(Invoice.next_attempt_at.is_(None), Invoice.next_attempt_at <= now),
    )
    waiting_dian = select(Invoice.id).where(Invoice.status == ISSUED)
    if payment_id is not None:
        due = due.where(Invoice.payment_id == payment_id)
        waiting_dian = waiting_dian.where(Invoice.payment_id == payment_id)
    due_ids = list(db.scalars(due.order_by(Invoice.created_at).limit(limit)))
    issued_ids = list(db.scalars(waiting_dian.order_by(Invoice.created_at).limit(limit)))
    if not due_ids and not issued_ids:
        return report

    try:
        issuer.check_ready()
    except IssuerMisconfigured as exc:
        report.stopped = f"config: {exc}"
        logger.error("Emision de facturas detenida: %s", exc)
        return report
    except IssuerError as exc:
        report.stopped = f"emisor: {exc}"
        logger.warning("Emision de facturas sin emisor por ahora: %s", exc)
        return report

    for invoice_id in due_ids:
        invoice = _locked(db, invoice_id)
        if invoice is None or invoice.status not in (PENDING, SENDING):
            db.rollback()
            continue
        if invoice.prepared_at is None:
            if not prepare(db, invoice, sources, now):
                report.waiting += 1
                db.commit()
                continue
            report.prepared += 1
            db.commit()
            invoice = _locked(db, invoice_id)
            if invoice is None:
                db.rollback()
                continue
        try:
            state = _send(db, issuer, invoice, now)
        except IssuerMisconfigured as exc:
            report.stopped = f"config: {exc}"
            logger.error("Emision de facturas detenida: %s", exc)
            return report
        _count(report, state)

    for invoice_id in issued_ids:
        invoice = _locked(db, invoice_id)
        if invoice is None or invoice.status != ISSUED or invoice.provider_id is None:
            db.rollback()
            continue
        try:
            state = _refresh(db, issuer, invoice, now)
        except IssuerMisconfigured as exc:
            db.rollback()
            report.stopped = f"config: {exc}"
            logger.error("Emision de facturas detenida: %s", exc)
            return report
        except IssuerError as exc:
            db.rollback()
            report.errors.append(f"{invoice_id}: {exc}")
            continue
        if state != ISSUED:
            _count(report, state)
    return report


def _count(report: EmissionReport, state: str) -> None:
    if state == ACCEPTED:
        report.accepted += 1
    elif state == ISSUED:
        report.issued += 1
    elif state == REJECTED:
        report.rejected += 1
    elif state == FAILED:
        report.failed += 1
    elif state == "retry":
        report.retried += 1


def emit_in_background(bind: Engine, payment_id: object) -> None:
    """La tarea de fondo tras aprobar un pago: emite su factura, con su propia
    sesion. Nunca lanza: si algo falla, la toma el job de cada hora."""
    from app.core.exchange_rates import get_rate_sources
    from app.invoicing.base import get_invoice_issuer

    try:
        issuer = get_invoice_issuer()
        if not issuer.enabled:
            return
        with sessionmaker(bind=bind, future=True)() as db:
            report = run_emission(
                db, issuer, get_rate_sources(), datetime.now(UTC), payment_id=payment_id
            )
        logger.info("Factura del pago %s: %s", payment_id, report.summary())
    except Exception:  # noqa: BLE001 - una tarea de fondo no debe tumbar nada
        logger.exception("No se pudo emitir la factura del pago %s", payment_id)


def pesos_of(invoice: Invoice) -> Decimal | None:
    return pesos(invoice.cop_cents) if invoice.cop_cents else None


# ---------- Acciones del admin (§3.17, "Paso 5.4", punto 13) ----------

#: Desde donde se puede reintentar la emision.
RETRYABLE = (FAILED, PENDING, SENDING)
#: Desde donde se puede volver a consultar en el emisor.
REFRESHABLE = (ISSUED, REJECTED)


def reset_for_retry(invoice: Invoice) -> None:
    """Deja la factura lista para otro intento ya. NO hace commit.

    Una fallida que nunca llego al emisor (sin `provider_id`) se vuelve a
    preparar: asi toma los datos de facturacion corregidos. Una que pudo
    llegar (`sending`) conserva lo congelado, porque el reintento manda la
    misma llave y el emisor devuelve la que ya creo con esos datos.
    """
    if invoice.status not in RETRYABLE:
        raise ValueError(f"Una factura {invoice.status} no se reintenta")
    if invoice.status == FAILED and invoice.provider_id is None:
        invoice.prepared_at = None
    invoice.status = PENDING
    invoice.attempts = 0
    invoice.next_attempt_at = None
    invoice.waiting_reason = None
    invoice.last_error_codes = None
    invoice.last_error_message = None


def refresh(db: Session, issuer: InvoiceIssuer, invoice: Invoice, now: datetime) -> str:
    """Vuelve a consultar en el emisor una factura emitida o rechazada (por
    ejemplo, despues de corregirla en Siigo Nube). NO hace commit: el admin
    deja su fila de bitacora en la misma transaccion."""
    if invoice.status not in REFRESHABLE or invoice.provider_id is None:
        raise ValueError(f"Una factura {invoice.status} no se reconsulta")
    return _apply(db, issuer, invoice, issuer.fetch(invoice.provider_id), now)
