"""Los datos de facturacion del comprador (docs/PLATAFORMA_COMPLETA.md §3.17,
"Paso 5.4", punto 8; Fase 5, paso 5.4).

La factura electronica va a cada comprador, con su nombre y su documento
(decidido por el usuario el 2026-11-06), y Siigo exige ademas la direccion y la
ciudad con sus codigos. Se piden al pagar (`/planes/pagar`) y se cambian en "Mi
cuenta": son de la cuenta, no de un pago. `POST /billing/subscriptions` no abre
un pago sin ellos.

Todo exige sesion y nada mas: no `RequireAccess`, porque quien los da es justo
quien todavia no tiene acceso. Las rutas no llevan ids: cada cuenta ve y cambia
solo los suyos.
"""

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.billing import billing_profile as rules
from app.billing import places
from app.core import billing_profiles, rate_limit
from app.core.config import get_settings
from app.models import BillingProfile
from app.schemas.billing_profile import (
    BillingIdType,
    BillingProfileRequest,
    BillingProfileResponse,
    CityResponse,
    CountryResponse,
    IdTypeOption,
)

router = APIRouter(tags=["billing"])

_MINUTE = 60


def profile_response(profile: BillingProfile) -> BillingProfileResponse:
    city = places.find(profile.country_code, profile.state_code, profile.city_code)
    country = places.country(profile.country_code)
    id_type = BillingIdType(profile.id_type)
    return BillingProfileResponse(
        first_names=profile.first_names,
        last_names=profile.last_names,
        country_code=profile.country_code,
        country=country.name if country else profile.country_code,
        id_type=id_type,
        id_type_name=rules.ID_TYPE_NAMES[id_type.value],
        id_number=profile.id_number,
        address=profile.address,
        state_code=profile.state_code,
        state=city.state if city else profile.state_code,
        city_code=profile.city_code,
        city=city.city if city else profile.city_code,
        updated_at=profile.updated_at,
    )


@router.get("/billing/profile", response_model=BillingProfileResponse | None)
def get_billing_profile(user: CurrentUser, db: DbSession) -> BillingProfileResponse | None:
    """Los datos de facturacion de la cuenta, o null si todavia no los dio."""
    profile = billing_profiles.get(db, user.id)
    return profile_response(profile) if profile else None


@router.put("/billing/profile", response_model=BillingProfileResponse)
def put_billing_profile(
    payload: BillingProfileRequest, user: CurrentUser, db: DbSession
) -> BillingProfileResponse:
    """Guarda los datos de facturacion de la cuenta (crea o reemplaza).

    Los valida con las reglas de Siigo (`billing/billing_profile`). Si algo no
    vale, responde 422 con `detail.code = "invalid_billing_profile"` y la lista
    de campos en `detail.errors`. Cambiarlos no toca ninguna factura ya
    emitida: cada factura guarda su propia copia.
    """
    if get_settings().rate_limit_enabled and not rate_limit.hit(
        f"billing-profile:user:{user.id}", limit=20, window=15 * _MINUTE
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados cambios seguidos. Intenta de nuevo más tarde.",
        )
    try:
        data = rules.validate(
            rules.BillingProfileInput(
                first_names=payload.first_names,
                last_names=payload.last_names,
                country_code=payload.country_code,
                id_type=payload.id_type,
                id_number=payload.id_number,
                address=payload.address,
                state_code=payload.state_code,
                city_code=payload.city_code,
            )
        )
    except rules.InvalidBillingProfile as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_billing_profile",
                "message": "Revisa tus datos de facturación.",
                "errors": [{"field": e.field, "message": e.message} for e in exc.errors],
            },
        ) from None
    profile = billing_profiles.save(db, user.id, data)
    db.commit()
    db.refresh(profile)
    return profile_response(profile)


@router.get("/billing/places/countries", response_model=list[CountryResponse])
def list_countries(user: CurrentUser) -> list[CountryResponse]:
    """Los paises de la lista de Siigo (Colombia primero), con los tipos de
    documento que admite cada uno."""
    return [
        CountryResponse(
            code=c.code,
            name=c.name,
            id_types=[
                IdTypeOption(code=BillingIdType(t), name=rules.ID_TYPE_NAMES[t])
                for t in rules.id_types_for(c.code)
            ],
            default_id_type=BillingIdType(rules.default_id_type(c.code)),
        )
        for c in places.countries()
    ]


@router.get("/billing/places/cities", response_model=list[CityResponse])
def list_cities(
    user: CurrentUser, country: str = Query(min_length=2, max_length=4)
) -> list[CityResponse]:
    """Las ciudades de un pais en la lista de Siigo, por departamento y nombre."""
    if places.country(country) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="País no encontrado")
    return [
        CityResponse(state_code=c.state_code, state=c.state, city_code=c.city_code, city=c.city)
        for c in places.cities_of(country)
    ]
