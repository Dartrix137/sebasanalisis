"""El partido, generico sobre sus resultados posibles.

Un deporte se describe por sus resultados del mercado de resultado final: el
futbol tiene empate (`HOME_DRAW_AWAY`), el baloncesto o el tenis no
(`HOME_AWAY`). "Local" y "visitante" son solo los dos lados del partido: en un
deporte sin localia el modelo no le da ventaja a ninguno.

Las cuotas viajan como un dict por resultado. En el backtest son las del
conjunto historico; en la etapa 2 seran las que escriba el usuario.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

HOME = "home"
DRAW = "draw"
AWAY = "away"

HOME_DRAW_AWAY: tuple[str, ...] = (HOME, DRAW, AWAY)
HOME_AWAY: tuple[str, ...] = (HOME, AWAY)


@dataclass(frozen=True)
class Event:
    event_id: str
    competition: str
    season: str
    date: date
    home: str
    away: str
    #: Marcador final; None si el partido no se jugo (o el conjunto no lo trae).
    home_score: int | None = None
    away_score: int | None = None
    #: Cuotas decimales por resultado, al cierre y, si el conjunto las tiene, de apertura.
    closing_odds: Mapping[str, float] | None = None
    opening_odds: Mapping[str, float] | None = None

    @property
    def finished(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    def outcome(self, outcomes: Sequence[str]) -> str | None:
        """El resultado final en el vocabulario del deporte; None si no se jugo.

        Un empate en un deporte sin empate (un dato raro del conjunto) da None:
        no se puede liquidar un mercado de dos resultados con un tercero.
        """
        if self.home_score is None or self.away_score is None:
            return None
        if self.home_score > self.away_score:
            return HOME
        if self.home_score < self.away_score:
            return AWAY
        return DRAW if DRAW in outcomes else None


def odds_vector(odds: Mapping[str, float] | None, outcomes: Sequence[str]) -> list[float] | None:
    """Las cuotas en el orden de `outcomes`; None si falta alguna o es invalida."""
    if odds is None:
        return None
    vector: list[float] = []
    for o in outcomes:
        value = odds.get(o)
        if value is None or not value > 1.0:
            return None
        vector.append(float(value))
    return vector
