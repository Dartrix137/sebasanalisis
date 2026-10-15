"""Respuestas que no salen solo de las columnas de un modelo."""

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing import pricing
from app.billing.schedule import first_charge_at
from app.core import price_changes, subscriptions
from app.core.access import has_access
from app.core.accounts import is_last_active_admin
from app.models import Payment, PaymentRefund, Subscription, User
from app.schemas.admin import AdminSubscriptionResponse
from app.schemas.auth import AccessInfo, UserAccount, UserResponse
from app.schemas.billing import (
    AdminPaymentResponse,
    PaymentResponse,
    PlanResponse,
    SubscriptionResponse,
    UpcomingPriceChange,
)


def user_response(db: Session, user: User, now: datetime | None = None) -> UserResponse:
    """La cuenta con su decision de acceso.

    La decision es la de `core/access.has_access`, la misma que aplica
    `RequireAccess`: aqui solo se muestra, no se vuelve a decidir.
    """
    decision = has_access(db, user, now or datetime.now(UTC))
    return UserResponse(
        **UserAccount.model_validate(user).model_dump(),
        access=AccessInfo.model_validate(decision),
        can_delete_account=not is_last_active_admin(db, user),
    )


def subscription_response(
    db: Session, subscription: Subscription, now: datetime
) -> SubscriptionResponse:
    """La suscripcion, con `in_force`: si su periodo pagado sigue vigente."""
    period_end = subscription.current_period_end
    vigente = subscriptions.in_force(subscription, now)
    continues = vigente and subscription.status != "canceled"
    # Un traslado de precio ya avisado (§4.10): el proximo cobro automatico se
    # muestra con el precio de su periodo, el mismo en sus tres intentos.
    upcoming = price_changes.pending_for(db, subscription.id) if vigente else None
    if subscription.renewal_mode == "automatic" and period_end is not None:
        next_price = price_changes.charge_price(db, subscription, first_charge_at(period_end))
    else:
        next_price = price_changes.price_at(db, subscription, subscription.next_charge_at or now)
    return SubscriptionResponse(
        id=subscription.id,
        status=subscription.status,  # type: ignore[arg-type]
        renewal_mode=subscription.renewal_mode,  # type: ignore[arg-type]
        plan=PlanResponse.model_validate(subscription.plan),
        price_cents=subscription.price_cents,
        currency=subscription.currency,
        current_period_start=subscription.current_period_start,
        current_period_end=period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        in_force=vigente,
        payment_source_type=subscription.payment_source_type,  # type: ignore[arg-type]
        card_brand=subscription.card_brand,
        card_last4=subscription.card_last4,
        next_charge_at=subscription.next_charge_at if continues else None,
        next_charge_cents=(
            pricing.renewal_quote(
                next_price,
                subscription.currency,
                subscriptions.renewal_discount(db, subscription),
            ).total_cents
            if continues
            else None
        ),
        price_change=(
            UpcomingPriceChange(
                new_price_cents=upcoming.new_price_cents,
                effective_at=upcoming.effective_at,
                first_charge_at=price_changes.first_charge_with_new_price(
                    subscription, upcoming.effective_at
                ),
            )
            if upcoming is not None and upcoming.effective_at is not None
            else None
        ),
    )


def _payment_fields(payment: Payment) -> dict[str, object]:
    return {
        "id": payment.id,
        "status": payment.status,
        "kind": payment.kind,
        "plan_id": payment.plan_id,
        "plan_name": payment.plan.name,
        "amount_cents": payment.amount_cents,
        "discount_cents": payment.discount_cents,
        "currency": payment.currency,
        "period_start": payment.period_start,
        "period_end": payment.period_end,
        "created_at": payment.created_at,
        "resolved_at": payment.resolved_at,
    }


def payment_response(payment: Payment) -> PaymentResponse:
    """Un pago como lo ve su dueno: sin la referencia ni lo que dijo el proveedor."""
    return PaymentResponse(**_payment_fields(payment))  # type: ignore[arg-type]


def admin_payment_responses(db: Session, payments: Iterable[Payment]) -> list[AdminPaymentResponse]:
    """Los pagos como los ve el administrador, con el correo de la cuenta y lo
    reembolsado. Dos consultas para toda la lista, no dos por pago."""
    rows = list(payments)
    ids = [p.id for p in rows]
    refunded: dict[object, int] = dict(
        db.execute(  # type: ignore[arg-type]
            select(PaymentRefund.payment_id, func.sum(PaymentRefund.amount_cents))
            .where(PaymentRefund.payment_id.in_(ids))
            .group_by(PaymentRefund.payment_id)
        ).all()
    ) if ids else {}
    user_ids = {p.user_id for p in rows if p.user_id is not None}
    emails: dict[object, str] = dict(
        db.execute(select(User.id, User.email).where(User.id.in_(user_ids))).all()  # type: ignore[arg-type]
    ) if user_ids else {}
    return [
        AdminPaymentResponse(
            **_payment_fields(p),  # type: ignore[arg-type]
            reference=p.reference,
            provider_transaction_id=p.provider_transaction_id,
            failure_reason=p.failure_reason,
            subscription_id=p.subscription_id,
            user_id=p.user_id,
            user_email=emails.get(p.user_id) if p.user_id is not None else None,
            reversed_at=p.reversed_at,
            reversal_note=p.reversal_note,
            refunded_cents=int(refunded.get(p.id, 0)),
        )
        for p in rows
    ]


def admin_subscription_response(
    db: Session, subscription: Subscription, now: datetime
) -> AdminSubscriptionResponse:
    return AdminSubscriptionResponse(
        **subscription_response(db, subscription, now).model_dump(),
        user_id=subscription.user_id,
        user_email=subscription.user.email,
        retry_count=subscription.retry_count,
        canceled_at=subscription.canceled_at,
        created_at=subscription.created_at,
    )
