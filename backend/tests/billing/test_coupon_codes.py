"""Codigos de cupon: forma y filtro de terminologia (§4.5)."""

import pytest

from app.billing.coupon_codes import (
    MAX_LENGTH,
    InvalidCouponCodeError,
    normalize_code,
    validate_code,
)


def test_se_normaliza_a_mayusculas_y_sin_espacios() -> None:
    assert normalize_code("  bienvenida-10 ") == "BIENVENIDA-10"


@pytest.mark.parametrize("code", ["BIENVENIDA10", "OCT-2026", "AMIGOS_15", "A1B", "X" * MAX_LENGTH])
def test_codigos_validos(code: str) -> None:
    validate_code(code)


@pytest.mark.parametrize(
    "code",
    ["", "AB", "X" * (MAX_LENGTH + 1), "-INICIO", "CON ESPACIO", "PROMOCIÓN", "bienvenida", "A.B.C"],
)
def test_codigos_con_mala_forma(code: str) -> None:
    with pytest.raises(InvalidCouponCodeError):
        validate_code(code)


@pytest.mark.parametrize(
    "code",
    [
        "GANASEGURO",
        "GANA-SEGURO",
        "GANA_YA",
        "GARANTIZADO",
        "INFALIBLE20",
        "PREDICCION",
        "VENTAJA10",
        "ACIERTO",
        "WIN50",
        "SUERTE",
        "PREMIO-OCT",
    ],
)
def test_ningun_codigo_promete_resultados(code: str) -> None:
    with pytest.raises(InvalidCouponCodeError, match="promete resultados"):
        validate_code(code)
