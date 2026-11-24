"""Recomendacion de un partido: "Apostar: ..." o "No apostar este partido" (§8.4 n.º 4).

Para cada resultado se compara la cuota con la estimacion propia:

    edge = p_modelo * cuota - 1

es lo que paga la cuota por encima de lo que justifica la estimacion, por unidad
apostada. Se recomienda el resultado de mayor `edge` solo si llega a
`min_edge`; si ninguno llega, NO_BET. Como en la ruleta, **una sola
recomendacion** por partido, y la mejor candidata viaja siempre, tambien con
NO_BET, para que el backtest compare cuando el motor hablo con cuando callo.

Desempate determinista: mayor `edge`, despues mayor probabilidad estimada (el
resultado menos arriesgado), despues el orden de los resultados del deporte.

Cada candidata trae juntas la estimacion propia y la probabilidad implicita sin
margen, nunca una sola: es la misma regla de la pareja que la ruleta aplica a
la probabilidad teorica y la frecuencia observada.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.engine.recommendation import Decision
from app.engine.sports.odds import MarginMethod, overround, remove_margin


@dataclass(frozen=True)
class Policy:
    """Lo que se congela en validacion y se usa tal cual en prueba (§8.5)."""

    min_edge: float
    margin_method: MarginMethod
    #: Cuota maxima que se recomienda; None = sin tope.
    max_odds: float | None = None


@dataclass(frozen=True)
class Candidate:
    outcome: str
    odds: float
    #: Estimacion estadistica propia, a partir de resultados anteriores.
    model_probability: float
    #: Probabilidad implicita en la cuota, sin el margen de la casa.
    market_probability: float
    #: Lo que paga la cuota por encima de la estimacion, por unidad apostada.
    edge: float


@dataclass(frozen=True)
class SportsRecommendation:
    decision: Decision
    #: La mejor candidata; existe siempre, tambien con NO_BET.
    best: Candidate
    candidates: tuple[Candidate, ...]
    overround: float

    @property
    def outcome(self) -> str | None:
        """El resultado recomendado; None con NO_BET."""
        return self.best.outcome if self.decision is Decision.recommend else None


def recommend(
    model_probs: Mapping[str, float],
    odds: Mapping[str, float],
    outcomes: Sequence[str],
    policy: Policy,
) -> SportsRecommendation:
    if set(model_probs) != set(outcomes) or set(odds) != set(outcomes):
        raise ValueError("la estimacion y las cuotas tienen que cubrir los mismos resultados")
    total = sum(model_probs.values())
    if not math.isclose(total, 1.0, abs_tol=1e-6):
        raise ValueError(f"la estimacion tiene que sumar 1 (suma {total})")

    odds_vec = [float(odds[o]) for o in outcomes]
    market = remove_margin(odds_vec, policy.margin_method)
    candidates = tuple(
        Candidate(
            outcome=o,
            odds=odds_vec[i],
            model_probability=float(model_probs[o]),
            market_probability=market[i],
            edge=float(model_probs[o]) * odds_vec[i] - 1.0,
        )
        for i, o in enumerate(outcomes)
    )
    order = {o: i for i, o in enumerate(outcomes)}
    ranked = sorted(candidates, key=lambda c: (-c.edge, -c.model_probability, order[c.outcome]))

    eligible = [
        c
        for c in ranked
        if c.edge >= policy.min_edge and (policy.max_odds is None or c.odds <= policy.max_odds)
    ]
    if eligible:
        return SportsRecommendation(Decision.recommend, eligible[0], candidates, overround(odds_vec))
    return SportsRecommendation(Decision.no_bet, ranked[0], candidates, overround(odds_vec))
