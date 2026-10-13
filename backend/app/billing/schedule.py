"""Calendario de cobros de la renovacion automatica (docs/PLATAFORMA_COMPLETA.md §3.5 y §3.8).

Python puro: sin FastAPI, sin SQLAlchemy, sin red. Aqui solo se decide CUANDO;
quien cobra y quien escribe en la base es `core/renewals.py`.

Reglas:

- Tres intentos de cobro por periodo: 48 h, 24 h y 0 h antes de
  `current_period_end`. Asi un fallo transitorio de la tarjeta no corta el
  acceso.
- No hay periodo de gracia: si los tres fallan, la suscripcion vence
  exactamente en `current_period_end`.
- Antes del primer intento se avisa por correo, con `NOTICE_DAYS` dias de
  anticipacion (decidido el 2026-10-13: 7). En el pago manual el aviso sale
  esos mismos dias antes del vencimiento.
- Si el job estuvo caido y hay intentos atrasados, se hacen de a uno por
  corrida, en orden: nunca dos cobros en la misma corrida.
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: Cuanto antes del vencimiento va cada intento, en orden.
ATTEMPT_OFFSETS: tuple[timedelta, ...] = (
    timedelta(hours=48),
    timedelta(hours=24),
    timedelta(hours=0),
)
MAX_ATTEMPTS = len(ATTEMPT_OFFSETS)

#: Dias de anticipacion del correo de aviso.
NOTICE_DAYS = 7


def attempt_time(period_end: datetime, attempt: int) -> datetime:
    """Cuando toca el intento `attempt` (1, 2 o 3) del periodo que vence en `period_end`."""
    if not 1 <= attempt <= MAX_ATTEMPTS:
        raise ValueError(f"El intento va de 1 a {MAX_ATTEMPTS}")
    return period_end - ATTEMPT_OFFSETS[attempt - 1]


def first_charge_at(period_end: datetime) -> datetime:
    """Cuando se intenta por primera vez el cobro del periodo siguiente."""
    return attempt_time(period_end, 1)


def next_attempt(now: datetime, period_end: datetime, attempts_made: int) -> int | None:
    """El numero del intento que toca hacer ahora, o None si no toca ninguno.

    `attempts_made` son los intentos ya hechos para este periodo, hayan
    terminado como hayan terminado.
    """
    if attempts_made < 0:
        raise ValueError("Los intentos hechos no pueden ser negativos")
    attempt = attempts_made + 1
    if attempt > MAX_ATTEMPTS:
        return None
    return attempt if now >= attempt_time(period_end, attempt) else None


def attempts_exhausted(attempts_made: int) -> bool:
    return attempts_made >= MAX_ATTEMPTS


def should_expire(
    now: datetime, period_end: datetime, attempts_made: int, *, attempt_in_flight: bool
) -> bool:
    """La suscripcion automatica vence: el periodo termino y no queda nada por intentar.

    Con un cobro todavia sin resolver no vence: puede que se apruebe.
    """
    return now >= period_end and not attempt_in_flight and attempts_exhausted(attempts_made)


def renewal_notice_due(now: datetime, period_end: datetime) -> bool:
    """Ya toca avisar del cobro automatico: `NOTICE_DAYS` antes del primer intento."""
    return now >= first_charge_at(period_end) - timedelta(days=NOTICE_DAYS)


def expiry_notice_due(now: datetime, period_end: datetime) -> bool:
    """Ya toca avisar, en el pago manual, de que el periodo esta por vencer."""
    return period_end - timedelta(days=NOTICE_DAYS) <= now < period_end
