"""La nota credito: su motivo, su valor en pesos y su texto (docs/PLATAFORMA_COMPLETA.md
§3.17, "Paso 5.4", punto 12; Fase 5, paso 5.4).

Python puro: sin FastAPI, sin SQLAlchemy, sin red. Quien decide cuando hay nota
credito y la guarda es `core/credit_notes.py`; quien la manda, `invoicing/`.

Lo que respondio la contadora (2026-11-11):

- Reembolso de todo el valor: motivo **2**, "Anulacion de factura
  electronica". De una parte (los dias que no uso): motivo **1**, "Devolucion
  parcial de los bienes y/o no aceptacion parcial del servicio". Son los
  codigos de la DIAN que lista Siigo en "Crear nota credito"
  (`developers.siigo.com/docs/siigoapi/credit-note/1-create-credit-note/` y
  `CreditNoteIn` de `jsapi.apiary.io/apis/siigoapi.apib`, leidos el
  2026-11-11): 1, 2, 3, 4, 6 y 7.
- "El valor en la nota credito debe ser la misma que en la factura y el mismo
  en la transferencia, sin importar el cambio": se convierte con las tasas
  congeladas de la factura, nunca con las del dia del reembolso.

El valor en pesos de cada nota sale de lo acumulado: si antes de esta nota ya
se devolvieron `a` centavos de euro y esta devuelve `b`, vale
`pesos(a + b) - pesos(a)`, con `pesos` la misma conversion de la factura
(`billing/fx.to_cop_cents`). Asi la suma de todas las notas de una factura
nunca pasa de su valor en pesos, y la iguala al centavo cuando se devolvio
todo, sin importar el redondeo de cada una.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from app.billing import fx
from app.billing.invoice_document import (
    OBSERVATIONS_MAX,
    VAT_EXCLUSION_NOTE,
    FrozenRates,
    format_day,
    format_money,
    format_rate,
)

#: Motivo de la DIAN: anulacion de la factura electronica (reembolso total).
REASON_ANNULMENT = 2
#: Motivo de la DIAN: devolucion parcial / no aceptacion parcial del servicio.
REASON_PARTIAL = 1

CreditNoteReason = Literal[1, 2]


def reason_for(amount_cents: int, paid_cents: int) -> CreditNoteReason:
    """2 si la nota devuelve todo lo que se pago, 1 si es una parte.

    Varias devoluciones parciales que terminan sumando el total van cada una
    con el 1: ninguna, por si sola, anula la factura."""
    _check_cents("amount_cents", amount_cents)
    _check_cents("paid_cents", paid_cents)
    if amount_cents > paid_cents:
        raise ValueError("La nota credito no puede devolver mas de lo pagado")
    if amount_cents == paid_cents:
        return 2  # REASON_ANNULMENT
    return 1  # REASON_PARTIAL


def _check_cents(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} va en centavos enteros mayores que cero")


def _to_cop(cents: int, currency: str, rates: fx.Rates) -> int:
    return 0 if cents == 0 else fx.to_cop_cents(cents, currency, rates)


def cop_cents_for(
    *,
    credited_before_cents: int,
    amount_cents: int,
    paid_cents: int,
    currency: str,
    rates: fx.Rates,
    invoice_cop_cents: int,
) -> int:
    """Los centavos de peso de una nota que devuelve `amount_cents` (en la
    moneda del pago), cuando ya se devolvieron `credited_before_cents` con
    otras notas de la misma factura.

    `rates` son las tasas congeladas de la factura e `invoice_cop_cents` su
    valor en pesos. Si se devuelve todo, la ultima nota cierra exacto contra
    el valor de la factura."""
    _check_cents("amount_cents", amount_cents)
    _check_cents("paid_cents", paid_cents)
    _check_cents("invoice_cop_cents", invoice_cop_cents)
    if isinstance(credited_before_cents, bool) or credited_before_cents < 0:
        raise ValueError("Lo devuelto antes no puede ser negativo")
    after = credited_before_cents + amount_cents
    if after > paid_cents:
        raise ValueError("Las notas credito no pueden devolver mas de lo pagado")

    def total(cents: int) -> int:
        # Lo pagado entero vale lo que dice la factura: es la misma conversion,
        # y asi no depende de que se haya redondeado igual.
        return invoice_cop_cents if cents == paid_cents else _to_cop(cents, currency, rates)

    value = total(after) - total(credited_before_cents)
    if value <= 0:
        raise ValueError("La nota credito quedaria en cero pesos")
    if total(after) > invoice_cop_cents:
        raise ValueError("Las notas credito pasarian del valor de la factura")
    return value


def observations(
    *,
    invoice_name: str,
    reason: CreditNoteReason,
    amount_cents: int,
    currency: str,
    cop_cents: int,
    rates: FrozenRates | None,
    payment_reference: str,
    invoice_issue_date: date | None,
) -> str:
    """El texto de `observations` de la nota: a que factura corrige, por que,
    lo devuelto en la moneda del pago y las tasas de la factura que usa."""
    kind = "reembolso total" if reason == REASON_ANNULMENT else "reembolso parcial"
    of_day = f" del {format_day(invoice_issue_date)}" if invoice_issue_date else ""
    parts = [f"Nota crédito de la factura {invoice_name}{of_day}, por {kind}.", VAT_EXCLUSION_NOTE]
    if currency != fx.FUNCTIONAL_CURRENCY:
        if rates is None:
            raise ValueError("Una nota de un pago en otra moneda necesita las tasas de su factura")
        parts.append(f"Valor devuelto: {format_money(amount_cents, currency)}.")
        parts.append("Con las tasas de la factura:")
        if rates.eur_usd is not None and rates.eur_usd_date and rates.eur_usd_source:
            parts.append(
                f"Tasa EUR/USD del {format_day(rates.eur_usd_date)}: {format_rate(rates.eur_usd)}"
                f" ({rates.eur_usd_source})."
            )
        parts.append(
            f"TRM del {format_day(rates.usd_cop_date)}: {format_rate(rates.usd_cop)} COP/USD"
            f" ({rates.usd_cop_source})."
        )
    parts.append(f"Valor en pesos: {format_money(cop_cents, 'COP')}.")
    parts.append(f"Referencia del pago: {payment_reference}.")
    text = " ".join(parts)
    if len(text) > OBSERVATIONS_MAX:
        raise ValueError("Las observaciones superan el tope de Siigo")
    return text
