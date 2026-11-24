"""Deportes sin empate (local o visitante): Elo con ventaja de local.

Es la linea de partida para baloncesto, tenis y cualquier deporte de dos
resultados. Cada equipo arranca con `initial` puntos; despues de cada partido
el ganador le quita al perdedor

    K * (1 - E),   E = 1 / (1 + 10^((R_rival - R_propio - H) / 400))

donde `H` es la ventaja de local (0 en un deporte sin localia, como el tenis) y
`E` la probabilidad que el modelo le daba al ganador antes del partido. Esa
misma `E` es la estimacion del partido siguiente. `K` y `H` se eligen en
validacion.

Un empate en el conjunto (un dato raro en un deporte de dos resultados) no
mueve a nadie.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.engine.sports.events import AWAY, HOME, HOME_AWAY, Event
from app.engine.sports.models import history_before


def expected_home(rating_home: float, rating_away: float, home_advantage: float) -> float:
    exponent: float = (rating_away - rating_home - home_advantage) / 400.0
    return 1.0 / (1.0 + math.pow(10.0, exponent))


@dataclass(frozen=True)
class FittedElo:
    ratings: dict[str, float]
    games: dict[str, int]
    home_advantage: float
    min_games: int

    def estimate(self, home: str, away: str) -> dict[str, float] | None:
        if self.games.get(home, 0) < self.min_games or self.games.get(away, 0) < self.min_games:
            return None
        p = expected_home(self.ratings[home], self.ratings[away], self.home_advantage)
        return {HOME: p, AWAY: 1.0 - p}


@dataclass(frozen=True)
class Elo:
    k: float = 20.0
    home_advantage: float = 50.0
    initial: float = 1500.0
    #: Partidos minimos de un equipo para estimarlo.
    min_games: int = 10

    @property
    def name(self) -> str:
        return "elo"

    @property
    def outcomes(self) -> tuple[str, ...]:
        return HOME_AWAY

    def fit(self, history: Sequence[Event], as_of: date) -> FittedElo:
        ratings: dict[str, float] = {}
        games: Counter[str] = Counter()
        for e in history_before(history, as_of):
            rh = ratings.setdefault(e.home, self.initial)
            ra = ratings.setdefault(e.away, self.initial)
            games[e.home] += 1
            games[e.away] += 1
            result = e.outcome(HOME_AWAY)
            if result is None:
                continue
            expected = expected_home(rh, ra, self.home_advantage)
            actual = 1.0 if result == HOME else 0.0
            delta = self.k * (actual - expected)
            ratings[e.home] = rh + delta
            ratings[e.away] = ra - delta
        return FittedElo(dict(ratings), dict(games), self.home_advantage, self.min_games)
