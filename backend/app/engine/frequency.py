"""Frecuencia observada con shrinkage bayesiano y ponderacion por recencia.

Python puro. Implementa §2.2 y §2.3.

Regla anti-falacia del jugador: cada resultado sale SIEMPRE acompanado de su
probabilidad teorica. Nunca se devuelve una frecuencia observada suelta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.engine.probability import GameConfig, theoretical_probability

# peso(antiguedad) = LAMBDA ** antiguedad, con vida media ~= 22 tiradas (§2.3).
RECENCY_LAMBDA = 0.969


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
