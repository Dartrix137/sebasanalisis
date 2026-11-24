"""Ligas simuladas para probar el backtest, nunca para medir un modelo.

Sirven para lo mismo que las ruedas justas del backtest de la ruleta: comprobar
que las cuentas del backtest dan lo que tienen que dar cuando se sabe la verdad.

- Con un **mercado informado** (la cuota sale de la probabilidad verdadera mas
  el margen), ningun modelo puede superarlo: el veredicto tiene que fallar.
- Con un **mercado desinformado** (la misma probabilidad para todos los
  partidos), un modelo con algo de informacion tiene que describir mejor los
  resultados.

Un resultado bueno sobre estas ligas no dice nada de una liga real.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from scipy.stats import poisson

from app.engine.sports.events import AWAY, DRAW, HOME, HOME_AWAY, Event


@dataclass(frozen=True)
class SyntheticMarket:
    #: Margen de la casa: las probabilidades implicitas suman 1 + margin.
    margin: float = 0.05
    #: True: la cuota sale de la probabilidad verdadera. False: de una constante.
    informed: bool = True
    #: Ruido en escala log sobre la probabilidad del mercado (0 = sin ruido).
    noise: float = 0.0


def _round_robin(teams: list[str]) -> list[list[tuple[str, str]]]:
    """Doble vuelta por el metodo del circulo: cada equipo juega una vez por jornada."""
    names = list(teams)
    if len(names) % 2:
        names.append("")
    n = len(names)
    rounds: list[list[tuple[str, str]]] = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = names[i], names[n - 1 - i]
            if a and b:
                pairs.append((a, b) if r % 2 == 0 else (b, a))
        rounds.append(pairs)
        names = [names[0], names[-1], *names[1:-1]]
    return rounds + [[(b, a) for a, b in pairs] for pairs in rounds]


def _market_odds(
    true_probs: list[float],
    flat_probs: list[float],
    market: SyntheticMarket,
    rng: np.random.Generator,
) -> dict[int, float]:
    base = true_probs if market.informed else flat_probs
    if market.noise > 0:
        logits = np.log(base) + rng.normal(0.0, market.noise, len(base))
        weights = np.exp(logits)
        base = [float(w) for w in weights / weights.sum()]
    return {i: 1.0 / (p * (1.0 + market.margin)) for i, p in enumerate(base)}


def football_league(
    n_teams: int = 10,
    n_seasons: int = 6,
    seed: int = 0,
    market: SyntheticMarket | None = None,
    competition: str = "SYN-FUT",
    start: date = date(2015, 8, 1),
    spread: float = 0.35,
    home_advantage: float = 0.25,
) -> list[Event]:
    """Liga de futbol con goles Poisson y fuerzas fijas, una jornada por semana."""
    market = market or SyntheticMarket()
    rng = np.random.default_rng(seed)
    teams = [f"Equipo {i + 1:02d}" for i in range(n_teams)]
    attack = dict(zip(teams, rng.normal(0.0, spread, n_teams), strict=True))
    defence = dict(zip(teams, rng.normal(0.0, spread, n_teams), strict=True))
    goals = np.arange(11)
    flat = [0.45, 0.27, 0.28]

    events: list[Event] = []
    for s in range(n_seasons):
        season = f"{start.year + s}-{start.year + s + 1}"
        season_start = start + timedelta(days=365 * s)
        for r, pairs in enumerate(_round_robin(teams)):
            day = season_start + timedelta(days=7 * r)
            for n, (h, a) in enumerate(pairs):
                lam = math.exp(home_advantage + attack[h] - defence[a])
                mu = math.exp(attack[a] - defence[h])
                matrix = np.outer(poisson.pmf(goals, lam), poisson.pmf(goals, mu))
                total = matrix.sum()
                true = [
                    float(np.tril(matrix, -1).sum() / total),
                    float(np.trace(matrix) / total),
                    float(np.triu(matrix, 1).sum() / total),
                ]
                odds = _market_odds(true, flat, market, rng)
                events.append(
                    Event(
                        event_id=f"{competition}-{season}-{r:02d}-{n:02d}",
                        competition=competition,
                        season=season,
                        date=day,
                        home=h,
                        away=a,
                        home_score=int(rng.poisson(lam)),
                        away_score=int(rng.poisson(mu)),
                        closing_odds={HOME: odds[0], DRAW: odds[1], AWAY: odds[2]},
                    )
                )
    return events


def two_way_league(
    n_teams: int = 10,
    n_seasons: int = 6,
    seed: int = 0,
    market: SyntheticMarket | None = None,
    competition: str = "SYN-2R",
    start: date = date(2015, 10, 1),
    spread: float = 0.8,
    home_advantage: float = 0.2,
) -> list[Event]:
    """Liga de dos resultados: gana el local con probabilidad logistica de la diferencia."""
    market = market or SyntheticMarket()
    rng = np.random.default_rng(seed)
    teams = [f"Equipo {i + 1:02d}" for i in range(n_teams)]
    strength = dict(zip(teams, rng.normal(0.0, spread, n_teams), strict=True))
    flat = [0.55, 0.45]

    events: list[Event] = []
    for s in range(n_seasons):
        season = f"{start.year + s}-{start.year + s + 1}"
        season_start = start + timedelta(days=365 * s)
        # Dos dobles vueltas por temporada: mas partidos, como en baloncesto.
        rounds = _round_robin(teams) * 2
        for r, pairs in enumerate(rounds):
            day = season_start + timedelta(days=3 * r)
            for n, (h, a) in enumerate(pairs):
                p_home = 1.0 / (1.0 + math.exp(-(strength[h] - strength[a] + home_advantage)))
                odds = _market_odds([p_home, 1.0 - p_home], flat, market, rng)
                home_wins = bool(rng.random() < p_home)
                events.append(
                    Event(
                        event_id=f"{competition}-{season}-{r:03d}-{n:02d}",
                        competition=competition,
                        season=season,
                        date=day,
                        home=h,
                        away=a,
                        home_score=1 if home_wins else 0,
                        away_score=0 if home_wins else 1,
                        closing_odds={HOME_AWAY[0]: odds[0], HOME_AWAY[1]: odds[1]},
                    )
                )
    return events

