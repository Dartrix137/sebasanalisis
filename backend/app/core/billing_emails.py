"""Los correos de cobro (docs/PLATAFORMA_COMPLETA.md §3.8).

Aqui solo se arman: quien los envia es el endpoint (en segundo plano) o el job
de renovaciones. Ninguno promete resultados: describen el servicio y el cobro.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.billing import pricing
from app.core import price_changes, subscriptions
from app.core.config import get_settings
from app.core.email import EmailMessage
from app.core.subscriptions import Settlement
from app.emails import build_email
from app.models import Plan, Subscription, SubscriptionPriceChange, User


def frontend_url(path: str) -> str:
    return f"{get_settings().frontend_base_url.rstrip('/')}{path}"


def source_label(subscription: Subscription) -> str:
    """El medio de pago como se le nombra al cliente: `Visa •••• 4242`, `Nequi`."""
    if subscription.payment_source_type == "NEQUI":
        return "tu cuenta Nequi"
    if subscription.card_last4:
        # La marca llega con el primer cobro aprobado: una tarjeta recien
        # guardada todavia no la tiene.
        brand = f" {subscription.card_brand.capitalize()}" if subscription.card_brand else ""
        return f"tu tarjeta{brand} terminada en {subscription.card_last4}"
    return "tu medio de pago guardado"


def payment_emails(db: Session, settlement: Settlement) -> list[EmailMessage]:
    """Los correos que corresponden a un pago que ESTA llamada resolvio: un
    evento repetido no repite el correo.

    Aprobado: recibo, y bienvenida si ademas activo la suscripcion. Cobro
    automatico de renovacion rechazado: aviso de cobro fallido.
    """
    payment = settlement.payment
    if not settlement.changed or payment.user_id is None:
        return []
    user = db.get(User, payment.user_id)
    if user is None:
        return []
    subscription = (
        db.get(Subscription, payment.subscription_id) if payment.subscription_id else None
    )

    if settlement.renewal_failed and subscription is not None:
        return [
            build_email(
                "payment_failed",
                to=user.email,
                display_name=user.display_name,
                plan_name=payment.plan.name,
                amount_cents=payment.amount_cents,
                currency=payment.currency,
                source_label=source_label(subscription),
                period_end=subscription.current_period_end,
                url=frontend_url("/cuenta"),
            )
        ]
    if payment.status != "approved":
        return []

    automatic = subscription is not None and subscription.renewal_mode == "automatic"
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
        "automatic": automatic and subscription is not None and subscription.status == "active",
    }
    messages = []
    if settlement.activated:
        messages.append(
            build_email(
                "subscription_welcome",
                to=user.email,
                url=frontend_url("/dashboard"),
                account_url=frontend_url("/cuenta"),
                **context,
            )
        )
    messages.append(
        build_email("payment_receipt", to=user.email, url=frontend_url("/cuenta"), **context)
    )
    return messages


def renewal_notice(
    user: User, subscription: Subscription, amount_cents: int, charge_at: datetime
) -> EmailMessage:
    """Aviso ANTES de un cobro automatico: que plan, cuanto, en que moneda y que dia."""
    return build_email(
        "renewal_notice",
        to=user.email,
        display_name=user.display_name,
        plan_name=subscription.plan.name,
        amount_cents=amount_cents,
        currency=subscription.currency,
        charge_at=charge_at,
        source_label=source_label(subscription),
        url=frontend_url("/cuenta"),
    )


def period_ending(user: User, subscription: Subscription, amount_cents: int) -> EmailMessage:
    """Pago manual: el periodo esta por vencer y como pagar el siguiente."""
    return build_email(
        "period_ending",
        to=user.email,
        display_name=user.display_name,
        plan_name=subscription.plan.name,
        amount_cents=amount_cents,
        currency=subscription.currency,
        period_end=subscription.current_period_end,
        url=frontend_url(f"/planes/pagar?plan={subscription.plan_id}"),
    )


def subscription_expired(
    user: User, subscription: Subscription, *, automatic: bool, notice_failed: bool = False
) -> EmailMessage:
    """La suscripcion vencio: se agotaron los cobros, no se pago el siguiente
    periodo o, en la automatica, el aviso del cobro nunca salio y no se cobro."""
    return build_email(
        "subscription_expired",
        to=user.email,
        display_name=user.display_name,
        plan_name=subscription.plan.name,
        period_end=subscription.current_period_end,
        automatic=automatic,
        notice_failed=notice_failed,
        url=frontend_url("/planes"),
    )


def subscription_canceled(user: User, subscription: Subscription) -> EmailMessage:
    return build_email(
        "subscription_canceled",
        to=user.email,
        display_name=user.display_name,
        plan_name=subscription.plan.name,
        period_end=subscription.current_period_end,
        url=frontend_url("/cuenta"),
    )


def payment_method_updated(
    user: User, subscription: Subscription, amount_cents: int, *, activated_renewal: bool
) -> EmailMessage:
    """Se guardo un medio de pago nuevo. `activated_renewal`: con eso la
    suscripcion paso a renovarse sola."""
    return build_email(
        "payment_method_updated",
        to=user.email,
        display_name=user.display_name,
        plan_name=subscription.plan.name,
        source_label=source_label(subscription),
        activated_renewal=activated_renewal,
        amount_cents=amount_cents,
        currency=subscription.currency,
        charge_at=subscription.next_charge_at,
        period_end=subscription.current_period_end,
        url=frontend_url("/cuenta"),
    )


def switched_to_manual(user: User, subscription: Subscription) -> EmailMessage:
    return build_email(
        "switched_to_manual",
        to=user.email,
        display_name=user.display_name,
        plan_name=subscription.plan.name,
        period_end=subscription.current_period_end,
        url=frontend_url("/cuenta"),
    )


def admin_change(
    db: Session, user: User, subscription: Subscription, action: str, *, had_renewal: bool
) -> EmailMessage:
    """Un administrador extendio o cancelo la suscripcion (decidido el
    2026-10-14: se avisa en las tres acciones). El motivo que escribio el
    administrador es interno y no va en el correo."""
    if action == "extend":
        renews = subscription.renewal_mode == "automatic" and subscription.status == "active"
        return build_email(
            "subscription_extended",
            to=user.email,
            display_name=user.display_name,
            plan_name=subscription.plan.name,
            period_end=subscription.current_period_end,
            charge_at=subscription.next_charge_at if renews else None,
            amount_cents=(
                pricing.renewal_quote(
                    subscription.price_cents,
                    subscription.currency,
                    subscriptions.renewal_discount(db, subscription),
                ).total_cents
            ),
            currency=subscription.currency,
            source_label=source_label(subscription),
            url=frontend_url("/cuenta"),
        )
    if action == "cancel_at_period_end":
        return build_email(
            "subscription_renewal_stopped",
            to=user.email,
            display_name=user.display_name,
            plan_name=subscription.plan.name,
            period_end=subscription.current_period_end,
            url=frontend_url("/cuenta"),
        )
    return build_email(
        "subscription_ended",
        to=user.email,
        display_name=user.display_name,
        plan_name=subscription.plan.name,
        period_end=subscription.current_period_end,
        had_renewal=had_renewal,
        url=frontend_url("/cuenta"),
    )


# ---------- Traslado de precio (§4.10) ----------


def period_label(plan: Plan) -> str:
    """`al mes`, `cada 2 meses`, `al año`."""
    if plan.interval == "year":
        return "al año" if plan.interval_count == 1 else f"cada {plan.interval_count} años"
    return "al mes" if plan.interval_count == 1 else f"cada {plan.interval_count} meses"


def price_increase(
    user: User,
    subscription: Subscription,
    row: SubscriptionPriceChange,
    effective_at: datetime | None,
) -> EmailMessage:
    """Aviso de una subida, 30 dias antes de cobrarla. Dice que plan, de cuanto
    a cuanto, desde cuando, y como cancelar o pasar a pago manual antes."""
    return build_email(
        "price_increase",
        to=user.email,
        display_name=user.display_name,
        plan_name=subscription.plan.name,
        old_price_cents=row.old_price_cents,
        new_price_cents=row.new_price_cents,
        currency=subscription.currency,
        period_label=period_label(subscription.plan),
        effective_at=effective_at,
        first_charge_at=price_changes.first_charge_with_new_price(subscription, effective_at),
        automatic=subscription.renewal_mode == "automatic",
        has_discount=subscription.coupon_id is not None
        and subscription.discount_periods_remaining != 0,
        url=frontend_url("/cuenta"),
    )


def price_decrease(
    user: User, subscription: Subscription, row: SubscriptionPriceChange
) -> EmailMessage:
    return build_email(
        "price_decrease",
        to=user.email,
        display_name=user.display_name,
        plan_name=subscription.plan.name,
        old_price_cents=row.old_price_cents,
        new_price_cents=row.new_price_cents,
        currency=subscription.currency,
        period_label=period_label(subscription.plan),
        automatic=subscription.renewal_mode == "automatic",
        url=frontend_url("/cuenta"),
    )


def price_change_canceled(
    user: User, subscription: Subscription, row: SubscriptionPriceChange
) -> EmailMessage:
    """El cambio de precio que se le aviso ya no se hara."""
    return build_email(
        "price_change_canceled",
        to=user.email,
        display_name=user.display_name,
        plan_name=subscription.plan.name,
        old_price_cents=row.old_price_cents,
        currency=subscription.currency,
        period_label=period_label(subscription.plan),
        url=frontend_url("/cuenta"),
    )
