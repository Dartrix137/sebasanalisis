"""Estimaciones estadisticas propias, una por deporte (§8.5).

Un modelo se ajusta con los partidos anteriores a una fecha y devuelve, para un
partido, la probabilidad que le da a cada resultado. **Nunca ve un partido de
la fecha que estima ni posterior**: el backtest solo le pasa el pasado, y cada
modelo filtra ademas por su cuenta (`history_before`), por si alguien lo llama
de otra forma. Una fuga de datos futuros haria pasar por bueno un modelo que no
lo es, y ningun numero del informe lo dejaria ver.

Una estimacion es solo eso: la frecuencia que el modelo le asigna a cada
resultado a partir de los anteriores. No anticipa el partido.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from app.engine.sports.events import Event


class FittedModel(Protocol):
    def estimate(self, home: str, away: str) -> dict[str, float] | None:
        """Probabilidad por resultado; None si el modelo no conoce a algun equipo."""
        ...


class Model(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def outcomes(self) -> tuple[str, ...]: ...

    def fit(self, history: Sequence[Event], as_of: date) -> FittedModel:
        """Ajusta solo con los partidos jugados antes de `as_of`."""
        ...


def history_before(history: Sequence[Event], as_of: date) -> list[Event]:
    """Los partidos jugados estrictamente antes de `as_of`, en orden cronologico."""
    past = [e for e in history if e.date < as_of and e.finished]
    past.sort(key=lambda e: (e.date, e.event_id))
    return past
