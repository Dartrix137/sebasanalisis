"""Admin: suscripciones y pagos (docs/PLATAFORMA_COMPLETA.md §4.3 y §4.8).

Reglas:

- Toda accion pide un motivo y escribe su fila en `admin_audit_log` en la misma
  transaccion que el cambio (`core/audit.record`).
- Un pago y su suscripcion solo los mueve `core/subscriptions.apply_transaction`,
  y solo con una transaccion que salio de reconsultar al proveedor. "Reconsultar"
  es exactamente eso: la misma funcion del webhook.
- Extender y cancelar una suscripcion estan en `core/subscription_admin`. No
  tocan ningun pago.
- Un reembolso se registra, no se ejecuta: se hace en el panel del proveedor
  (§10 n.º 7) y aqui no cambia el estado del pago ni el acceso.
- El acceso lo decide `core/access.has_access`; aqui no se repite.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select

from app.api.deps import AdminUser, DbSession
from app.api.presenters import admin_payment_responses, admin_subscription_response
from app.api.v1.billing import EmailSenderDep, PaymentProviderDep, queue_payment_emails
from app.api.v1.legal import client_ip
from app.core import audit, billing_emails, subscription_admin, subscriptions
from app.core.email import send_safely
from app.models import (
    AdminAuditLog,
    Invoice,
    Payment,
    PaymentEvent,
    PaymentRefund,
    Subscription,
    User,
)
from app.payments.base import PaymentProviderError
from app.schemas.admin import (
    AdminPaymentDetailResponse,
    AdminPaymentListResponse,
    AdminSubscriptionDetailResponse,
    AdminSubscriptionListResponse,
    AuditLogEntry,
    InvoiceResponse,
    PaymentEventResponse,
    PaymentRefundResponse,
    RecordRefundRequest,
    RequeryPaymentRequest,
    UpdateSubscriptionRequest,
)
from app.schemas.billing import PaymentKind, PaymentStatus, RenewalMode, SubscriptionStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]

# Cuantos pagos y cuantas filas de bitacora trae un detalle.
_DETAIL_PAYMENT_ROWS = 50
_DETAIL_AUDIT_ROWS = 20


def _pattern(text: str) -> str:
    """Los comodines que escriba el admin se buscan literales."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _audit_rows(db: DbSession, target_type: str, target_id: object) -> list[AuditLogEntry]:
    rows = db.scalars(
        select(AdminAuditLog)
        .where(AdminAuditLog.target_type == target_type, AdminAuditLog.target_id == str(target_id))
        .order_by(AdminAuditLog.created_at.desc())
        .limit(_DETAIL_AUDIT_ROWS)
    )
    return [AuditLogEntry.model_validate(r) for r in rows]


def _error(exc: subscriptions.SubscribeError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}
    )


# ---------- Suscripciones ----------


