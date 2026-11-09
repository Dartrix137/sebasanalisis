"""Planes, cotizacion, alta y estado del pago (docs/PLATAFORMA_COMPLETA.md §3.3 y §3.4).

El precio lo calcula siempre el servidor, con `app.billing.pricing.quote`. El
cliente manda el plan y, si tiene, un codigo: nunca un monto.

Tambien la gestion de la suscripcion ya pagada: cancelar, reanudar, cambiar el
medio de pago y pasar de un modo de pago al otro (§3.6).

Este router NO exige `RequireAccess`: quien cotiza y paga es justo quien todavia
no tiene acceso. El pago en si ocurre en la pagina del procesador; aqui se
listan los medios de pago (`GET /billing/payment-methods`), se abre el pago
(`POST /billing/subscriptions`), se entrega una sola vez la pagina con la que el
navegador sigue a la pasarela (`GET /billing/checkout/:token`) y se consulta
como termino (`GET /billing/payments/:id`). Lo que mueve una suscripcion es
`core/subscriptions.apply_transaction`, la misma funcion que usa el webhook.
"""

import logging
from datetime import UTC, datetime
from html import escape
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.api.presenters import payment_response, subscription_response
from app.api.v1.legal import client_ip
from app.billing import pricing
from app.billing.coupon_codes import normalize_code
from app.billing.pricing import CouponRejection
from app.core import (
    billing_emails,
    checkout_pages,
    invoices,
    rate_limit,
    renewals,
    subscriptions,
)
from app.core.config import get_settings
from app.core.email import EmailSender, get_email_sender, send_safely
from app.core.subscriptions import (
    COUPON_MESSAGES,
    CheckoutChoice,
    CheckoutUrls,
    Settlement,
    SourceInput,
    SubscribeError,
    coupon_terms,
)
from app.models import Coupon, Payment, Plan, User
from app.payments.base import (
    BuyerField,
    PaymentProvider,
    PaymentProviderError,
    get_payment_provider,
)
from app.schemas.billing import (
    BillingAvailabilityResponse,
    BuyerData,
    BuyerFieldName,
    CheckoutMethodResponse,
    PaymentListResponse,
    PaymentMethodRequest,
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


def _api_url(path: str) -> str:
    return f"{get_settings().api_public_url.rstrip('/')}{path}"


# Los nombres de los datos del comprador en la API y en la pasarela.
_BUYER_FIELDS: dict[BuyerFieldName, BuyerField] = {
    BuyerFieldName.first_name: "firstName",
    BuyerFieldName.last_name: "lastName",
    BuyerFieldName.personal_id: "personalId",
    BuyerFieldName.phone: "phone",
}
_BUYER_NAMES: dict[BuyerField, BuyerFieldName] = {v: k for k, v in _BUYER_FIELDS.items()}


def _buyer(data: BuyerData | None) -> dict[BuyerField, str]:
    if data is None:
        return {}
    values = data.model_dump()
    return {
        provider_name: values[api_name.value]
        for api_name, provider_name in _BUYER_FIELDS.items()
        if values.get(api_name.value)
    }


def _checkout_urls(payment: Payment) -> CheckoutUrls:
    """A donde vuelve el navegador al terminar y a donde avisa la pasarela.
    La pantalla de regreso consulta el pago: lo que diga la URL no cuenta."""
    return CheckoutUrls(
        url_ok=_frontend_url(f"/pago/{payment.id}"),
        url_ko=_frontend_url(f"/pago/{payment.id}"),
        notification_url=_api_url("/webhooks/payments"),
    )


@router.get("/plans", response_model=list[PlanResponse])
def list_plans(db: DbSession) -> list[Plan]:
    """Los planes que se ofrecen. Publico."""
    return list(
        db.scalars(
            select(Plan)
            .options(selectinload(Plan.games))
            .where(Plan.active.is_(True))
            .order_by(Plan.sort_order, Plan.code)
        )
    )


@router.get("/billing/availability", response_model=BillingAvailabilityResponse)
def availability(provider: PaymentProviderDep) -> BillingAvailabilityResponse:
    """Si se puede pagar, y como se guarda un medio de pago. Publico: /planes
    lo usa para encender el boton."""
    tokenizer = provider.tokenizer() if provider.enabled else None
    return BillingAvailabilityResponse(
        enabled=provider.enabled,
        tokenizer=tokenizer.kind if tokenizer else None,  # type: ignore[arg-type]
    )


@router.get("/billing/payment-methods", response_model=list[CheckoutMethodResponse])
def payment_methods(
    user: CurrentUser,
    provider: PaymentProviderDep,
    country: Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")] = None,
) -> list[CheckoutMethodResponse]:
    """Los medios de pago que ofrece la pasarela en un pais, para la pantalla
    de pago. Sin pais, los que no dependen del pais. Exige sesion: la consulta
    sale con las llaves de la pasarela, y no se le presta a cualquiera."""
    if not provider.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "payments_unavailable", "message": "El pago todavía no está disponible."},
        )
    if get_settings().rate_limit_enabled and not rate_limit.hit(
        f"payment-methods:user:{user.id}", limit=30, window=_MINUTE
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_TOO_MANY_PAYMENTS
        )
    try:
        methods = provider.payment_methods(country)
    except PaymentProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=_PROVIDER_UNAVAILABLE
        ) from exc
    return [
        CheckoutMethodResponse(
            key=m.key,
            name=m.name,
            logo_url=m.logo_url,
            min_cents=m.min_cents,
            max_cents=m.max_cents,
            currency=m.currency,
            fields=[_BUYER_NAMES[f] for f in m.fields],
        )
        for m in methods
    ]


