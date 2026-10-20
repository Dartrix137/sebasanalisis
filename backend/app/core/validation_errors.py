"""Errores de validacion de la API en espanol (paso 9 de la Fase 4).

Pydantic escribe sus mensajes en ingles ("value is not a valid email address:
..."), y el frontend muestra el `msg` tal cual. Un correo como `a@b` lo acepta
el navegador y lo rechaza la API, asi que ese texto en ingles le llegaba al
usuario. Aqui se traduce cada error por su `type`.

La forma de la respuesta no cambia (`{"detail": [{loc, msg, type}]}`, la misma
del 422 de FastAPI), salvo que no devuelve `input` ni `ctx`: `input` repetia lo
que mando el cliente (una contrasena, por ejemplo) y `ctx` no hace falta.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Tipos de error de Pydantic -> mensaje. Los que llevan `{...}` toman el valor
# del `ctx` del error (el minimo, el maximo).
_MESSAGES: dict[str, str] = {
    "missing": "Falta un dato obligatorio.",
    "string_too_short": "Debe tener al menos {min_length} caracteres.",
    "string_too_long": "Puede tener como máximo {max_length} caracteres.",
    "string_type": "Debe ser un texto.",
    "too_short": "Faltan elementos: el mínimo es {min_length}.",
    "too_long": "Sobran elementos: el máximo es {max_length}.",
    "greater_than": "Debe ser mayor que {gt}.",
    "greater_than_equal": "Debe ser mayor o igual a {ge}.",
    "less_than": "Debe ser menor que {lt}.",
    "less_than_equal": "Debe ser menor o igual a {le}.",
    "int_parsing": "Debe ser un número entero.",
    "int_type": "Debe ser un número entero.",
    "int_from_float": "Debe ser un número entero.",
    "float_parsing": "Debe ser un número.",
    "float_type": "Debe ser un número.",
    "bool_parsing": "Debe ser verdadero o falso.",
    "bool_type": "Debe ser verdadero o falso.",
    "enum": "No es una de las opciones válidas.",
    "literal_error": "No es una de las opciones válidas.",
    "uuid_parsing": "El identificador no es válido.",
    "uuid_type": "El identificador no es válido.",
    "date_parsing": "La fecha no es válida.",
    "date_from_datetime_parsing": "La fecha no es válida.",
    "datetime_parsing": "La fecha y hora no son válidas.",
    "datetime_from_date_parsing": "La fecha y hora no son válidas.",
    "list_type": "Debe ser una lista.",
    "dict_type": "Debe ser un objeto.",
    "model_attributes_type": "Debe ser un objeto.",
    "json_invalid": "La solicitud no es un JSON válido.",
    "url_parsing": "La dirección no es válida.",
}

# Los tipos de los `PydanticCustomError` del proyecto (`schemas/auth.py`).
_OWN_TYPES = frozenset({"password_policy"})

_INVALID_EMAIL = "El correo no es válido."
_FALLBACK = "Hay un dato que no es válido."
# Pydantic antepone esto al mensaje de un ValueError lanzado por un validador
# propio; el resto del mensaje ya esta en espanol.
_VALUE_ERROR_PREFIX = "Value error, "


def translate_error(error: Mapping[str, Any]) -> str:
    """El mensaje en espanol de un error de Pydantic."""
    kind = str(error.get("type", ""))
    msg = str(error.get("msg", ""))
    ctx = error.get("ctx") or {}

    if kind == "value_error":
        # EmailStr falla como value_error con el texto de email-validator.
        if msg.startswith("value is not a valid email address"):
            return _INVALID_EMAIL
        if msg.startswith(_VALUE_ERROR_PREFIX):
            return msg[len(_VALUE_ERROR_PREFIX) :]
        return _FALLBACK

    template = _MESSAGES.get(kind)
    if template is not None:
        try:
            return template.format(**ctx)
        except (KeyError, IndexError):
            return _FALLBACK

    # Errores propios (PydanticCustomError): su mensaje ya esta escrito para el
    # usuario. Cualquier otro tipo de Pydantic sale con el mensaje generico, en
    # vez de dejar pasar el ingles.
    if kind in _OWN_TYPES:
        return msg
    return _FALLBACK


def translate_errors(errors: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """La lista del 422, con cada `msg` en espanol y sin `input` ni `ctx`."""
    return [
        {"loc": list(e.get("loc", ())), "msg": translate_error(e), "type": e.get("type", "")}
        for e in errors
    ]


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(status_code=422, content={"detail": translate_errors(exc.errors())})