@router.get("/subscriptions", response_model=AdminSubscriptionListResponse)
def list_subscriptions(
    db: DbSession,
    admin: AdminUser,
    status_filter: Annotated[SubscriptionStatus | None, Query(alias="status")] = None,
    plan_id: UUID | None = None,
    renewal_mode: RenewalMode | None = None,
    query: Annotated[str | None, Query(max_length=255)] = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminSubscriptionListResponse:
    """Suscripciones por pagina, las mas recientes primero. Filtra en el servidor.

    Sin filtro de estado no trae las `pending`: son pagos que se abrieron y no se
    completaron, y se ven en Pagos. Con `status=pending` si.

    El estado es la columna tal cual. Lo pone el job de renovaciones cada hora,
    asi que una suscripcion recien vencida puede seguir `active` hasta la
    siguiente corrida; `in_force` de cada fila dice si el periodo sigue vigente.
    """
    filters = []
    if status_filter is not None:
        filters.append(Subscription.status == status_filter.value)
    else:
        filters.append(Subscription.status != "pending")
    if plan_id is not None:
        filters.append(Subscription.plan_id == plan_id)
    if renewal_mode is not None:
        filters.append(Subscription.renewal_mode == renewal_mode.value)
    text = (query or "").strip()
    if text:
        filters.append(User.email.ilike(_pattern(text), escape="\\"))

    base = select(Subscription).join(User, User.id == Subscription.user_id).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Subscription.created_at.desc(), Subscription.id).limit(limit).offset(offset)
    )
    now = datetime.now(UTC)
    return AdminSubscriptionListResponse(
        items=[admin_subscription_response(db, s, now) for s in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _subscription_detail(db: DbSession, subscription: Subscription) -> AdminSubscriptionDetailResponse:
    payments = db.scalars(
        select(Payment)
        .where(Payment.subscription_id == subscription.id)
        .order_by(Payment.created_at.desc(), Payment.id)
        .limit(_DETAIL_PAYMENT_ROWS)
    )
    return AdminSubscriptionDetailResponse(
        subscription=admin_subscription_response(db, subscription, datetime.now(UTC)),
        payments=admin_payment_responses(db, payments),
        audit=_audit_rows(db, "subscription", subscription.id),
    )


@router.get("/subscriptions/{subscription_id}", response_model=AdminSubscriptionDetailResponse)
def get_subscription(
    subscription_id: UUID, db: DbSession, admin: AdminUser
) -> AdminSubscriptionDetailResponse:
    subscription = db.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suscripción no encontrada")
    return _subscription_detail(db, subscription)


@router.patch("/subscriptions/{subscription_id}", response_model=AdminSubscriptionDetailResponse)
def update_subscription(
    subscription_id: UUID,
    payload: UpdateSubscriptionRequest,
    db: DbSession,
    admin: AdminUser,
    request: Request,
    background: BackgroundTasks,
    sender: EmailSenderDep,
) -> AdminSubscriptionDetailResponse:
    """Extiende el periodo (`extend`, con `days`), cancela la renovacion al
    final del periodo (`cancel_at_period_end`) o termina la suscripcion ahora
    (`cancel_now`). Pide motivo; al cliente se le avisa por correo."""
    action = payload.action.value
    if (action == "extend") != (payload.days is not None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Los días solo se indican al extender, y al extender son obligatorios",
        )
    existing = db.get(Subscription, subscription_id)
    had_renewal = (
        existing is not None
        and existing.renewal_mode == "automatic"
        and existing.status in ("active", "past_due")
    )
    try:
        change = subscription_admin.apply(
            db,
            admin=admin,
            subscription_id=subscription_id,
            action=action,  # type: ignore[arg-type]
            days=payload.days,
            reason=payload.reason.strip(),
            ip=client_ip(request),
            now=datetime.now(UTC),
        )
    except subscriptions.SubscribeError as exc:
        db.rollback()
        raise _error(exc) from exc

    subscription = change.subscription
    user = db.get(User, subscription.user_id)
    if user is not None:
        message = billing_emails.admin_change(
            db, user, subscription, action, had_renewal=had_renewal
        )
        background.add_task(send_safely, sender, message)
    return _subscription_detail(db, subscription)


# ---------- Pagos ----------


@router.get("/payments", response_model=AdminPaymentListResponse)
def list_payments(
    db: DbSession,
    admin: AdminUser,
    status_filter: Annotated[PaymentStatus | None, Query(alias="status")] = None,
    kind: PaymentKind | None = None,
    reversed_only: Annotated[bool, Query(alias="reversed")] = False,
    refunded_only: Annotated[bool, Query(alias="refunded")] = False,
    subscription_id: UUID | None = None,
    user_id: UUID | None = None,
    query: Annotated[str | None, Query(max_length=255)] = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminPaymentListResponse:
    """Cobros por pagina, los mas recientes primero, incluidos los que no se
    completaron. `query` busca por correo, referencia o id de la transaccion."""
    filters = []
    if status_filter is not None:
        filters.append(Payment.status == status_filter.value)
    if kind is not None:
        filters.append(Payment.kind == kind.value)
    if reversed_only:
        filters.append(Payment.reversed_at.is_not(None))
    if refunded_only:
        filters.append(select(PaymentRefund.id).where(PaymentRefund.payment_id == Payment.id).exists())
    if subscription_id is not None:
        filters.append(Payment.subscription_id == subscription_id)
    if user_id is not None:
        filters.append(Payment.user_id == user_id)
    text = (query or "").strip()
    if text:
        pattern = _pattern(text)
        filters.append(
            or_(
                User.email.ilike(pattern, escape="\\"),
                Payment.reference.ilike(pattern, escape="\\"),
                Payment.provider_transaction_id == text,
            )
        )

    base = select(Payment).outerjoin(User, User.id == Payment.user_id).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Payment.created_at.desc(), Payment.id).limit(limit).offset(offset)
    )
    return AdminPaymentListResponse(
        items=admin_payment_responses(db, rows), total=total, limit=limit, offset=offset
    )


def _get_payment(db: DbSession, payment_id: UUID) -> Payment:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado")
    return payment


def _payment_detail(db: DbSession, payment: Payment) -> AdminPaymentDetailResponse:
    # Los eventos que quedaron asociados al pago y, ademas, los que no (los de
    # firma invalida nunca se asocian: no se reconsultan) pero nombran en su
    # cuerpo la transaccion o la referencia de este pago. El cuerpo de un evento
    # sin firma valida no es confiable: aqui solo sirve para mostrarlo.
    transaction = PaymentEvent.raw_payload["data"]["transaction"]
    mentions = [transaction["reference"].astext == payment.reference]
    if payment.provider_transaction_id is not None:
        mentions.append(transaction["id"].astext == payment.provider_transaction_id)
    events = db.scalars(
        select(PaymentEvent)
        .where(
            or_(
                PaymentEvent.payment_id == payment.id,
                and_(PaymentEvent.payment_id.is_(None), or_(*mentions)),
            )
        )
        .order_by(PaymentEvent.created_at, PaymentEvent.id)
        .limit(100)
    )
    refunds = db.scalars(
        select(PaymentRefund)
        .where(PaymentRefund.payment_id == payment.id)
        .order_by(PaymentRefund.refunded_at, PaymentRefund.id)
    )
    invoice = db.scalar(select(Invoice).where(Invoice.payment_id == payment.id))
    [response] = admin_payment_responses(db, [payment])
    return AdminPaymentDetailResponse(
        payment=response,
        invoice=InvoiceResponse.model_validate(invoice) if invoice is not None else None,
        events=[
            PaymentEventResponse(
                id=e.id,
                provider_event_id=e.provider_event_id,
                event_type=e.event_type,
                status=e.status,
                signature_verified=e.signature_verified,
                processed_at=e.processed_at,
                created_at=e.created_at,
                linked=e.payment_id == payment.id,
                raw_payload=e.raw_payload,
            )
            for e in events
        ],
        refunds=[PaymentRefundResponse.model_validate(r) for r in refunds],
        audit=_audit_rows(db, "payment", payment.id),
    )


@router.get("/payments/{payment_id}", response_model=AdminPaymentDetailResponse)
def get_payment(payment_id: UUID, db: DbSession, admin: AdminUser) -> AdminPaymentDetailResponse:
    return _payment_detail(db, _get_payment(db, payment_id))


@router.post("/payments/{payment_id}/requery", response_model=AdminPaymentDetailResponse)
def requery_payment(
    payment_id: UUID,
    payload: RequeryPaymentRequest,
    db: DbSession,
    admin: AdminUser,
    request: Request,
    background: BackgroundTasks,
    sender: EmailSenderDep,
    provider: PaymentProviderDep,
) -> AdminPaymentDetailResponse:
    """Vuelve a preguntarle al proveedor por la transaccion del pago y aplica su
    respuesta con `apply_transaction`, la misma funcion del webhook.

    Un pago resuelto no se vuelve a resolver: reconsultarlo no da otro periodo.
    Lo unico que cambia un pago aprobado es que el proveedor lo reporte anulado.
    """
    payment = _get_payment(db, payment_id)
    if not provider.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No hay una pasarela de pagos configurada",
        )
    if payment.provider_transaction_id is None:
        # La documentacion del proveedor no describe una consulta por referencia.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Este pago no tiene una transacción en el proveedor: no hay nada que "
                "reconsultar. Si el cliente pagó, el evento del proveedor lo resolverá."
            ),
        )
    try:
        transaction = provider.fetch_transaction(payment.provider_transaction_id)
    except PaymentProviderError as exc:
        logger.warning("No se pudo reconsultar el pago %s desde el admin", payment.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El proveedor no respondió. Intenta de nuevo en unos minutos.",
        ) from exc
    if transaction is None or transaction.reference != payment.reference:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El proveedor no reporta esa transacción para este pago",
        )

    before = {"status": payment.status}
    reason = payload.reason.strip()
    ip = client_ip(request)

    def record(updated: Payment) -> None:
        audit.record(
            db,
            admin,
            action="payment.requery",
            target_type="payment",
            target_id=updated.id,
            before=before,
            after={"status": updated.status, "provider_status": transaction.status},
            reason=reason,
            ip=ip,
        )

    settlement = subscriptions.apply_transaction(
        db, transaction, datetime.now(UTC), before_commit=record
    )
    if settlement is not None:
        queue_payment_emails(db, settlement, background, sender)
    return _payment_detail(db, _get_payment(db, payment_id))