def _require_tokenizer(provider: PaymentProvider) -> None:
    if not provider.enabled or provider.tokenizer() is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "automatic_unavailable",
                "message": "La renovación automática todavía no está disponible.",
            },
        )


_PROVIDER_UNAVAILABLE = {
    "code": "provider_unavailable",
    "message": "No pudimos consultar al procesador de pagos. Intenta de nuevo.",
}


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
    background: BackgroundTasks,
    sender: EmailSenderDep,
) -> SubscribeResponse:
    """Abre el pago de un periodo.

    Pago manual (`renewal_mode: manual`): crea la orden en la pasarela con el
    medio, el pais y los datos del comprador que mando el cliente, y devuelve
    el enlace de un solo uso de la pagina de pago (`checkout_url`). Los datos
    del comprador van a la pasarela y no se guardan. No se tokeniza nada.

    Renovacion automatica (`automatic`): recibe el token que el procesador le
    dio al navegador, guarda el medio de pago en el proveedor y le hace el
    primer cobro. Por aqui nunca pasan datos de tarjeta, y solo se guardan la
    referencia del proveedor, la marca y los ultimos cuatro digitos.

    En los dos casos exige correo confirmado y documentos legales aceptados, y
    el total sale de `billing/pricing`: cualquier monto que mande el cliente se
    ignora. Responde 202: la suscripcion no queda activa hasta que el proveedor
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
            renewal_mode=payload.renewal_mode.value,
            source=(
                SourceInput(
                    type=payload.payment_source_type or "",
                    token=payload.payment_source_token or "",
                )
                if payload.renewal_mode.value == "automatic"
                else None
            ),
            choice=(
                CheckoutChoice(
                    method=payload.payment_method or "",
                    country=payload.country,
                    buyer=_buyer(payload.buyer),
                )
                if payload.renewal_mode.value == "manual"
                else None
            ),
            urls=_checkout_urls,
        )
    except SubscribeError as exc:
        db.rollback()
        raise _http_error(exc) from exc

    payment = started.payment
    if started.settlement is not None:
        # El cobro al medio guardado ya se envio; puede que ya este resuelto.
        queue_payment_emails(db, started.settlement, background, sender)
        return SubscribeResponse(
            payment_id=payment.id,
            checkout_url=None,
            subtotal_cents=started.subtotal_cents,
            discount_cents=payment.discount_cents,
            total_cents=payment.amount_cents,
            currency=payment.currency,
        )
    assert started.checkout is not None
    # La pagina se entrega una sola vez (core/checkout_pages.py).
    token = checkout_pages.put(started.checkout.html, return_url=_frontend_url("/"))
    checkout_url = _api_url(f"/billing/checkout/{token}")
    return SubscribeResponse(
        payment_id=payment.id,
        checkout_url=checkout_url,
        subtotal_cents=started.subtotal_cents,
        discount_cents=payment.discount_cents,
        total_cents=payment.amount_cents,
        currency=payment.currency,
    )


_USED_LINK_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Enlace de pago usado</title></head>
<body style="font-family:sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem;">
<h1>Este enlace de pago ya se usó o venció</h1>
<p>Por seguridad, la página de pago se abre una sola vez. Si no terminaste de
pagar, vuelve a los planes y abre el pago de nuevo.</p>
<p><a href="{planes}">Volver a los planes</a></p>
</body></html>"""


