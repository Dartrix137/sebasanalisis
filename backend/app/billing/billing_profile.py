"""Los datos de facturacion del comprador: que tipos de documento se admiten y
como se validan (docs/PLATAFORMA_COMPLETA.md §3.17, "Paso 5.4", punto 8; Fase 5,
paso 5.4).

Decidido por el usuario: la factura va a cada comprador, con su nombre y su
documento, nunca a consumidor final (2026-11-06). Se piden al pagar, no al
registrarse. Tipos de documento (aprobados el 2026-11-05):

- En Colombia: cedula de ciudadania (`13`) por defecto, o cedula de
  extranjeria (`22`).
- Fuera de Colombia: documento de identificacion extranjero (`42`) por
  defecto, o pasaporte (`41`) o NIT de otro pais (`50`). Hasta el 2026-11-09
  el defecto era `50`, que es de una empresa; el tercero se crea siempre como
  persona. Soporte de Siigo (2026-11-09): "El ID se informa dependiendo del
  documento que tenga el tercero", y el extranjero pide los mismos campos
  obligatorios que el nacional (decidido por el usuario el 2026-11-09).

Los codigos y sus formatos salen de la documentacion de clientes de Siigo
(`https://developers.siigo.com/docs/siigoapi/customer/1-create-customer/`,
leida el 2026-11-05): la cedula es numerica de 3 a 13 digitos; los documentos
de fuera son alfanumericos de 1 a 20. Ademas, `invalid_identification` exige
`^[\\d\\w]{1}[\\d\\w\\-]+[\\d\\w]{1}$`, asi que en la practica son al menos 3.

Los nombres: Siigo los recibe en `name` (hasta 100 caracteres cada uno) y en el
contacto (`contacts.first_name` y `last_name`, hasta 50): se limitan a 50. Dice
que el nombre "no permite caracteres especiales". Se admiten letras (con tildes
y la ñ), espacios, apostrofo, guion y punto; que Siigo acepte tildes y la ñ se
comprueba en su empresa de pruebas.

Python puro: sin base de datos ni red.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.billing import places

IdType = Literal["13", "22", "50", "41", "42"]

ID_TYPE_NAMES: dict[IdType, str] = {
    "13": "Cédula de ciudadanía",
    "22": "Cédula de extranjería",
    "50": "NIT de otro país",
    "41": "Pasaporte",
    "42": "Documento de identificación extranjero",
}

#: Los tipos de cada lado, el primero es el que va por defecto.
COLOMBIA_ID_TYPES: tuple[IdType, ...] = ("13", "22")
FOREIGN_ID_TYPES: tuple[IdType, ...] = ("42", "41", "50")
NUMERIC_ID_TYPES: frozenset[IdType] = frozenset({"13"})

NAME_MAX = 50
ADDRESS_MAX = 256
ID_MAX = 20

FieldName = Literal["first_names", "last_names", "country_code", "id_type", "id_number",
                    "address", "city"]


def id_types_for(country_code: str) -> tuple[IdType, ...]:
    return COLOMBIA_ID_TYPES if places.is_colombia(country_code) else FOREIGN_ID_TYPES


def default_id_type(country_code: str) -> IdType:
    return id_types_for(country_code)[0]


@dataclass(frozen=True)
class BillingProfileInput:
    first_names: str
    last_names: str
    country_code: str
    id_type: str
    id_number: str
    address: str
    state_code: str
    city_code: str


@dataclass(frozen=True)
class BillingProfileData:
    """Los datos ya normalizados y validados."""

    first_names: str
    last_names: str
    country_code: str
    id_type: IdType
    id_number: str
    address: str
    state_code: str
    city_code: str
    city: places.City


@dataclass(frozen=True)
class FieldError:
    field: FieldName
    message: str


class InvalidBillingProfile(ValueError):
    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__("; ".join(f"{e.field}: {e.message}" for e in errors))
        self.errors = errors


def _spaces(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


# Palabras de letras separadas por un espacio, un apostrofo, un guion o un
# punto (o un punto y un espacio: "St. John").
_NAME_RE = re.compile(r"^[^\W\d_]+(?:(?:[ '\-]|\. ?)[^\W\d_]+)*\.?$")
_FOREIGN_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]+[A-Z0-9]$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _name(raw: str, field: FieldName, errors: list[FieldError]) -> str:
    value = _spaces(raw)
    if not value:
        errors.append(FieldError(field, "Es obligatorio."))
    elif len(value) > NAME_MAX:
        errors.append(FieldError(field, f"Máximo {NAME_MAX} caracteres."))
    elif not _NAME_RE.match(value):
        errors.append(FieldError(field, "Usa solo letras, espacios, apóstrofo, guion o punto."))
    return value


def _id_number(raw: str, id_type: IdType, errors: list[FieldError]) -> str:
    if id_type in NUMERIC_ID_TYPES:
        # "1.234.567" o "1 234 567" se aceptan: se guardan los digitos.
        value = re.sub(r"[.\s]", "", raw)
        if not value.isdigit() or not 3 <= len(value) <= 13:
            errors.append(FieldError("id_number", "La cédula lleva de 3 a 13 dígitos."))
        return value
    value = re.sub(r"\s", "", raw).upper()
    if not 3 <= len(value) <= ID_MAX or not _FOREIGN_ID_RE.match(value):
        errors.append(
            FieldError(
                "id_number",
                f"Usa de 3 a {ID_MAX} letras o números, sin espacios ni símbolos (se admite el guion).",
            )
        )
    return value


def validate(data: BillingProfileInput) -> BillingProfileData:
    """Normaliza y valida. `InvalidBillingProfile` con todos los errores."""
    errors: list[FieldError] = []
    first = _name(data.first_names, "first_names", errors)
    last = _name(data.last_names, "last_names", errors)

    country = places.country(data.country_code.strip())
    if country is None:
        errors.append(FieldError("country_code", "Elige un país de la lista."))

    id_type: IdType | None = None
    if country is not None:
        allowed = id_types_for(country.code)
        if data.id_type in allowed:
            id_type = next(t for t in allowed if t == data.id_type)
        else:
            errors.append(FieldError("id_type", "Ese tipo de documento no aplica en ese país."))
    number = _id_number(data.id_number, id_type, errors) if id_type else data.id_number.strip()

    address = _spaces(data.address)
    if not address:
        errors.append(FieldError("address", "Es obligatoria."))
    elif len(address) > ADDRESS_MAX:
        errors.append(FieldError("address", f"Máximo {ADDRESS_MAX} caracteres."))
    elif _CONTROL.search(data.address.replace("\n", " ").replace("\t", " ")):
        errors.append(FieldError("address", "Tiene caracteres no válidos."))

    city = None
    if country is not None:
        city = places.find(country.code, data.state_code.strip(), data.city_code.strip())
        if city is None:
            errors.append(FieldError("city", "Elige una ciudad de la lista."))

    if errors or country is None or id_type is None or city is None:
        raise InvalidBillingProfile(errors)
    return BillingProfileData(
        first_names=first,
        last_names=last,
        country_code=city.country_code,
        id_type=id_type,
        id_number=number,
        address=address,
        state_code=city.state_code,
        city_code=city.city_code,
        city=city,
    )
