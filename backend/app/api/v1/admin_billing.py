"""Admin: planes y cupones (docs/PLATAFORMA_COMPLETA.md §4.4 y §4.5).

Tres reglas:

- Nada se borra: no hay `DELETE`. Un plan o un cupon que ya no se quiere
  ofrecer se desactiva (`active = false`).
- Todo cambio pide un motivo y escribe su fila en `admin_audit_log` en la misma
  transaccion (§4.6).
- Un cambio que no cambia nada se rechaza, para no llenar la bitacora de filas
  que no dicen nada.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession
from app.api.v1.admin_users import Limit, Offset
from app.api.v1.legal import client_ip
from app.billing.coupon_codes import InvalidCouponCodeError, normalize_code, validate_code
from app.billing.pricing import MAX_PERCENT
from app.core import audit
from app.models import Coupon, CouponRedemption, Plan, User
from app.schemas.billing import (
    AdminCouponListResponse,
    AdminCouponResponse,
    AdminPlanListResponse,
    AdminPlanResponse,
    CouponRedemptionListResponse,
    CouponRedemptionResponse,
    CreateCouponRequest,
    CreatePlanRequest,
    UpdateCouponRequest,
    UpdatePlanRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"])

_NOTHING_TO_CHANGE = "No hay nada que cambiar"

# Lo que define el descuento de un cupon. Con redenciones ya no se toca: el
# paso 5 lee estos campos para las renovaciones de quien ya lo uso.
_DISCOUNT_FIELDS = ("kind", "value", "currency", "duration", "duration_periods")


def _invalid(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _utc(value: datetime | None) -> datetime | None:
    """Una fecha sin zona horaria se lee como UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# ---------- Planes ----------

_PLAN_FIELDS = (
    "name",
    "description",
    "price_cents",
    "display_price_cents",
    "display_currency",
    "interval",
    "interval_count",
    "active",
    "sort_order",
)


def _plan_snapshot(plan: Plan) -> dict[str, Any]:
    return {
        "code": plan.code,
        "currency": plan.currency,
        **{f: getattr(plan, f) for f in _PLAN_FIELDS},
    }


def _plan_or_404(db: DbSession, plan_id: UUID) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado")
    return plan


def _check_display_price(price_cents: int | None, currency: str | None) -> None:
    if (price_cents is None) != (currency is None):
        raise _invalid("El precio de presentación lleva monto y moneda, o ninguno de los dos")


@router.get("/plans", response_model=AdminPlanListResponse)
def list_plans(
    db: DbSession, admin: AdminUser, limit: Limit = 50, offset: Offset = 0
) -> AdminPlanListResponse:
    """Todos los planes, los desactivados tambien."""
    total = db.scalar(select(func.count()).select_from(Plan)) or 0
    plans = db.scalars(select(Plan).order_by(Plan.sort_order, Plan.code).limit(limit).offset(offset))
    return AdminPlanListResponse(
        items=[AdminPlanResponse.model_validate(p) for p in plans],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/plans", response_model=AdminPlanResponse, status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: CreatePlanRequest, db: DbSession, admin: AdminUser, request: Request
) -> Plan:
    _check_display_price(payload.display_price_cents, payload.display_currency)
    if db.scalar(select(Plan.id).where(Plan.code == payload.code)):
        raise _conflict("Ya existe un plan con ese código")
    plan = Plan(
        code=payload.code,
        name=payload.name.strip(),
        description=payload.description.strip(),
        price_cents=payload.price_cents,
        currency=payload.currency,
        display_price_cents=payload.display_price_cents,
        display_currency=payload.display_currency,
        interval=payload.interval.value,
        interval_count=payload.interval_count,
        active=payload.active,
        sort_order=payload.sort_order,
    )
    db.add(plan)
    db.flush()
    audit.record(
        db,
        admin,
        action="plan.create",
        target_type="plan",
        target_id=plan.id,
        after=_plan_snapshot(plan),
        reason=payload.reason.strip(),
        ip=client_ip(request),
    )
    db.commit()
    db.refresh(plan)
    return plan


