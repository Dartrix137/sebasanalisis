"""Frecuencia observada con shrinkage bayesiano y ponderacion por recencia.

Python puro. Implementa §2.2 y §2.3.

Regla anti-falacia del jugador: cada resultado sale SIEMPRE acompanado de su
probabilidad teorica. Nunca se devuelve una frecuencia observada suelta.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

from scipy import stats

from app.engine.probability import GameConfig, theoretical_probability

# peso(antiguedad) = LAMBDA ** antiguedad, con vida media ~= 22 tiradas (§2.3).
RECENCY_LAMBDA = 0.969

#: Nivel de confianza del intervalo que acompana a cada frecuencia observada.
CONFIDENCE_LEVEL = 0.95


@lru_cache(maxsize=8)
def _two_sided_z(confidence: float) -> float:
    # `norm.ppf` cuesta ~0.1 ms por llamada y el valor solo depende de la
    # confianza; sin cache era el 75% del tiempo de la auto-evaluacion.
    return float(stats.norm.ppf(1 - (1 - confidence) / 2))


def wilson_interval(
    favorable: int, total: int, confidence: float = CONFIDENCE_LEVEL
) -> tuple[float, float]:
    """Intervalo de Wilson para una proporcion observada.

    Responde "que tanto puede moverse esto por puro azar con esta cantidad de
    giros", que es justo lo que falta al mostrar una frecuencia sola: 6 de 10 y
    600 de 1000 son ambos 60% y no dicen ni remotamente lo mismo. Sin el
    intervalo, una desviacion de ruido y una respaldada por volumen se ven igual.

    Se usa Wilson y no la aproximacion normal (p +- z*raiz(p(1-p)/n)) porque esa
    se rompe justo donde mas hace falta: con pocos giros devuelve limites fuera
    de [0,1], y cuando un grupo no salio ninguna vez colapsa a un intervalo de
    ancho cero, afirmando certeza absoluta a partir de nada.

    Va sobre los conteos SIN ponderar por recencia: Wilson supone un conteo
    binomial y la estimacion con shrinkage y decaimiento no lo es. El intervalo
    describe lo que sostienen los datos crudos; la estimacion con shrinkage se
    muestra a su lado, no dentro.
    """
    if favorable < 0 or total < 0:
        raise ValueError("Los conteos no pueden ser negativos")
    if favorable > total:
        raise ValueError("Los favorables no pueden superar el total")
    if not 0 < confidence < 1:
        raise ValueError("La confianza tiene que estar entre 0 y 1")
    # Sin giros no se sabe nada, y el intervalo honesto es "cualquier valor".
    if total == 0:
        return (0.0, 1.0)

    z = _two_sided_z(confidence)
    p = favorable / total
    denominador = 1 + z**2 / total
    centro = (p + z**2 / (2 * total)) / denominador
    margen = (
        z / denominador * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2))
    )
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def recency_weights(n_results: int, lambda_: float = RECENCY_LAMBDA) -> list[float]:
    """Peso de cada observacion, para una lista en orden cronologico ascendente.

    El ultimo elemento es el mas reciente y pesa 1.0; hacia atras el peso decae
    exponencialmente. Se prefiere esto a una ventana fija porque evita el efecto
    escalon de que un giro pase de contar entero a no contar nada (§2.3).
    """
    if n_results < 0:
        raise ValueError("n_results no puede ser negativo")
    return [lambda_ ** (n_results - 1 - i) for i in range(n_results)]


def shrinkage_estimate(
    favorable: float, total: float, p_teorica: float, alpha: float
) -> float:
    """p_estimada = (favorables + alpha x p_teorica) / (total + alpha)  (§2.2).

    Con pocos datos el resultado se queda cerca de la probabilidad teorica, que
    es la lectura prudente: 3 de 4 no es "75% de probabilidad".
    """
    if alpha < 0:
        raise ValueError("alpha no puede ser negativo")
    if total < 0 or favorable < 0:
        raise ValueError("Los conteos no pueden ser negativos")
    denominador = total + alpha
    if denominador == 0:
        return p_teorica
    return (favorable + alpha * p_teorica) / denominador


@dataclass(frozen=True)
class GroupFrequency:
    """Frecuencia de un grupo. Los dos primeros campos viajan siempre juntos."""

    category_id: str
    group_id: str
    group_label: str
    theoretical_probability: float
    observed_frequency_shrunk: float
    #: Frecuencia cruda ponderada, solo para construir la evidencia mostrada.
    #: Nunca se usa como estimacion: para eso esta el valor con shrinkage.
    raw_weighted_frequency: float
    deviation: float
    weighted_favorable: float
    weighted_total: float
    payout: float
    #: Conteos sin ponderar, para textos del tipo "salio 15 de 40".
    raw_count: int
    raw_total: int
    #: Intervalo de Wilson sobre los conteos crudos. Es el contexto que vuelve
    #: legible la desviacion: si la probabilidad teorica cae dentro, lo observado
    #: no se distingue del azar con esta cantidad de giros.
    observed_ci_low: float
    observed_ci_high: float


def category_frequencies(
    config: GameConfig,
    category_id: str,
    results: Sequence[str],
    lambda_: float = RECENCY_LAMBDA,
) -> list[GroupFrequency]:
    """Frecuencia con shrinkage y recencia de cada grupo de una categoria.

    `results` va en orden cronologico ascendente (mas antiguo primero), igual que
    `spin_index`.

    El denominador son TODOS los giros, no solo los que caen en algun grupo. Es
    lo que mantiene la comparacion honesta: la probabilidad teorica de una docena
    es 12/37 contando el 0, asi que la frecuencia observada tambien tiene que
    contarlo. Excluirlo inflaria toda docena por encima de su teorica.
    """
    category = config.category(category_id)
    if category is None:
        raise KeyError(f"La configuracion no tiene la categoria '{category_id}'")

    pesos = recency_weights(len(results), lambda_)
    peso_total = sum(pesos)

    salidas: list[GroupFrequency] = []
    for group in category.groups:
        p_teorica = theoretical_probability(config, category_id, group.id)
        favorable = sum(w for r, w in zip(results, pesos) if r in group.outcomes)
        crudo = sum(1 for r in results if r in group.outcomes)
        p_shrunk = shrinkage_estimate(
            favorable=favorable,
            total=peso_total,
            p_teorica=p_teorica,
            alpha=category.shrinkage_alpha,
        )
        ci_low, ci_high = wilson_interval(crudo, len(results))
        salidas.append(
            GroupFrequency(
                category_id=category_id,
                group_id=group.id,
                group_label=group.label,
                theoretical_probability=p_teorica,
                observed_frequency_shrunk=p_shrunk,
                raw_weighted_frequency=(favorable / peso_total) if peso_total else 0.0,
                deviation=p_shrunk - p_teorica,
                weighted_favorable=favorable,
                weighted_total=peso_total,
                payout=group.payout,
                raw_count=crudo,
                raw_total=len(results),
                observed_ci_low=ci_low,
                observed_ci_high=ci_high,
            )
        )
    return salidas


def all_frequencies(
    config: GameConfig, results: Sequence[str], lambda_: float = RECENCY_LAMBDA
) -> dict[str, list[GroupFrequency]]:
    """Frecuencias de todas las categorias, indexadas por `category_id`."""
    return {
        c.id: category_frequencies(config, c.id, results, lambda_) for c in config.categories
    }
