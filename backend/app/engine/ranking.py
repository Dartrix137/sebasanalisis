"""Puntaje de significancia, ranking top-3 y fuerza de la senal (§2.6).

Python puro.

Nada de lo que sale de aqui anticipa el resultado de un giro. Describe cuanto se
desvio la muestra ya ocurrida y con cuanto respaldo, nada mas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from app.engine.chi_square import ChiSquareResult, all_chi_square_signals
from app.engine.frequency import RECENCY_LAMBDA, GroupFrequency, all_frequencies
from app.engine.probability import GameConfig, expected_value


class SignalStrength(str, Enum):
    """Fuerza de la senal: describe la evidencia pasada, no una certeza futura."""

    strong = "strong"
    medium = "medium"
    weak = "weak"


#: Umbrales de EV de §2.6.
EV_STRONG = 0.15
EV_MEDIUM = 0.06

TOP_N = 3


@dataclass(frozen=True)
class Suggestion:
    category_id: str
    group_id: str
    group_label: str
    #: Los dos viajan juntos siempre (regla anti-falacia del jugador, §2).
    theoretical_probability: float
    observed_frequency_shrunk: float
    deviation: float
    significance_score: float
    strength: SignalStrength
    #: EV calculado con la frecuencia observada: es una lectura sobre esta
    #: muestra, no una garantia. Con la probabilidad teorica el EV seria
    #: exactamente menos la ventaja de la casa.
    ev: float
    #: EV con la probabilidad teorica, para mostrar al lado del anterior.
    ev_theoretical: float
    chi_square_pvalue: float | None
    payout: float
    raw_count: int
    raw_total: int
    is_top3: bool


def significance_score(frequency: GroupFrequency) -> float:
    """|p_estimada - p_teorica| x sqrt(giros ponderados)  (§2.6).

    La raiz del volumen es lo que evita que una desviacion enorme sobre cuatro
    giros pese lo mismo que una desviacion moderada sobre cien.
    """
    return abs(frequency.deviation) * math.sqrt(max(frequency.weighted_total, 0.0))


def classify_strength(ev: float, chi: ChiSquareResult | None) -> SignalStrength:
    """FUERTE exige EV alto Y respaldo de chi-cuadrado significativo (§2.6).

    Interpretacion conservadora de "si aplica a esa dimension": cuando la prueba
    no esta activa —porque faltan giros o porque la desviacion es compatible con
    el azar— la senal no llega a FUERTE. Un EV alto sobre diez giros es ruido, y
    llamarlo fuerte seria exactamente la sobre-promesa que el producto no hace.
    """
    if ev >= EV_STRONG and chi is not None and chi.active:
        return SignalStrength.strong
    if ev >= EV_MEDIUM:
        return SignalStrength.medium
    return SignalStrength.weak


def rank_suggestions(
    config: GameConfig,
    results: Sequence[str],
    lambda_: float = RECENCY_LAMBDA,
) -> list[Suggestion]:
    """Todas las senales, ordenadas por significancia, con las 3 primeras
    marcadas `is_top3`.

    Se devuelven TODAS, no solo las tres: §2.6 exige que las senales debiles se
    muestren etiquetadas como debiles, nunca ocultarlas ni disfrazarlas.
    """
    frecuencias = all_frequencies(config, results, lambda_)
    chis = all_chi_square_signals(config, results)

    sugerencias: list[Suggestion] = []
    for category_id, grupos in frecuencias.items():
        chi = chis.get(category_id)
        for f in grupos:
            ev = expected_value(f.observed_frequency_shrunk, f.payout)
            sugerencias.append(
                Suggestion(
                    category_id=category_id,
                    group_id=f.group_id,
                    group_label=f.group_label,
                    theoretical_probability=f.theoretical_probability,
                    observed_frequency_shrunk=f.observed_frequency_shrunk,
                    deviation=f.deviation,
                    significance_score=significance_score(f),
                    strength=classify_strength(ev, chi),
                    ev=ev,
                    ev_theoretical=expected_value(f.theoretical_probability, f.payout),
                    chi_square_pvalue=chi.p_value if chi and chi.active else None,
                    payout=f.payout,
                    raw_count=f.raw_count,
                    raw_total=f.raw_total,
                    is_top3=False,
                )
            )

    # Desempate estable por id, para que dos corridas con los mismos datos den
    # exactamente el mismo orden.
    sugerencias.sort(key=lambda s: (-s.significance_score, s.category_id, s.group_id))
    return [
        Suggestion(**{**s.__dict__, "is_top3": i < TOP_N}) for i, s in enumerate(sugerencias)
    ]


def top3(config: GameConfig, results: Sequence[str], lambda_: float = RECENCY_LAMBDA) -> list[Suggestion]:
    return [s for s in rank_suggestions(config, results, lambda_) if s.is_top3]