@router.patch("/plans/{plan_id}", response_model=AdminPlanResponse)
def update_plan(
    plan_id: UUID, payload: UpdatePlanRequest, db: DbSession, admin: AdminUser, request: Request
) -> Plan:
    """Edita, activa o desactiva un plan. El codigo y la moneda de cobro no cambian.

    El precio nuevo aplica a suscripciones nuevas: las vigentes guardan el suyo
    (§3.7).
    """
    plan = _plan_or_404(db, plan_id)
    before = _plan_snapshot(plan)

    sent = payload.model_fields_set
    for field in _PLAN_FIELDS:
        if field not in sent:
            continue
        value = getattr(payload, field)
        # Solo el precio de presentacion se puede vaciar.
        if value is None and field not in ("display_price_cents", "display_currency"):
            raise _invalid(f"El campo {field} no puede quedar vacío")
        if field == "interval":
            value = value.value
        elif field in ("name", "description"):
            value = value.strip()
            if not value:
                raise _invalid(f"El campo {field} no puede quedar vacío")
        setattr(plan, field, value)
    _check_display_price(plan.display_price_cents, plan.display_currency)

    after = _plan_snapshot(plan)
    if after == before:
        raise _conflict(_NOTHING_TO_CHANGE)
    audit.record(
        db,
        admin,
        action="plan.update",
        target_type="plan",
        target_id=plan.id,
        before=before,
        after=after,
        reason=payload.reason.strip(),
        ip=client_ip(request),
    )
    db.commit()
    db.refresh(plan)
    return plan


# ---------- Cupones ----------

_COUPON_FIELDS = (
    *_DISCOUNT_FIELDS,
    "max_redemptions",
    "valid_from",
    "valid_until",
    "active",
)


def _coupon_snapshot(coupon: Coupon) -> dict[str, Any]:
    return {
        "code": coupon.code,
        "kind": coupon.kind,
        "value": coupon.value,
        "currency": coupon.currency,
        "duration": coupon.duration,
        "duration_periods": coupon.duration_periods,
        "max_redemptions": coupon.max_redemptions,
        "valid_from": _iso(coupon.valid_from),
        "valid_until": _iso(coupon.valid_until),
        "active": coupon.active,
        "plan_ids": sorted(str(p.id) for p in coupon.plans),
    }


def _coupon_response(coupon: Coupon) -> AdminCouponResponse:
    return AdminCouponResponse(
        id=coupon.id,
        code=coupon.code,
        kind=coupon.kind,  # type: ignore[arg-type]
        value=coupon.value,
        currency=coupon.currency,
        duration=coupon.duration,  # type: ignore[arg-type]
        duration_periods=coupon.duration_periods,
        max_redemptions=coupon.max_redemptions,
        redemptions_count=coupon.redemptions_count,
        valid_from=coupon.valid_from,
        valid_until=coupon.valid_until,
        active=coupon.active,
        plan_ids=[p.id for p in coupon.plans],
        created_at=coupon.created_at,
    )


def _coupon_or_404(db: DbSession, coupon_id: UUID) -> Coupon:
    coupon = db.get(Coupon, coupon_id)
    if coupon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cupón no encontrado")
    return coupon


def _plans_or_422(db: DbSession, plan_ids: list[UUID]) -> list[Plan]:
    unique = list(dict.fromkeys(plan_ids))
    plans = list(db.scalars(select(Plan).where(Plan.id.in_(unique)))) if unique else []
    if len(plans) != len(unique):
        raise _invalid("Alguno de los planes elegidos no existe")
    return plans


def _check_coupon(coupon: Coupon) -> None:
    """Reglas de §4.5 sobre el cupon como quedaria guardado."""
    if coupon.kind == "percent":
        if not 1 <= coupon.value <= MAX_PERCENT:
            raise _invalid(
                f"El porcentaje va de 1 a {MAX_PERCENT}. Un cupón no puede dejar el total en "
                "cero: una cortesía total se da como acceso invitado desde Usuarios"
            )
        if coupon.currency is not None:
            raise _invalid("Un cupón de porcentaje no lleva moneda")
    elif coupon.currency is None:
        raise _invalid("Un cupón de monto fijo necesita la moneda")

    if coupon.duration == "repeating":
        if coupon.duration_periods is None:
            raise _invalid("Un cupón que se repite necesita el número de períodos")
    elif coupon.duration_periods is not None:
        raise _invalid("El número de períodos solo aplica a un cupón que se repite")

    if coupon.valid_until is not None and coupon.valid_until <= coupon.valid_from:
        raise _invalid("El vencimiento debe ser posterior al inicio de la vigencia")
    if coupon.max_redemptions is not None and coupon.max_redemptions < coupon.redemptions_count:
        raise _invalid(
            f"El tope de usos no puede ser menor que los {coupon.redemptions_count} que ya tiene"
        )


