"""Fecha de la operacion y conversion a pesos de la factura electronica
(docs/PLATAFORMA_COMPLETA.md §3.17; Fase 5, paso 5.2).

Python puro: sin FastAPI, sin SQLAlchemy, sin red.

- **El dia de la operacion** es el dia en que se aprobo el pago, contado en
  hora de Colombia: un pago aprobado a las 03:00 UTC del 24 es del 23.
- **La factura va en pesos** (la moneda funcional). Un pago en otra moneda se
  convierte con la tasa del dia de la operacion. Para el euro, el Decreto 1625
  de 2016, art. 1.1.3 par. 1: de euros a dolares con la tasa del dia, y de
  dolares a pesos con la TRM de esa fecha.
- **Las tasas van en `Decimal`**, nunca en `float`, y los montos en centavos
  enteros. De donde salen las tasas, como se buscan por su vigencia y como se
  guardan en la factura es del paso 5.4.

**Provisional hasta que hable el contador**: el redondeo (`ROUNDING`) y que se
redondee una sola vez, al final. Cambiarlo es cambiar estas constantes y sus
tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

#: Hora de Colombia. No tiene horario de verano, asi que basta un desfase fijo
#: (el mismo criterio de `app/emails/render.py`) y no hace falta `tzdata`.
COLOMBIA = timezone(timedelta(hours=-5))

#: PROVISIONAL (lo confirma el contador): la mitad exacta sube.
ROUNDING = ROUND_HALF_UP

#: La moneda de la factura.
FUNCTIONAL_CURRENCY = "COP"


def operation_date(approved_at: datetime) -> date:
    """El dia de la operacion: el de la aprobacion del pago, en hora de Colombia."""
    if approved_at.tzinfo is None or approved_at.utcoffset() is None:
        raise ValueError("La hora de aprobacion necesita su zona horaria")
    return approved_at.astimezone(COLOMBIA).date()


def _check_rate(name: str, value: Decimal | None) -> None:
    if value is None:
        return
    # `bool` e `int` tambien se rechazan: una tasa siempre llega como Decimal,
    # y asi un `float` no se cuela convertido a medias.
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} debe ser Decimal, no {type(value).__name__}")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name} debe ser un numero mayor que cero")


@dataclass(frozen=True)
class Rates:
    """Las tasas del dia de la operacion."""

    #: Dolares por un euro.
    eur_usd: Decimal | None = None
    #: Pesos por un dolar: la TRM.
    usd_cop: Decimal | None = None

    def __post_init__(self) -> None:
        _check_rate("eur_usd", self.eur_usd)
        _check_rate("usd_cop", self.usd_cop)


def _required(name: str, value: Decimal | None, currency: str) -> Decimal:
    if value is None:
        raise ValueError(f"Para convertir {currency} a pesos falta la tasa {name}")
    return value


def to_cop_cents(amount_cents: int, currency: str, rates: Rates) -> int:
    """El monto del pago en centavos de peso.

    Se multiplica en `Decimal`, sin redondear en el camino, y se redondea una
    sola vez, al centavo (PROVISIONAL, ver el encabezado del modulo).
    """
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise TypeError("El monto va en centavos enteros")
    if amount_cents <= 0:
        raise ValueError("El monto debe ser mayor que cero")
    if currency == FUNCTIONAL_CURRENCY:
        return amount_cents
    if currency == "USD":
        factor = _required("usd_cop", rates.usd_cop, currency)
    elif currency == "EUR":
        factor = _required("eur_usd", rates.eur_usd, currency) * _required(
            "usd_cop", rates.usd_cop, currency
        )
    else:
        raise ValueError(f"No se sabe convertir {currency} a pesos")
    return int((Decimal(amount_cents) * factor).quantize(Decimal(1), rounding=ROUNDING))
