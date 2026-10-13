"""Respuestas que no salen solo de las columnas de un modelo."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.billing import pricing
from app.core import subscriptions
from app.core.access import has_access
from app.core.accounts import is_last_active_admin
from app.models import Payment, Subscription, User
from app.schemas.auth import AccessInfo, UserAccount, UserResponse
from app.schemas.billing import (
    AdminPaymentResponse,
    PaymentResponse,
    PlanResponse,
    SubscriptionResponse,
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
                subscription.price_cents,
                subscription.currency,
                subscriptions.renewal_discount(db, subscription),
            ).total_cents
            if continues
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


def admin_payment_response(payment: Payment) -> AdminPaymentResponse:
    return AdminPaymentResponse(
        **_payment_fields(payment),  # type: ignore[arg-type]
        reference=payment.reference,
        provider_transaction_id=payment.provider_transaction_id,
        failure_reason=payment.failure_reason,
    )
