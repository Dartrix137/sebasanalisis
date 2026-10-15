"""Cuando aplica el traslado de un precio nuevo a una suscripcion vigente
(docs/PLATAFORMA_COMPLETA.md §4.10 y §10 n.º 5). Puro: sin base ni red.

Decidido el 2026-10-14:

- **Subida**: el precio nuevo se cobra desde 30 dias despues de que el aviso
  le llego a ESE cliente, no desde que se registro el traslado. Mientras el
  aviso no haya salido, no hay fecha.
- **Bajada**: solo beneficia al cliente; aplica de inmediato, desde su proximo
  cobro o pago, y el aviso es informativo.
- Un cupon que todavia descuenta sigue descontando sobre el precio nuevo: eso
  lo hace `pricing.renewal_quote`, que calcula desde el precio que reciba.

Decidido el 2026-10-15, en la renovacion automatica:

- **Un periodo se cobra con un solo precio**: el que corre en su primer
  intento programado (`schedule.first_charge_at`), que es el que dice el aviso
  de 7 dias. Una subida que empieza a correr entre ese intento y un reintento
  no cambia el monto de los reintentos; una bajada si, porque solo favorece al
  cliente.
- Por eso la pantalla y el correo de una subida dicen desde que COBRO se paga
  el precio nuevo (`first_charge_with_new_price`), no solo desde que fecha
  corre: con la fecha sola parecia que el cobro siguiente ya iba con el nuevo.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from app.billing import schedule
from app.billing.periods import Interval, add_interval

#: Dias entre el aviso de una subida y el primer cobro con el precio nuevo.
#: Pendiente de que lo confirme el abogado.
INCREASE_NOTICE_DAYS = 30


class Direction(str, Enum):
    increase = "increase"
    decrease = "decrease"


def direction(old_price_cents: int, new_price_cents: int) -> Direction:
    if old_price_cents == new_price_cents:
        raise ValueError("Un traslado cambia el precio: el viejo y el nuevo no pueden ser iguales")
    return Direction.increase if new_price_cents > old_price_cents else Direction.decrease


def effective_at(
    old_price_cents: int, new_price_cents: int, *, registered_at: datetime, notice_sent_at: datetime | None
) -> datetime | None:
    """Desde cuando se cobra el precio nuevo. None si todavia no se sabe: una
    subida cuyo aviso no ha salido."""
    if direction(old_price_cents, new_price_cents) is Direction.decrease:
        return registered_at
    if notice_sent_at is None:
        return None
    return notice_sent_at + timedelta(days=INCREASE_NOTICE_DAYS)


@dataclass(frozen=True)
class PendingChange:
    new_price_cents: int
    #: None mientras no se sepa (subida sin aviso).
    effective_at: datetime | None


def price_at(frozen_price_cents: int, pending: PendingChange | None, moment: datetime) -> int:
    """El precio que corre en `moment`: el congelado, o el nuevo si ya aplica."""
    if pending is None or pending.effective_at is None or moment < pending.effective_at:
        return frozen_price_cents
    return pending.new_price_cents


@dataclass(frozen=True)
class AppliedChange:
    """Un traslado ya aplicado a la suscripcion: `price_cents` ya es el nuevo."""

    old_price_cents: int
    new_price_cents: int
    effective_at: datetime


def charge_price(
    frozen_price_cents: int,
    pending: PendingChange | None,
    applied: Iterable[AppliedChange],
    first_charge_at: datetime,
) -> int:
    """El precio de los tres intentos del cobro automatico de un periodo: el
    que corria en el primero (`first_charge_at`).

    Si el job ya aplico una subida que empezo a correr despues de ese momento,
    los reintentos siguen con el precio de antes. Una bajada aplicada despues
    no se deshace: el reintento sale con el precio menor.
    """
    price = price_at(frozen_price_cents, pending, first_charge_at)
    for change in applied:
        increase = direction(change.old_price_cents, change.new_price_cents) is Direction.increase
        if increase and change.effective_at > first_charge_at:
            price = min(price, change.old_price_cents)
    return price


def first_charge_with_new_price(
    effective_at: datetime, period_end: datetime, interval: Interval, interval_count: int
) -> datetime:
    """El primer cobro automatico que se hace con el precio nuevo: el primer
    intento del primer periodo que empieza a cobrarse en `effective_at` o
    despues. Los periodos se encadenan desde `period_end`, como las renovaciones.
    """
    end = period_end
    while schedule.first_charge_at(end) < effective_at:
        end = add_interval(end, interval, interval_count)
    return schedule.first_charge_at(end)
