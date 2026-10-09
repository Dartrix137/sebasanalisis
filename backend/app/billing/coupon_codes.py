"""Forma y filtro de terminologia de los codigos de cupon (§4.5).

Python puro. Un codigo es texto que ve el cliente, asi que pasa la regla de
lenguaje del producto: ninguno promete resultados (nada tipo `GANASEGURO`).
"""

from __future__ import annotations

import re

MIN_LENGTH = 3
MAX_LENGTH = 40

_SHAPE = re.compile(r"[A-Z0-9][A-Z0-9_-]*")

#: Fragmentos que un codigo no puede contener. Se comparan sin guiones, para
#: que `GANA-SEGURO` no pase donde `GANASEGURO` no pasa. Es una lista corta y
#: tosca a proposito: prefiere rechazar un codigo inocente (el admin elige
#: otro) a dejar pasar uno que suene a promesa.
FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "ACERT",
    "ACIERT",
    "FORTUNA",
    "GANA",
    "GANE",
    "GARANT",
    "INFALIB",
    "JACKPOT",
    "PREDIC",
    "PREMIO",
    "SEGUR",
    "SUERTE",
    "VENTAJA",
    "WIN",
)


class InvalidCouponCodeError(ValueError):
    """El mensaje se le muestra tal cual al administrador."""


def normalize_code(raw: str) -> str:
    """Como se guarda y se busca un codigo: sin espacios alrededor y en mayusculas."""
    return raw.strip().upper()


def validate_code(code: str) -> None:
    """Revisa un codigo ya normalizado. Lanza `InvalidCouponCodeError` si no sirve."""
    if not MIN_LENGTH <= len(code) <= MAX_LENGTH:
        raise InvalidCouponCodeError(
            f"El código debe tener entre {MIN_LENGTH} y {MAX_LENGTH} caracteres"
        )
    if not _SHAPE.fullmatch(code):
        raise InvalidCouponCodeError(
            "El código solo lleva letras sin tilde, números, guion y guion bajo, "
            "y empieza por letra o número"
        )
    compact = code.replace("-", "").replace("_", "")
    for fragment in FORBIDDEN_FRAGMENTS:
        if fragment in compact:
            raise InvalidCouponCodeError(
                f"El código no puede contener «{fragment}»: ningún cupón promete resultados"
            )
