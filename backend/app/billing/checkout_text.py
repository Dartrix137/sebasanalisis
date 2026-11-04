"""Los textos del producto que viajan a la pasarela (Fase 5, paso 5.3).

Tipster Page firma `product_name` y `product_description` dentro de
`tspay_signature`, y no dice con que codificacion firma un texto con tildes:
se mandan solo en ASCII imprimible (decidido el 2026-11-03, pregunta 6 de
"Paso 5.3" en `docs/HOJA_DE_RUTA.md`). Los armamos nosotros: no salen de
`plans.description`, que es texto libre del administrador.

Puro, sin base de datos ni red, con mypy estricto.
"""

import unicodedata

#: Tope de largo de cada texto. El manual no fija uno; los nuestros son cortos.
MAX_LENGTH = 100

_BRAND = "Sebasanalisis"


def ascii_text(value: str, max_length: int = MAX_LENGTH) -> str:
    """`"Acceso Bimestral ñ"` -> `"Acceso Bimestral n"`.

    Quita las tildes (descompone y descarta las marcas), descarta lo que siga
    fuera de ASCII imprimible y junta los espacios. Un texto que queda vacio es
    un error: la pasarela lo exige.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    kept = "".join(ch for ch in decomposed if " " <= ch <= "~")
    collapsed = " ".join(kept.split())[:max_length].strip()
    if not collapsed:
        raise ValueError("El texto queda vacio en ASCII")
    return collapsed


def product_name(plan_name: str) -> str:
    """El nombre del plan, en ASCII."""
    return ascii_text(plan_name)


def product_description(interval: str, interval_count: int) -> str:
    """`month`, 2 -> `"Sebasanalisis: acceso por 2 meses"`.

    Un plan anual se dice en meses: "ano" sin la tilde dice otra cosa.
    """
    if interval_count < 1:
        raise ValueError("interval_count debe ser positivo")
    months_per_unit = {"month": 1, "year": 12}
    if interval not in months_per_unit:
        raise ValueError(f"Intervalo desconocido: {interval}")
    months = interval_count * months_per_unit[interval]
    unit = "mes" if months == 1 else "meses"
    return ascii_text(f"{_BRAND}: acceso por {months} {unit}")
