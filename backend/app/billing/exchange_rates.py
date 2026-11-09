"""Las tasas de cambio de la factura: leerlas de su fuente y elegir la del dia
del pago (docs/PLATAFORMA_COMPLETA.md §3.17, "Paso 5.4", punto 5; Fase 5, paso
5.4).

Python puro: sin FastAPI, sin SQLAlchemy, sin red. Quien consulta las fuentes y
guarda las tasas es `core/exchange_rates.py`.

Las dos fuentes (decididas por el usuario el 2026-11-09):

- **TRM (dolares a pesos)**: el historico abierto de la Superintendencia
  Financiera en datos.gov.co (conjunto `32sa-8pi3`; la Superfinanciera lo enlaza
  como `mcec-87by` y devuelven las mismas filas). Cada fila trae `valor`,
  `unidad` ("COP"), `vigenciadesde` y `vigenciahasta`, y la TRM de un fin de
  semana o un festivo viene como una sola fila que cubre esos dias (la del 31
  de octubre de 2026 va vigente hasta el 3 de noviembre). Es la regla del
  Decreto 1625 de 2016, art. 1.1.3 par. 2: un dia sin TRM certificada usa la del
  ultimo dia certificado antes. Por eso se busca la fila cuya vigencia cubre el
  dia, sin suponer dias habiles.
- **Euros a dolares**: la tasa de referencia del Banco Central Europeo
  (`https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml`), en
  dolares por euro, una por dia habil. La publica hacia las 16:00 de Francfort
  (las 10:00 en Colombia) y no la publica los sabados, los domingos ni los dias
  de cierre de TARGET. Un dia sin tasa usa la del ultimo dia publicado antes
  (la misma regla del par. 2).

Un dia habil cuya tasa todavia no salio (un pago a las 08:00 de Colombia, antes
de que publique el BCE) no usa la del dia anterior: la factura espera a la
corrida siguiente. Solo se sabe que un dia entre semana no tendra tasa cuando
la fuente ya publico un dia posterior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from xml.etree import ElementTree

Pair = Literal["USD/COP", "EUR/USD"]

TRM_SOURCE = "datos.gov.co/32sa-8pi3 (Superintendencia Financiera)"
ECB_SOURCE = "ecb.europa.eu eurofxref (Banco Central Europeo)"

#: Si la tasa anterior mas reciente esta a mas de estos dias, algo falla en la
#: fuente (el cierre de TARGET mas largo, en Navidad, deja cuatro dias seguidos
#: sin tasa): mejor esperar que usar una tasa vieja.
MAX_GAP_DAYS = 7

_ECB_NS = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"


class RateSourceError(ValueError):
    """La respuesta de la fuente no tiene la forma esperada."""


@dataclass(frozen=True)
class RatePeriod:
    """Una tasa con los dias que cubre (los dos incluidos)."""

    pair: Pair
    valid_from: date
    valid_to: date
    value: Decimal
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal) or not self.value.is_finite() or self.value <= 0:
            raise RateSourceError(f"Tasa invalida: {self.value!r}")
        if self.valid_to < self.valid_from:
            raise RateSourceError("La vigencia termina antes de empezar")

    def covers(self, day: date) -> bool:
        return self.valid_from <= day <= self.valid_to


def _decimal(raw: object) -> Decimal:
    if not isinstance(raw, str):
        raise RateSourceError(f"La tasa no viene como texto: {raw!r}")
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise RateSourceError(f"La tasa no es un numero: {raw!r}") from exc


def _day(raw: object) -> date:
    """`2026-10-31T00:00:00.000` o `2026-10-31`: solo cuenta la fecha."""
    if not isinstance(raw, str):
        raise RateSourceError(f"La fecha no viene como texto: {raw!r}")
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).date()
    except ValueError as exc:
        raise RateSourceError(f"Fecha invalida: {raw!r}") from exc


def parse_trm_rows(rows: object) -> list[RatePeriod]:
    """Las filas JSON de datos.gov.co, como `RatePeriod` de `USD/COP`."""
    if not isinstance(rows, list):
        raise RateSourceError("La respuesta de la TRM no es una lista")
    periods: list[RatePeriod] = []
    for row in rows:
        if not isinstance(row, dict):
            raise RateSourceError("Una fila de la TRM no es un objeto")
        if row.get("unidad") != "COP":
            raise RateSourceError(f"La TRM viene en otra unidad: {row.get('unidad')!r}")
        periods.append(
            RatePeriod(
                pair="USD/COP",
                valid_from=_day(row.get("vigenciadesde")),
                valid_to=_day(row.get("vigenciahasta")),
                value=_decimal(row.get("valor")),
                source=TRM_SOURCE,
            )
        )
    return periods


def parse_ecb_xml(xml: bytes) -> list[RatePeriod]:
    """El XML de referencia del BCE (el del dia o el de 90 dias), como
    `RatePeriod` de `EUR/USD` de un dia cada uno."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise RateSourceError("El XML del BCE no se pudo leer") from exc
    periods: list[RatePeriod] = []
    for cube in root.iter(f"{_ECB_NS}Cube"):
        time = cube.get("time")
        if time is None:
            continue
        day = _day(time)
        usd = [c for c in cube if c.get("currency") == "USD"]
        if len(usd) != 1:
            raise RateSourceError(f"El BCE no trae una tasa en dolares para {time}")
        periods.append(
            RatePeriod(
                pair="EUR/USD",
                valid_from=day,
                valid_to=day,
                value=_decimal(usd[0].get("rate")),
                source=ECB_SOURCE,
            )
        )
    if not periods:
        raise RateSourceError("El XML del BCE no trae ningun dia")
    return periods


def trm_for(day: date, periods: list[RatePeriod]) -> RatePeriod | None:
    """La TRM vigente el dia, o `None` si todavia no hay una que lo cubra."""
    found = [p for p in periods if p.pair == "USD/COP" and p.covers(day)]
    if len(found) > 1 and len({p.value for p in found}) > 1:
        raise RateSourceError(f"Dos TRM distintas cubren el {day.isoformat()}")
    return found[0] if found else None


def ecb_for(day: date, periods: list[RatePeriod]) -> RatePeriod | None:
    """La tasa del BCE del dia o, si ese dia no hubo, la del ultimo dia
    publicado antes. `None` si todavia no se sabe.

    - Hay tasa del dia: esa.
    - Sabado o domingo: el BCE nunca publica, y vale la anterior.
    - Entre semana sin tasa: si la fuente ya publico un dia posterior, ese dia
      fue de cierre y vale la anterior; si no, todavia puede salir y se espera.
    """
    ecb = sorted((p for p in periods if p.pair == "EUR/USD"), key=lambda p: p.valid_from)
    exact = [p for p in ecb if p.valid_from == day]
    if exact:
        return exact[-1]
    weekend = day.weekday() >= 5
    published_after = any(p.valid_from > day for p in ecb)
    if not weekend and not published_after:
        return None
    before = [p for p in ecb if p.valid_from < day]
    if not before:
        return None
    last = before[-1]
    if (day - last.valid_from) > timedelta(days=MAX_GAP_DAYS):
        raise RateSourceError(
            f"La tasa del BCE anterior al {day.isoformat()} es del {last.valid_from.isoformat()}"
        )
    return last