@router.get("/billing/checkout/{token}", response_class=HTMLResponse, include_in_schema=False)
def checkout_page(token: Annotated[str, Path(min_length=20, max_length=100)]) -> HTMLResponse:
    """La pagina de pago, una sola vez (core/checkout_pages.py).

    Sin sesion: es una navegacion del navegador, que no lleva el token de
    acceso; el enlace mismo es la credencial. Lleva su propia CSP, que deja
    correr solo los scripts de la pagina que mando la pasarela. Una recarga, o
    el enlace pasados diez minutos, muestra como volver a empezar.
    """
    page = checkout_pages.take(token)
    headers = {"Cache-Control": "no-store"}
    if page is None:
        return HTMLResponse(
            _USED_LINK_PAGE.format(planes=escape(_frontend_url("/planes"), quote=True)),
            status_code=status.HTTP_410_GONE,
            headers={
                **headers,
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            },
        )
    return HTMLResponse(
        page.html, headers={**headers, "Content-Security-Policy": page.csp}
    )


def _http_error(exc: SubscribeError) -> HTTPException:
    detail: dict[str, str] = {"code": exc.code, "message": exc.message}
    if exc.coupon_reason is not None:
        detail["reason"] = exc.coupon_reason.value
    return HTTPException(status_code=exc.status_code, detail=detail)


def queue_payment_emails(
    db: DbSession, settlement: Settlement, background: BackgroundTasks, sender: EmailSender
) -> None:
    """Encola lo que sigue a un pago que esta llamada resolvio: los correos
    (§3.8: recibo, bienvenida o aviso de cobro fallido, armados por
    `core/billing_emails`) y, si quedo aprobado, la emision de su factura
    (§3.17, "Paso 5.4"), fuera de la transaccion del pago."""
    for message in billing_emails.payment_emails(db, settlement):
        background.add_task(send_safely, sender, message)
    if settlement.changed and settlement.payment.status == "approved":
        background.add_task(invoices.emit_in_background, db.get_bind(), settlement.payment.id)


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

    # Una pasarela sin id de transaccion propio se reconsulta con la referencia
    # del pago. Con ella, un rechazo tambien se reconsulta: puede pasar a
    # aprobado si el comprador reintento (manual V2 de Tipster Page, §10).
    if provider.lookup_by_reference:
        lookup_id: str | None = payment.reference
        open_statuses = ("pending", "declined")
    else:
        lookup_id = payment.provider_transaction_id or transaction_id
        open_statuses = ("pending",)
    if (
        payment.status in open_statuses
        and provider.enabled
        and lookup_id
        and _may_requery(user)
    ):
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
    return subscription_response(db, found, datetime.now(UTC)) if found is not None else None


