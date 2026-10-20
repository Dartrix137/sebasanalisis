"""Errores de validacion en espanol (core/validation_errors.py)."""

from typing import Any

import pytest
from pydantic import BaseModel, EmailStr, Field, ValidationError

from app.core.validation_errors import translate_error, translate_errors


class _Modelo(BaseModel):
    email: EmailStr
    nombre: str = Field(min_length=3, max_length=5)
    monto: int = Field(gt=0)


def _errores(data: dict[str, Any]) -> list[dict[str, Any]]:
    with pytest.raises(ValidationError) as exc:
        _Modelo.model_validate(data)
    return [dict(e) for e in exc.value.errors()]


def test_un_correo_invalido_sale_en_espanol() -> None:
    errores = _errores({"email": "a@b", "nombre": "abc", "monto": 1})
    assert translate_error(errores[0]) == "El correo no es válido."


@pytest.mark.parametrize(
    ("data", "esperado"),
    [
        ({"email": "x@ejemplo.com", "nombre": "ab", "monto": 1}, "Debe tener al menos 3 caracteres."),
        ({"email": "x@ejemplo.com", "nombre": "abcdef", "monto": 1}, "Puede tener como máximo 5 caracteres."),
        ({"email": "x@ejemplo.com", "nombre": "abc", "monto": 0}, "Debe ser mayor que 0."),
        ({"email": "x@ejemplo.com", "nombre": "abc", "monto": "diez"}, "Debe ser un número entero."),
        ({"nombre": "abc", "monto": 1}, "Falta un dato obligatorio."),
    ],
)
def test_los_errores_comunes_salen_en_espanol(data: dict[str, Any], esperado: str) -> None:
    assert translate_error(_errores(data)[0]) == esperado


def test_un_value_error_propio_pierde_el_prefijo() -> None:
    error = {"type": "value_error", "msg": "Value error, La apuesta base no puede superar la banca"}
    assert translate_error(error) == "La apuesta base no puede superar la banca"


def test_un_error_propio_conserva_su_mensaje() -> None:
    error = {"type": "password_policy", "msg": "La contraseña debe tener al menos 10 caracteres"}
    assert translate_error(error) == "La contraseña debe tener al menos 10 caracteres"


def test_un_tipo_desconocido_no_deja_pasar_el_ingles() -> None:
    error = {"type": "decimal_max_digits", "msg": "Decimal input should have no more than 4 digits"}
    assert translate_error(error) == "Hay un dato que no es válido."


def test_la_lista_no_devuelve_lo_que_mando_el_cliente() -> None:
    errores = _errores({"email": "a@b", "nombre": "abc", "monto": 1})
    (salida,) = translate_errors(errores)
    assert set(salida) == {"loc", "msg", "type"}
    assert salida["loc"] == ["email"]
