"""El contenido de la factura electronica: montos, textos, llave de idempotencia y
como se clasifica un error de Siigo (docs/PLATAFORMA_COMPLETA.md §3.17, "Paso
5.4", puntos 3, 4, 6 y 7; Fase 5, paso 5.4).

Python puro: sin FastAPI, sin SQLAlchemy, sin red. Quien llama a Siigo es
`invoicing/siigo.py` y quien guarda es `core/invoices.py`.

Lo decidido:
- La factura va en pesos (forma A): sin el objeto `currency` de Siigo, con el
  precio en pesos. Siigo recibe los valores con hasta 2 decimales en los pagos y
  redondea cada linea a 2 decimales; aqui el monto en pesos sale de los
  centavos de `billing/fx.to_cop_cents`, asi que ya viene exacto al centavo.
- La suscripcion va excluida de IVA (art. 476 num. 21 del Estatuto Tributario;
  la contadora): un item sin impuestos, con precio igual al total.
- `observations` lleva el parrafo de la exclusion, el valor en euros y las dos
  tasas con su fecha y su fuente.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

#: El parrafo que pide la contadora al pie de la factura.
VAT_EXCLUSION_NOTE = (
    "IVA: Operación excluida del IVA, conforme al artículo 476, numeral 21, "
    "del Estatuto Tributario."
)

#: Siigo admite `observations` de hasta 4.000 caracteres.
OBSERVATIONS_MAX = 4000

#: La `Idempotency-Key` de Siigo: alfanumerica, de hasta 30 caracteres (su
#: pagina de idempotencia; la de errores dice 32). Un UUID en base 36 cabe en 25.
IDEMPOTENCY_KEY_LENGTH = 25
_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def idempotency_key(invoice_id: uuid.UUID, kind: Literal["FV", "NC"] = "FV") -> str:
    """La llave de un documento: la misma en todos los reintentos.

    La factura (`FV`) usa el id en base 36; la nota credito (`NC`) lo antepone
    con una letra para que no choque con la de su factura.
    """
    n = invoice_id.int
    digits = []
    while n:
        n, r = divmod(n, 36)
        digits.append(_BASE36[r])
    key = "".join(reversed(digits)).rjust(IDEMPOTENCY_KEY_LENGTH, "0")
    return key if kind == "FV" else "n" + key[1:]


def pesos(cop_cents: int) -> Decimal:
    """Los centavos de peso como el valor con 2 decimales que recibe Siigo."""
    if isinstance(cop_cents, bool) or not isinstance(cop_cents, int) or cop_cents <= 0:
        raise ValueError("El monto en pesos va en centavos enteros mayores que cero")
    return (Decimal(cop_cents) / 100).quantize(Decimal("0.01"))


def _money(cents: int, currency: str) -> str:
    """32,00 EUR o 115.339,27 COP: como se escribe en Colombia."""
    whole, frac = divmod(cents, 100)
    return f"{whole:,}".replace(",", ".") + f",{frac:02d} {currency}"


def _rate(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        integer, decimals = text.split(".")
    else:
        integer, decimals = text, ""
    grouped = f"{int(integer):,}".replace(",", ".")
    return grouped + ("," + decimals if decimals else "")


def _day(value: date) -> str:
    return value.strftime("%d/%m/%Y")


@dataclass(frozen=True)
class FrozenRates:
    """Las tasas que la factura congelo, con el dia y la fuente de cada una."""

    eur_usd: Decimal | None
    eur_usd_date: date | None
    eur_usd_source: str | None
    usd_cop: Decimal
    usd_cop_date: date
    usd_cop_source: str


def observations(
    *,
    paid_cents: int,
    paid_currency: str,
    cop_cents: int,
    rates: FrozenRates | None,
    payment_reference: str,
) -> str:
    """El texto de `observations`: la exclusion del IVA, lo pagado en su moneda,
    las tasas y la referencia del pago (para encontrar la factura desde Siigo)."""
    parts = [VAT_EXCLUSION_NOTE]
    if paid_currency != "COP":
        if rates is None:
            raise ValueError("Un pago en otra moneda necesita sus tasas")
        parts.append(f"Valor pagado: {_money(paid_cents, paid_currency)}.")
        if rates.eur_usd is not None and rates.eur_usd_date and rates.eur_usd_source:
            parts.append(
                f"Tasa EUR/USD del {_day(rates.eur_usd_date)}: {_rate(rates.eur_usd)}"
                f" ({rates.eur_usd_source})."
            )
        parts.append(
            f"TRM del {_day(rates.usd_cop_date)}: {_rate(rates.usd_cop)} COP/USD"
            f" ({rates.usd_cop_source})."
        )
        parts.append(f"Valor en pesos: {_money(cop_cents, 'COP')}.")
    parts.append(f"Referencia del pago: {payment_reference}.")
    text = " ".join(parts)
    if len(text) > OBSERVATIONS_MAX:
        raise ValueError("Las observaciones superan el tope de Siigo")
    return text


# ---------- Errores de Siigo ----------

ErrorKind = Literal["transient", "config", "invalid"]

#: Pasajeros: se reintentan en otra corrida (codigos de "Manejo de errores").
#: `documents_service` no esta: en la empresa de pruebas (2026-11-09) llego
#: con "Your request could not be completed with the data you submitted", por
#: un tipo de comprobante que pide centro de costo. Es de datos, no pasajero.
TRANSIENT_CODES = frozenset(
    {
        "requests_limit",
        "request_timeout",
        "service_unavailable",
        "payment_types_service",
        "general_service",
    }
)

#: De configuracion de la cuenta: detienen toda la corrida (el "freno"), porque
#: mientras no se corrijan ninguna factura se puede emitir, y reintentar a
#: ciegas lleva al bloqueo por el 80 % de errores.
CONFIG_CODES = frozenset(
    {
        "company_settings",
        "document_settings",
        "invalid_reference",
        "parameter_inactive",
        "invalid_dian_resolution",
        "unauthorized",
        "header_required",
        "invalid_partner_id",
        "blocked_transactions",
        "invalid_plan_type",
    }
)


def classify(status_code: int, codes: list[str]) -> ErrorKind:
    """Que hacer con una respuesta de error de Siigo."""
    if status_code == 429 or status_code >= 500 or any(c in TRANSIENT_CODES for c in codes):
        return "transient"
    if status_code in (401, 403) or any(c in CONFIG_CODES for c in codes):
        return "config"
    return "invalid"
