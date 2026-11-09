"""
Schemas: los datos de facturacion del comprador y los lugares de Siigo
(docs/PLATAFORMA_COMPLETA.md §3.17, "Paso 5.4", punto 8).

Son datos personales: van del navegador a la API y de ahi a Siigo. El
monitoreo descarta los cuerpos de `/billing`.
"""

from datetime import datetime
from enum import Enum

from pydantic import Field

from app.schemas.base import ApiModel


class BillingIdType(str, Enum):
    """Los codigos de documento de Siigo (`billing/billing_profile.IdType`)."""

    cedula_ciudadania = "13"
    cedula_extranjeria = "22"
    nit_otro_pais = "50"
    pasaporte = "41"
    documento_extranjero = "42"


class IdTypeOption(ApiModel):
    code: BillingIdType
    name: str


class CountryResponse(ApiModel):
    """Un pais de la lista de Siigo, con los tipos de documento que admite."""

    code: str
    name: str
    id_types: list[IdTypeOption]
    # El tipo que se propone primero.
    default_id_type: BillingIdType


class CityResponse(ApiModel):
    state_code: str
    state: str
    city_code: str
    city: str


class BillingProfileRequest(ApiModel):
    """PUT /billing/profile. El servidor normaliza y valida con las reglas de
    Siigo; los topes de aqui solo frenan un cuerpo desmedido."""

    first_names: str = Field(max_length=200)
    last_names: str = Field(max_length=200)
    country_code: str = Field(max_length=8)
    id_type: str = Field(max_length=4)
    id_number: str = Field(max_length=60)
    address: str = Field(max_length=600)
    state_code: str = Field(max_length=16)
    city_code: str = Field(max_length=16)


class BillingProfileResponse(ApiModel):
    first_names: str
    last_names: str
    country_code: str
    country: str
    id_type: BillingIdType
    id_type_name: str
    id_number: str
    address: str
    state_code: str
    state: str
    city_code: str
    city: str
    updated_at: datetime


class BillingProfileFieldError(ApiModel):
    field: str
    message: str
