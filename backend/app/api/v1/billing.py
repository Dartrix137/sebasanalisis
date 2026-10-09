"""Planes y cotizacion (docs/PLATAFORMA_COMPLETA.md §3.3).

El precio lo calcula siempre el servidor, con `app.billing.pricing.quote`. El
cliente manda el plan y, si tiene, un codigo: nunca un monto.

Aqui no se cobra ni se redime ningun cupon: eso llega con el paso 5. Este
router NO exige `RequireAccess`: quien cotiza es justo quien todavia no tiene
acceso.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.v1.legal import client_ip
from app.billing import pricing
from app.billing.coupon_codes import normalize_code
from app.billing.pricing import CouponRejection
from app.core import rate_limit
from app.core.config import get_settings
from app.models import Coupon, CouponRedemption, Plan, User
from app.schemas.billing import PlanResponse, QuoteCoupon, QuoteRequest, QuoteResponse

router = APIRouter(tags=["billing"])

_MINUTE = 60
_HOUR = 60 * _MINUTE

_TOO_MANY_CODES = "Demasiados intentos con códigos. Intenta de nuevo más tarde."

# Lo que se le dice al cliente por cada motivo. Ninguno promete nada.
COUPON_MESSAGES: dict[CouponRejection, str] = {
    CouponRejection.not_found: "Ese código no existe.",
    CouponRejection.inactive: "Ese cupón ya no está disponible.",
    CouponRejection.not_started: "Ese cupón todavía no está vigente.",
    CouponRejection.expired: "Ese cupón ya venció.",
    CouponRejection.exhausted: "Ese cupón ya no tiene cupos.",
    CouponRejection.other_plan: "Ese cupón no aplica a este plan.",
    CouponRejection.currency_mismatch: "Ese cupón no aplica a la moneda de este plan.",
    CouponRejection.already_used: "Ya usaste ese cupón.",
    CouponRejection.covers_total: "Ese cupón no se puede usar con este plan.",
}


def _limit_coupon_attempts(user: User, request: Request) -> None:
    """Limite de intentos de la cotizacion CON codigo (§5.7.1).

    Sin el, la cotizacion serviria para adivinar codigos: responde si existe.
    Por cuenta y por IP, porque crear cuentas es gratis. Una cotizacion sin
    codigo no cuenta. En memoria, como el resto de `core/rate_limit`.
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


def coupon_terms(db: DbSession, coupon: Coupon, user: User) -> pricing.CouponTerms:
    """Lo que `pricing.quote` necesita saber de un cupon para esta cuenta."""
    already_used = (
        db.scalar(
            select(CouponRedemption.id).where(
                CouponRedemption.coupon_id == coupon.id, CouponRedemption.user_id == user.id
            )
        )
        is not None
    )
    return pricing.CouponTerms(
        kind=pricing.CouponKind(coupon.kind),
        value=coupon.value,
        currency=coupon.currency,
        active=coupon.active,
        valid_from=coupon.valid_from,
        valid_until=coupon.valid_until,
        max_redemptions=coupon.max_redemptions,
        redemptions_count=coupon.redemptions_count,
        plan_ids=frozenset(str(p.id) for p in coupon.plans),
        already_used_by_user=already_used,
    )


@router.get("/plans", response_model=list[PlanResponse])
def list_plans(db: DbSession) -> list[Plan]:
    """Los planes que se ofrecen. Publico."""
    return list(
        db.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.sort_order, Plan.code))
    )


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
