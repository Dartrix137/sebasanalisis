"""Periodos que compra un pago (docs/PLATAFORMA_COMPLETA.md §3.5 y §3.10).

Python puro: sin FastAPI, sin SQLAlchemy, sin red.

Regla (decidida por el usuario el 2026-10-13): un pago hecho ANTES de que venza
el periodo vigente lo extiende desde ese vencimiento, para no quitar los dias
que quedaban; uno hecho despues, o el primero, cuenta desde el momento del pago.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Interval = Literal["month", "year"]


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime


def add_interval(start: datetime, interval: Interval, count: int) -> datetime:
    """`start` mas `count` meses o anos de calendario.

    Si el dia no existe en el mes de llegada se usa el ultimo de ese mes: del
    31 de enero se pasa al 28 (o 29) de febrero. La hora no cambia.
    """
    if count < 1:
        raise ValueError("El periodo debe durar al menos un intervalo")
    months = count * (12 if interval == "year" else 1)
    index = start.year * 12 + (start.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def next_period(
    now: datetime, paid_until: datetime | None, interval: Interval, count: int
) -> Period:
    """El periodo que compra un pago aprobado en `now`.

    `paid_until` es hasta cuando tiene acceso pagado la cuenta, si lo tiene.
    """
    start = paid_until if paid_until is not None and paid_until > now else now
    return Period(start=start, end=add_interval(start, interval, count))