@router.post(
    "/payments/{payment_id}/refunds",
    response_model=AdminPaymentDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_refund(
    payment_id: UUID,
    payload: RecordRefundRequest,
    db: DbSession,
    admin: AdminUser,
    request: Request,
) -> AdminPaymentDetailResponse:
    """Registra un reembolso ya hecho en el panel del proveedor. No mueve el
    pago ni el acceso: si ademas hay que quitar el acceso, se cancela la
    suscripcion de inmediato."""
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado")
    if payment.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se registra un reembolso de un pago aprobado",
        )
    refunded_at = payload.refunded_at
    if refunded_at.tzinfo is None:
        refunded_at = refunded_at.replace(tzinfo=UTC)
    if refunded_at > datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La fecha del reembolso no puede ser futura",
        )
    already = db.scalar(
        select(func.coalesce(func.sum(PaymentRefund.amount_cents), 0)).where(
            PaymentRefund.payment_id == payment.id
        )
    ) or 0
    if already + payload.amount_cents > payment.amount_cents:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lo reembolsado no puede pasar de lo que se cobró",
        )

    refund = PaymentRefund(
        payment_id=payment.id,
        amount_cents=payload.amount_cents,
        currency=payment.currency,
        refunded_at=refunded_at,
        provider_refund_id=(payload.provider_refund_id or "").strip() or None,
        reason=payload.reason.strip(),
        admin_user_id=admin.id,
        admin_email=admin.email,
    )
    db.add(refund)
    db.flush()
    audit.record(
        db,
        admin,
        action="payment.refund.record",
        target_type="payment",
        target_id=payment.id,
        before={"refunded_cents": already},
        after={
            "refunded_cents": already + payload.amount_cents,
            "amount_cents": payload.amount_cents,
            "currency": payment.currency,
            "provider_refund_id": refund.provider_refund_id,
        },
        reason=refund.reason,
        ip=client_ip(request),
    )
    db.commit()
    return _payment_detail(db, payment)
