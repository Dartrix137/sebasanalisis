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
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

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