@router.get("/coupons", response_model=AdminCouponListResponse)
def list_coupons(
    db: DbSession,
    admin: AdminUser,
    query: Annotated[str | None, Query(max_length=80)] = None,
    active: bool | None = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminCouponListResponse:
    """Cupones por pagina, los mas recientes primero. Busca por codigo."""
    filters = []
    text = normalize_code(query or "")
    if text:
        pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(Coupon.code.like(pattern, escape="\\"))
    if active is not None:
        filters.append(Coupon.active.is_(active))
    total = db.scalar(select(func.count()).select_from(Coupon).where(*filters)) or 0
    coupons = db.scalars(
        select(Coupon)
        .where(*filters)
        .order_by(Coupon.created_at.desc(), Coupon.id)
        .limit(limit)
        .offset(offset)
    )
    return AdminCouponListResponse(
        items=[_coupon_response(c) for c in coupons], total=total, limit=limit, offset=offset
    )


@router.post("/coupons", response_model=AdminCouponResponse, status_code=status.HTTP_201_CREATED)
def create_coupon(
    payload: CreateCouponRequest, db: DbSession, admin: AdminUser, request: Request
) -> AdminCouponResponse:
    code = normalize_code(payload.code)
    try:
        validate_code(code)
    except InvalidCouponCodeError as exc:
        raise _invalid(str(exc)) from None
    if db.scalar(select(Coupon.id).where(Coupon.code == code)):
        raise _conflict("Ya existe un cupón con ese código")

    coupon = Coupon(
        code=code,
        kind=payload.kind.value,
        value=payload.value,
        currency=payload.currency,
        duration=payload.duration.value,
        duration_periods=payload.duration_periods,
        max_redemptions=payload.max_redemptions,
        redemptions_count=0,
        valid_from=_utc(payload.valid_from) or datetime.now(UTC),
        valid_until=_utc(payload.valid_until),
        active=payload.active,
        created_by=admin.id,
    )
    _check_coupon(coupon)
    coupon.plans = _plans_or_422(db, payload.plan_ids)
    db.add(coupon)
    db.flush()
    audit.record(
        db,
        admin,
        action="coupon.create",
        target_type="coupon",
        target_id=coupon.id,
        after=_coupon_snapshot(coupon),
        reason=payload.reason.strip(),
        ip=client_ip(request),
    )
    db.commit()
    db.refresh(coupon)
    return _coupon_response(coupon)


@router.patch("/coupons/{coupon_id}", response_model=AdminCouponResponse)
def update_coupon(
    coupon_id: UUID,
    payload: UpdateCouponRequest,
    db: DbSession,
    admin: AdminUser,
    request: Request,
) -> AdminCouponResponse:
    """Edita, activa o desactiva un cupon. El codigo no cambia."""
    coupon = _coupon_or_404(db, coupon_id)
    before = _coupon_snapshot(coupon)

    sent = payload.model_fields_set
    for field in _COUPON_FIELDS:
        if field not in sent:
            continue
        value = getattr(payload, field)
        if field in ("kind", "duration") and value is not None:
            value = value.value
        elif field in ("valid_from", "valid_until"):
            value = _utc(value)
        if value is None and field in ("kind", "value", "duration", "valid_from", "active"):
            raise _invalid(f"El campo {field} no puede quedar vacío")
        setattr(coupon, field, value)
    if "plan_ids" in sent:
        if payload.plan_ids is None:
            raise _invalid("El campo plan_ids no puede quedar vacío: manda una lista")
        coupon.plans = _plans_or_422(db, payload.plan_ids)

    after = _coupon_snapshot(coupon)
    if after == before:
        raise _conflict(_NOTHING_TO_CHANGE)
    if coupon.redemptions_count > 0 and any(after[f] != before[f] for f in _DISCOUNT_FIELDS):
        raise _conflict(
            "Este cupón ya se usó: su descuento no se puede cambiar. "
            "Desactívalo y crea otro"
        )
    _check_coupon(coupon)

    audit.record(
        db,
        admin,
        action="coupon.update",
        target_type="coupon",
        target_id=coupon.id,
        before=before,
        after=after,
        reason=payload.reason.strip(),
        ip=client_ip(request),
    )
    db.commit()
    db.refresh(coupon)
    return _coupon_response(coupon)


@router.get("/coupons/{coupon_id}/redemptions", response_model=CouponRedemptionListResponse)
def list_redemptions(
    coupon_id: UUID, db: DbSession, admin: AdminUser, limit: Limit = 25, offset: Offset = 0
) -> CouponRedemptionListResponse:
    """Quien uso el cupon, cuando y en que suscripcion. Lo mas reciente primero."""
    coupon = _coupon_or_404(db, coupon_id)
    total = (
        db.scalar(
            select(func.count())
            .select_from(CouponRedemption)
            .where(CouponRedemption.coupon_id == coupon.id)
        )
        or 0
    )
    rows = db.execute(
        select(CouponRedemption, User.email)
        .join(User, User.id == CouponRedemption.user_id)
        .where(CouponRedemption.coupon_id == coupon.id)
        .order_by(CouponRedemption.created_at.desc(), CouponRedemption.id)
        .limit(limit)
        .offset(offset)
    )
    return CouponRedemptionListResponse(
        items=[
            CouponRedemptionResponse(
                id=r.id,
                user_id=r.user_id,
                user_email=email,
                subscription_id=r.subscription_id,
                created_at=r.created_at,
            )
            for r, email in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