@router.post("/billing/subscription/cancel", response_model=SubscriptionResponse)
def cancel_subscription(
    user: CurrentUser, db: DbSession, background: BackgroundTasks, sender: EmailSenderDep
) -> SubscriptionResponse:
    """Cancela la renovacion automatica (§3.6). La cuenta conserva el acceso
    hasta que termine el periodo que ya pago, y no se le vuelve a cobrar."""
    now = datetime.now(UTC)
    try:
        subscription = subscriptions.cancel(db, user, now)
    except SubscribeError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    background.add_task(
        send_safely, sender, billing_emails.subscription_canceled(user, subscription)
    )
    return subscription_response(db, subscription, now)


@router.post("/billing/subscription/resume", response_model=SubscriptionResponse)
def resume_subscription(user: CurrentUser, db: DbSession) -> SubscriptionResponse:
    """Revierte la cancelacion antes del vencimiento: la suscripcion vuelve a
    renovarse sola con el medio de pago que tenia guardado."""
    now = datetime.now(UTC)
    try:
        subscription = subscriptions.resume(db, user, now)
    except SubscribeError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    return subscription_response(db, subscription, now)


# ---------- Medio de pago y modo de pago (§3.6 y §3.10) ----------


@router.put("/billing/payment-method", response_model=SubscriptionResponse)
def set_payment_method(
    payload: PaymentMethodRequest,
    user: CurrentUser,
    db: DbSession,
    provider: PaymentProviderDep,
    background: BackgroundTasks,
    sender: EmailSenderDep,
) -> SubscriptionResponse:
    """Guarda un medio de pago en la suscripcion vigente, que queda renovandose
    sola con el: cambia el medio guardado, pasa de pago manual a renovacion
    automatica, o reanuda una renovacion cancelada con otro medio.

    No cobra nada: el periodo vigente ya esta pagado. Si la suscripcion tiene
    un cobro sin aprobar, se reintenta ya con el medio nuevo. Por aqui nunca
    pasan datos de tarjeta: solo el token que el procesador le dio al navegador.
    """
    if get_settings().rate_limit_enabled and not rate_limit.hit(
        f"payment-method:user:{user.id}", limit=10, window=15 * _MINUTE
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_TOO_MANY_PAYMENTS
        )
    now = datetime.now(UTC)
    try:
        change = subscriptions.set_payment_source(
            db,
            user=user,
            provider=provider,
            source=SourceInput(
                type=payload.payment_source_type,
                token=payload.payment_source_token,
            ),
            now=now,
        )
    except SubscribeError as exc:
        db.rollback()
        raise _http_error(exc) from exc

    subscription = change.subscription
    amount = pricing.renewal_quote(
        subscription.price_cents,
        subscription.currency,
        subscriptions.renewal_discount(db, subscription),
    ).total_cents
    background.add_task(
        send_safely,
        sender,
        billing_emails.payment_method_updated(
            user, subscription, amount, activated_renewal=change.activated_renewal
        ),
    )
    if change.retry_due:
        report = renewals.retry_now(db, provider, subscription, user, now)
        for message in report.emails:
            background.add_task(send_safely, sender, message)
        db.refresh(subscription)
    return subscription_response(db, subscription, now)


@router.delete("/billing/payment-method", response_model=SubscriptionResponse)
def remove_payment_method(
    user: CurrentUser, db: DbSession, background: BackgroundTasks, sender: EmailSenderDep
) -> SubscriptionResponse:
    """Pasa la renovacion automatica a pago manual: deja de guardarse el medio
    de pago y no se cobra mas. La cuenta conserva el acceso hasta que termine
    el periodo que ya pago, y paga el siguiente cuando quiera."""
    now = datetime.now(UTC)
    try:
        subscription = subscriptions.switch_to_manual(db, user, now)
    except SubscribeError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    background.add_task(
        send_safely, sender, billing_emails.switched_to_manual(user, subscription)
    )
    return subscription_response(db, subscription, now)
