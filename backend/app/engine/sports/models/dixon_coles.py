"""Futbol, resultado final (1X2): Dixon-Coles con decaimiento temporal.

Dixon y Coles (1997), "Modelling association football scores and inefficiencies
in the football betting market", Applied Statistics 46(2). Los goles de cada
lado son Poisson:

    lambda = exp(gamma + attack[local] - defence[visitante])   (goles del local)
    mu     = exp(attack[visitante] - defence[local])           (goles del visitante)

con `gamma` la ventaja de jugar en casa, y una correccion `tau` para los cuatro
marcadores bajos, donde la Poisson independiente se equivoca:

    tau(0,0) = 1 - lambda mu rho     tau(0,1) = 1 + lambda rho
    tau(1,0) = 1 + mu rho            tau(1,1) = 1 - rho
    tau = 1 en el resto

Cada partido pesa `exp(-xi * dias)` segun su antiguedad (§4.5 del articulo):
`xi` se elige en validacion. Una penalizacion `ridge` pequena sobre ataque y
defensa los deja identificados (sin ella, sumar una constante a todos los
ataques y a todas las defensas no cambia nada) y frena a los equipos con pocos
partidos.

Se ajusta por maxima verosimilitud con L-BFGS-B y el gradiente analitico. Las
probabilidades 1X2 salen de sumar la matriz de marcadores hasta `max_goals`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.stats import poisson

from app.engine.sports.events import AWAY, DRAW, HOME, HOME_DRAW_AWAY, Event
from app.engine.sports.models import history_before

FloatArray = NDArray[np.float64]

#: Cota de rho. Con lambda y mu de un partido normal (< 4 goles esperados) deja
#: tau positivo; si aun asi un cruce lo vuelve negativo, se recorta a TAU_FLOOR.
RHO_BOUND = 0.2
TAU_FLOOR = 1e-10


@dataclass(frozen=True)
class FittedDixonColes:
    teams: tuple[str, ...]
    attack: tuple[float, ...]
    defence: tuple[float, ...]
    home_advantage: float
    rho: float
    #: Equipos con al menos `min_matches` en la ventana: los unicos que se estiman.
    known: frozenset[str]
    max_goals: int

    def expected_goals(self, home: str, away: str) -> tuple[float, float] | None:
        if home not in self.known or away not in self.known:
            return None
        i = self.teams.index(home)
        j = self.teams.index(away)
        lam = float(np.exp(self.home_advantage + self.attack[i] - self.defence[j]))
        mu = float(np.exp(self.attack[j] - self.defence[i]))
        return lam, mu

    def score_matrix(self, home: str, away: str) -> FloatArray | None:
        goals = self.expected_goals(home, away)
        if goals is None:
            return None
        lam, mu = goals
        k = np.arange(self.max_goals + 1)
        matrix: FloatArray = np.outer(poisson.pmf(k, lam), poisson.pmf(k, mu))
        matrix[0, 0] *= max(1.0 - lam * mu * self.rho, TAU_FLOOR)
        matrix[0, 1] *= max(1.0 + lam * self.rho, TAU_FLOOR)
        matrix[1, 0] *= max(1.0 + mu * self.rho, TAU_FLOOR)
        matrix[1, 1] *= max(1.0 - self.rho, TAU_FLOOR)
        return matrix

    def estimate(self, home: str, away: str) -> dict[str, float] | None:
        matrix = self.score_matrix(home, away)
        if matrix is None:
            return None
        # La masa que queda fuera de max_goals es despreciable; se normaliza
        # para que las tres sumen 1 exacto.
        p_home = float(np.tril(matrix, -1).sum())
        p_draw = float(np.trace(matrix))
        p_away = float(np.triu(matrix, 1).sum())
        total = p_home + p_draw + p_away
        return {HOME: p_home / total, DRAW: p_draw / total, AWAY: p_away / total}


@dataclass(frozen=True)
class DixonColes:
    #: Decaimiento por dia. 0 = todos los partidos de la ventana pesan igual.
    xi: float = 0.002
    #: Solo entran los partidos de los ultimos `window_days` dias.
    window_days: int = 3 * 365
    #: Partidos minimos de un equipo en la ventana para estimarlo.
    min_matches: int = 6
    max_goals: int = 10
    ridge: float = 1e-3

    @property
    def name(self) -> str:
        return "dixon_coles"

    @property
    def outcomes(self) -> tuple[str, ...]:
        return HOME_DRAW_AWAY

    def fit(self, history: Sequence[Event], as_of: date) -> FittedDixonColes:
        past = [e for e in history_before(history, as_of) if (as_of - e.date).days <= self.window_days]
        teams = tuple(sorted({e.home for e in past} | {e.away for e in past}))
        counts: Counter[str] = Counter()
        for e in past:
            counts[e.home] += 1
            counts[e.away] += 1
        known = frozenset(t for t in teams if counts[t] >= self.min_matches)
        if not past:
            return FittedDixonColes((), (), (), 0.0, 0.0, frozenset(), self.max_goals)

        index = {t: n for n, t in enumerate(teams)}
        h = np.array([index[e.home] for e in past])
        a = np.array([index[e.away] for e in past])
        x = np.array([e.home_score for e in past], dtype=float)
        y = np.array([e.away_score for e in past], dtype=float)
        age = np.array([(as_of - e.date).days for e in past], dtype=float)
        w = np.exp(-self.xi * age)
        params = _fit_params(h, a, x, y, w, len(teams), self.ridge)
        n = len(teams)
        return FittedDixonColes(
            teams=teams,
            attack=tuple(float(v) for v in params[:n]),
            defence=tuple(float(v) for v in params[n : 2 * n]),
            home_advantage=float(params[2 * n]),
            rho=float(params[2 * n + 1]),
            known=known,
            max_goals=self.max_goals,
        )


def negative_log_likelihood(
    params: FloatArray,
    h: NDArray[Any],
    a: NDArray[Any],
    x: FloatArray,
    y: FloatArray,
    w: FloatArray,
    n_teams: int,
    ridge: float,
) -> tuple[float, FloatArray]:
    """Menos la log-verosimilitud ponderada (sin los factoriales, constantes) y su gradiente."""
    n = n_teams
    attack = params[:n]
    defence = params[n : 2 * n]
    gamma = params[2 * n]
    rho = params[2 * n + 1]

    log_lam = gamma + attack[h] - defence[a]
    log_mu = attack[a] - defence[h]
    lam = np.exp(log_lam)
    mu = np.exp(log_mu)

    tau = np.ones_like(lam)
    dtau_dlam = np.zeros_like(lam)
    dtau_dmu = np.zeros_like(lam)
    dtau_drho = np.zeros_like(lam)

    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)
    tau[m00] = 1.0 - lam[m00] * mu[m00] * rho
    dtau_dlam[m00] = -mu[m00] * rho
    dtau_dmu[m00] = -lam[m00] * rho
    dtau_drho[m00] = -lam[m00] * mu[m00]
    tau[m01] = 1.0 + lam[m01] * rho
    dtau_dlam[m01] = rho
    dtau_drho[m01] = lam[m01]
    tau[m10] = 1.0 + mu[m10] * rho
    dtau_dmu[m10] = rho
    dtau_drho[m10] = mu[m10]
    tau[m11] = 1.0 - rho
    dtau_drho[m11] = -1.0
    tau = np.maximum(tau, TAU_FLOOR)

    ll = np.log(tau) + x * log_lam - lam + y * log_mu - mu
    value = -float(np.dot(w, ll)) + ridge * float(np.dot(attack, attack) + np.dot(defence, defence))

    # Derivadas de cada partido respecto de log(lambda), log(mu) y rho.
    g_lam = w * (x - lam + lam * dtau_dlam / tau)
    g_mu = w * (y - mu + mu * dtau_dmu / tau)
    g_rho = float(np.dot(w, dtau_drho / tau))

    grad_attack = np.bincount(h, weights=g_lam, minlength=n) + np.bincount(a, weights=g_mu, minlength=n)
    grad_defence = -np.bincount(a, weights=g_lam, minlength=n) - np.bincount(h, weights=g_mu, minlength=n)
    grad = np.concatenate([grad_attack, grad_defence, [g_lam.sum(), g_rho]])
    grad = -grad
    grad[:n] += 2.0 * ridge * attack
    grad[n : 2 * n] += 2.0 * ridge * defence
    return value, grad


def _fit_params(
    h: NDArray[Any],
    a: NDArray[Any],
    x: FloatArray,
    y: FloatArray,
    w: FloatArray,
    n_teams: int,
    ridge: float,
) -> FloatArray:
    start = np.zeros(2 * n_teams + 2)
    start[2 * n_teams] = 0.25  # ventaja de local de partida, en escala log
    bounds = [(None, None)] * (2 * n_teams + 1) + [(-RHO_BOUND, RHO_BOUND)]
    result = minimize(
        negative_log_likelihood,
        start,
        args=(h, a, x, y, w, n_teams, ridge),
        jac=True,
        method="L-BFGS-B",
        bounds=bounds,
    )
    params: FloatArray = np.asarray(result.x, dtype=np.float64)
    return params
