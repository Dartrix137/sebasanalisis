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
de configuracion frena la corrida entera. `cancelled`: no se emite, porque el
pago se reembolso entero o se anulo antes (`core/credit_notes.py`).

**La espera de la contadora** (2026-11-11): "que no se realice la factura de
la venta hasta que no este la aceptacion del pago". La factura ya nace solo con
el pago aprobado y reconsultado; ademas, `INVOICE_HOLD_HOURS` la hace esperar
ese tiempo despues de la aprobacion. Un reembolso o una anulacion en ese plazo
la cancela, sin nota credito. Con 0 (por defecto) sale enseguida.

La misma corrida emite las notas credito (`core/credit_notes.py`), despues de
las facturas: una factura que acaba de quedar aceptada deja salir su nota.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.billing import checkout_text, fx
from app.billing.invoice_document import FrozenRates, idempotency_key, observations, pesos
from app.core import billing_profiles
from app.core.config import get_settings
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
from app.models import BillingProfile, CreditNote, Invoice, Payment, Plan, User

logger = logging.getLogger(__name__)

PENDING = "pending"
SENDING = "sending"
ISSUED = "issued"
ACCEPTED = "accepted"
REJECTED = "rejected"
FAILED = "failed"
CANCELLED = "cancelled"

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
WAITING_HOLD = "payment_hold"


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
    # El comprador se copia ya, con el pago aprobado: si la cuenta se elimina
    # antes de preparar la factura, sus datos de facturacion se borran con
    # ella y el pago se quedaria sin factura (auditoria del 2026-11-12,
    # decidido por el usuario el 2026-11-13). `prepare` vuelve a copiarlo de
    # los datos vigentes si la cuenta sigue: asi un reintento del admin toma
    # lo que el cliente haya corregido.
    profile = billing_profiles.get(db, payment.user_id) if payment.user_id else None
    user = db.get(User, payment.user_id) if payment.user_id else None
    if profile is not None and user is not None:
        _copy_buyer(invoice, profile, user)
    db.add(invoice)
    return invoice


def _copy_buyer(invoice: Invoice, profile: BillingProfile, user: User) -> None:
    invoice.buyer_first_names = profile.first_names
    invoice.buyer_last_names = profile.last_names
    invoice.buyer_id_type = profile.id_type
    invoice.buyer_id_number = profile.id_number
    invoice.buyer_email = user.email
    invoice.buyer_country_code = profile.country_code
    invoice.buyer_state_code = profile.state_code
    invoice.buyer_city_code = profile.city_code
    invoice.buyer_address = profile.address


def _has_buyer(invoice: Invoice) -> bool:
    """La factura ya trae al comprador copiado al aprobar el pago."""
    return bool(invoice.buyer_id_type and invoice.buyer_id_number and invoice.buyer_email)


@dataclass
class EmissionReport:
    prepared: int = 0
    issued: int = 0
    accepted: int = 0
    rejected: int = 0
    failed: int = 0
    waiting: int = 0
    retried: int = 0
    credit_notes_sent: int = 0
    credit_notes_failed: int = 0
    #: Por que se detuvo la corrida, si se detuvo (configuracion o caida).
    stopped: str | None = None
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"preparadas={self.prepared} emitidas={self.issued} aceptadas={self.accepted}"
            f" rechazadas={self.rejected} fallidas={self.failed} en_espera={self.waiting}"
            f" a_reintentar={self.retried} notas_credito={self.credit_notes_sent}"
            f" notas_fallidas={self.credit_notes_failed}"
            + (f" detenida={self.stopped}" if self.stopped else "")
        )


# ---------- Preparar: congelar lo que lleva ----------


def hold_period() -> timedelta:
    """La espera despues de aprobado el pago (`INVOICE_HOLD_HOURS`)."""
    return timedelta(hours=get_settings().invoice_hold_hours)


def prepare(
    db: Session,
    invoice: Invoice,
    sources: RateSources,
    now: datetime,
    hold: timedelta | None = None,
) -> bool:
    """Congela la factura si todavia no lo esta. True si quedo lista para
    enviar; si no, deja el motivo en `waiting_reason`. NO hace commit."""
    if invoice.prepared_at is not None:
        return True
    payment = db.get(Payment, invoice.payment_id)
    if payment is None or payment.status != "approved":
        invoice.waiting_reason = WAITING_PAYMENT
        return False
    hold = hold_period() if hold is None else hold
    if hold and payment.resolved_at is not None and payment.resolved_at + hold > now:
        invoice.waiting_reason = WAITING_HOLD
        invoice.next_attempt_at = payment.resolved_at + hold
        return False
    profile = billing_profiles.get(db, payment.user_id) if payment.user_id else None
    user = db.get(User, payment.user_id) if payment.user_id else None
    # Sin la cuenta (o sin sus datos de facturacion) sirve la copia hecha al
    # aprobar el pago; las facturas anteriores a esa copia no la tienen.
    if (profile is None or user is None) and not _has_buyer(invoice):
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
    if profile is not None and user is not None:
        _copy_buyer(invoice, profile, user)
    if invoice.idempotency_key is None:
        # La primera vez, el id de la factura. Un reintento del admin sobre una
        # fallida ya dejo una llave nueva (`reset_for_retry`).
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


