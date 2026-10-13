"""Planes, cotizacion, alta y estado del pago (docs/PLATAFORMA_COMPLETA.md §3.3 y §3.4).

El precio lo calcula siempre el servidor, con `app.billing.pricing.quote`. El
cliente manda el plan y, si tiene, un codigo: nunca un monto.

Este router NO exige `RequireAccess`: quien cotiza y paga es justo quien todavia
no tiene acceso. El pago en si ocurre en la pagina del proveedor; aqui se abre
(`POST /billing/subscriptions`) y se consulta como termino
(`GET /billing/payments/:id`). Lo que mueve una suscripcion es
`core/subscriptions.apply_transaction`, la misma funcion que usa el webhook.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.presenters import payment_response, subscription_response
from app.api.v1.legal import client_ip
from app.billing import pricing
from app.billing.coupon_codes import normalize_code
from app.billing.pricing import CouponRejection
from app.core import rate_limit, subscriptions
from app.core.config import get_settings
from app.core.email import EmailSender, get_email_sender, send_safely
from app.core.subscriptions import COUPON_MESSAGES, Settlement, SubscribeError, coupon_terms
from app.emails import build_email
from app.models import Coupon, Payment, Plan, User
from app.payments.base import PaymentProvider, PaymentProviderError, get_payment_provider
from app.schemas.billing import (
    BillingAvailabilityResponse,
    PaymentListResponse,
    PaymentResponse,
    PlanResponse,
    QuoteCoupon,
    QuoteRequest,
    QuoteResponse,
    SubscribeRequest,
    SubscribeResponse,
    SubscriptionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])

EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
PaymentProviderDep = Annotated[PaymentProvider, Depends(get_payment_provider)]

_MINUTE = 60
_HOUR = 60 * _MINUTE

_TOO_MANY_CODES = "Demasiados intentos con códigos. Intenta de nuevo más tarde."
_TOO_MANY_PAYMENTS = "Demasiados intentos de pago. Intenta de nuevo más tarde."


def _limit_coupon_attempts(user: User, request: Request) -> None:
    """Limite de intentos con codigo, al cotizar y al pagar (§5.7.1).

    Sin el, serviria para adivinar codigos: la respuesta dice si existe. Por
    cuenta y por IP, porque crear cuentas es gratis. Un intento sin codigo no
    cuenta. En memoria, como el resto de `core/rate_limit`.
    """
    if not get_settings().rate_limit_enabled:
        return
    allowed = rate_limit.hit(
        f"quote-coupon:user:{user.id}", limit=10, window=15 * _MINUTE
    ) and rate_limit.hit(f"quote-coupon:ip:{client_ip(request)}", limit=30, window=_HOUR)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_TOO_MANY_CODES
        )


def _frontend_url(path: str) -> str:
    return f"{get_settings().frontend_base_url.rstrip('/')}{path}"


@router.get("/plans", response_model=list[PlanResponse])
def list_plans(db: DbSession) -> list[Plan]:
    """Los planes que se ofrecen. Publico."""
    return list(
        db.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.sort_order, Plan.code))
    )


@router.get("/billing/availability", response_model=BillingAvailabilityResponse)
def availability(provider: PaymentProviderDep) -> BillingAvailabilityResponse:
    """Si se puede pagar. Publico: /planes lo usa para encender el boton."""
    return BillingAvailabilityResponse(enabled=provider.enabled)


@router.post("/billing/quote", response_model=QuoteResponse)
def quote(
    payload: QuoteRequest, user: CurrentUser, db: DbSession, request: Request
) -> QuoteResponse:
    """Cuanto se cobraria por un periodo del plan, con o sin cupon.

    Un cupon que no aplica no es un error: la cotizacion sale por el precio
    completo y dice por que. No reserva ni redime nada.
    """
    code = normalize_code(payload.coupon_code or "")
    if code:
        _limit_coupon_attempts(user, request)

    plan = db.get(Plan, payload.plan_id)
    # Un plan desactivado ya no se ofrece: para quien cotiza, no existe.
    if plan is None or not plan.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado")
    plan_price = pricing.PlanPrice(
        id=str(plan.id), price_cents=plan.price_cents, currency=plan.currency
    )

    coupon = db.scalar(select(Coupon).where(Coupon.code == code)) if code else None
    terms = coupon_terms(db, coupon, user) if coupon is not None else None
    result = pricing.quote(plan_price, terms, datetime.now(UTC))

    quote_coupon: QuoteCoupon | None = None
    if code:
        reason = CouponRejection.not_found if coupon is None else result.coupon_rejection
        quote_coupon = QuoteCoupon(
            code=code,
            applied=reason is None,
            reason=reason,
            message=COUPON_MESSAGES[reason] if reason is not None else None,
        )
    return QuoteResponse(
        plan_id=plan.id,
        subtotal_cents=result.subtotal_cents,
        discount_cents=result.discount_cents,
        total_cents=result.total_cents,
        currency=result.currency,
        coupon=quote_coupon,
    )


# ---------- Alta y pago manual de un periodo ----------


@router.post(
    "/billing/subscriptions",
    response_model=SubscribeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def subscribe(
    payload: SubscribeRequest,
    user: CurrentUser,
    db: DbSession,
    request: Request,
    provider: PaymentProviderDep,
) -> SubscribeResponse:
    """Abre el pago manual de un periodo y devuelve a donde ir a pagarlo.

    No tokeniza nada ni recibe datos de pago: el cliente paga en la pagina del
    proveedor. Exige correo confirmado y documentos legales aceptados. El total
    sale de `pricing.quote`; cualquier monto que mande el cliente se ignora.

    Responde 202: la suscripcion no queda activa hasta que el proveedor
    confirme el pago (`GET /billing/payments/:id`).
    """
    if get_settings().rate_limit_enabled and not rate_limit.hit(
        f"subscribe:user:{user.id}", limit=10, window=15 * _MINUTE
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_TOO_MANY_PAYMENTS
        )
    if normalize_code(payload.coupon_code or ""):
        _limit_coupon_attempts(user, request)

    try:
        started = subscriptions.start_payment(
            db,
            user=user,
            plan_id=payload.plan_id,
            coupon_code=payload.coupon_code,
            provider=provider,
            now=datetime.now(UTC),
        )
    except SubscribeError as exc:
        db.rollback()
        detail: dict[str, str] = {"code": exc.code, "message": exc.message}
        if exc.coupon_reason is not None:
            detail["reason"] = exc.coupon_reason.value
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc

    payment = started.payment
    checkout_url = provider.checkout_url(
        reference=payment.reference,
        amount_cents=payment.amount_cents,
        currency=payment.currency,
        # El proveedor devuelve aqui al cliente y le agrega `?id=` con el id de
        # su transaccion. Es solo informativo: el resultado se reconsulta.
        redirect_url=_frontend_url(f"/pago/{payment.id}"),
        customer_email=user.email,
    )
    return SubscribeResponse(
        payment_id=payment.id,
        checkout_url=checkout_url,
        subtotal_cents=started.subtotal_cents,
        discount_cents=payment.discount_cents,
        total_cents=payment.amount_cents,
        currency=payment.currency,
    )


def queue_payment_emails(
    db: DbSession, settlement: Settlement, background: BackgroundTasks, sender: EmailSender
) -> None:
    """Bienvenida al activar y recibo de cada cobro aprobado (§3.8).

    Solo cuando ESTA llamada resolvio el pago: un evento repetido no repite el
    correo.
    """
    payment = settlement.payment
    if not settlement.changed or payment.status != "approved" or payment.user_id is None:
        return
    user = db.get(User, payment.user_id)
    if user is None:
        return
    context = {
        "display_name": user.display_name,
        "plan_name": payment.plan.name,
        "amount_cents": payment.amount_cents,
        "discount_cents": payment.discount_cents,
        "currency": payment.currency,
        "paid_at": payment.resolved_at,
        "period_start": payment.period_start,
        "period_end": payment.period_end,
        "reference": payment.reference,
    }
    if settlement.activated:
        background.add_task(
            send_safely,
            sender,
            build_email(
                "subscription_welcome",
                to=user.email,
                url=_frontend_url("/dashboard"),
                **context,
            ),
        )
    background.add_task(
        send_safely,
        sender,
        build_email("payment_receipt", to=user.email, url=_frontend_url("/cuenta"), **context),
    )


@router.get("/billing/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: UUID,
    user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
    sender: EmailSenderDep,
    provider: PaymentProviderDep,
    transaction_id: Annotated[str | None, Query(max_length=255)] = None,
) -> PaymentResponse:
    """Como va un pago de la cuenta. La pantalla que espera el resultado la
    consulta hasta que salga de `pending`.

    Si sigue pendiente se reconsulta la transaccion al proveedor, por si el
    webhook se demoro (§3.4). `transaction_id` es el id que el proveedor le
    agrega a la URL de regreso: viene del navegador, asi que solo sirve para
    saber que reconsultar. Lo que se aplica es la respuesta del proveedor, y
    solo si su referencia es la de este pago.
    """
    payment = db.get(Payment, payment_id)
    if payment is None or payment.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado")

    lookup_id = payment.provider_transaction_id or transaction_id
    if payment.status == "pending" and provider.enabled and lookup_id and _may_requery(user):
        reference = payment.reference
        try:
            transaction = provider.fetch_transaction(lookup_id)
        except PaymentProviderError:
            # El pago sigue pendiente; lo resolvera el webhook o la proxima consulta.
            logger.warning("No se pudo reconsultar el pago %s", payment_id, exc_info=True)
            transaction = None
        if transaction is not None and transaction.reference == reference:
            settlement = subscriptions.apply_transaction(db, transaction, datetime.now(UTC))
            if settlement is not None:
                queue_payment_emails(db, settlement, background, sender)
                payment = settlement.payment
    return payment_response(payment)


def _may_requery(user: User) -> bool:
    """Tope de reconsultas al proveedor por cuenta: la pantalla consulta cada
    pocos segundos y no hace falta trasladarle todas."""
    if not get_settings().rate_limit_enabled:
        return True
    return rate_limit.hit(f"payment-requery:user:{user.id}", limit=30, window=_MINUTE)


@router.get("/billing/payments", response_model=PaymentListResponse)
def list_payments(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaymentListResponse:
    """El historial de pagos de la cuenta, lo mas reciente primero.

    No trae los pagos que siguen `pending`: casi todos son intentos que no se
    completaron, y uno que de verdad esta en proceso tiene su propia pantalla.
    """
    filters = (Payment.user_id == user.id, Payment.status != "pending")
    total = db.scalar(select(func.count()).select_from(Payment).where(*filters)) or 0
    rows = db.scalars(
        select(Payment)
        .where(*filters)
        .order_by(Payment.created_at.desc(), Payment.id)
        .limit(limit)
        .offset(offset)
    )
    return PaymentListResponse(
        items=[payment_response(p) for p in rows], total=total, limit=limit, offset=offset
    )


@router.get("/billing/subscription", response_model=SubscriptionResponse | None)
def get_subscription(user: CurrentUser, db: DbSession) -> SubscriptionResponse | None:
    """La suscripcion de la cuenta, o null si nunca pago una."""
    found = subscriptions.current_subscription(db, user.id)
    return subscription_response(found, datetime.now(UTC)) if found is not None else None