def _record_error(doc: Invoice | CreditNote, exc: IssuerError) -> None:
    doc.last_error_codes = exc.codes or None
    # El texto completo, solo a la base; el log y GlitchTip, `str(exc)`.
    doc.last_error_message = exc.detail[:500]


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
    # Draft o Sending (los otros dos estados ante la DIAN, segun soporte de
    # Siigo), o uno que no conocemos: espera y se vuelve a consultar.
    invoice.status = ISSUED
    return ISSUED


def attempt(
    db: Session,
    doc: Invoice | CreditNote,
    now: datetime,
    call: Callable[[], IssuedInvoice],
    apply: Callable[[IssuedInvoice], str],
    label: str,
) -> str:
    """Un intento de envio de una factura o una nota credito. Confirma en la
    base antes y despues de llamar al emisor."""
    doc.status = SENDING
    doc.attempts += 1
    doc.sent_at = now
    doc.issue_date = fx.operation_date(now)
    # Otra corrida no lo toca mientras sale; si el proceso muere aqui, el
    # reintento manda la misma llave.
    doc.next_attempt_at = now + _SENDING_GUARD
    db.commit()
    try:
        result = call()
    except IssuerTransient as exc:
        _record_error(doc, exc)
        if doc.attempts >= MAX_ATTEMPTS:
            doc.status = FAILED
            logger.error("%s %s: sin respuesta de Siigo tras %s intentos",
                         label, doc.id, doc.attempts)
            db.commit()
            return FAILED
        doc.status = SENDING if exc.uncertain else PENDING
        wait = _BACKOFF[min(doc.attempts - 1, len(_BACKOFF) - 1)]
        if exc.retry_after:
            wait = max(wait, timedelta(seconds=exc.retry_after))
        doc.next_attempt_at = now + wait
        db.commit()
        return "retry"
    except IssuerMisconfigured as exc:
        _record_error(doc, exc)
        # No es culpa de este documento: vuelve a esperar, sin gastar el intento.
        doc.status = PENDING
        doc.attempts -= 1
        doc.next_attempt_at = None
        db.commit()
        raise
    except IssuerRejected as exc:
        _record_error(doc, exc)
        doc.status = FAILED
        doc.next_attempt_at = None
        logger.error("%s %s: Siigo rechazo los datos (%s)", label, doc.id, exc.codes or "-")
        db.commit()
        return FAILED
    state = apply(result)
    db.commit()
    return state


def _send(db: Session, issuer: InvoiceIssuer, invoice: Invoice, now: datetime) -> str:
    """Un intento de envio de la factura."""
    return attempt(
        db,
        invoice,
        now,
        lambda: issuer.issue(_draft(invoice, now)),
        lambda result: _apply(db, issuer, invoice, result, now),
        "Factura",
    )


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
    hold: timedelta | None = None,
) -> EmissionReport:
    """Prepara y emite las facturas que tocan, y reconsulta las que esperan a
    la DIAN; despues, lo mismo con las notas credito. Con `payment_id`, solo
    las de ese pago (la tarea de fondo y las acciones del admin)."""
    from app.core import credit_notes

    report = EmissionReport()
    if not issuer.enabled:
        report.stopped = "disabled"
        return report
    hold = hold_period() if hold is None else hold

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
    notes = credit_notes.due(db, now, limit=limit, payment_id=payment_id)
    if not due_ids and not issued_ids and not notes:
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
            if not prepare(db, invoice, sources, now, hold):
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

    # Las notas credito se buscan otra vez: una factura que acaba de quedar
    # aceptada deja salir la suya en esta misma corrida.
    try:
        credit_notes.process(
            db, issuer, now, credit_notes.due(db, now, limit=limit, payment_id=payment_id), report
        )
    except IssuerMisconfigured as exc:
        report.stopped = f"config: {exc}"
        logger.error("Emision de notas credito detenida: %s", exc)
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

    Una fallida se vuelve a preparar, para tomar los datos de facturacion
    corregidos, y sale con una llave de idempotencia nueva: soporte de Siigo
    (2026-11-09) dice que una llave usada queda usada para siempre, "aunque se
    borre el documento", asi que con la misma Siigo devolveria lo de antes.
    Una fallida que si llego a Siigo (el total no cuadro) se reintenta solo si
    no tiene CUFE, y despues de anularla en Siigo Nube: si no, quedarian dos.
    Con CUFE, la DIAN ya la acepto y se corrige con nota credito.

    Una que pudo llegar (`sending`) conserva lo congelado y su llave: el
    emisor devuelve la que ya creo con esos datos.
    """
    if invoice.status not in RETRYABLE:
        raise ValueError(f"Una factura {invoice.status} no se reintenta")
    if invoice.status == FAILED:
        if invoice.cufe:
            raise ValueError("La DIAN ya acepto esa factura: se corrige con nota credito")
        invoice.prepared_at = None
        invoice.idempotency_key = idempotency_key(uuid.uuid4())
        invoice.provider_id = None
        invoice.provider_name = None
        invoice.provider_total = None
        invoice.stamp_status = None
        invoice.mail_status = None
        invoice.dian_errors = None
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
