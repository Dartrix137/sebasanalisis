"""Probabilidad implicita de una cuota y como quitarle el margen de la casa.

Una cuota decimal `o` paga `o` por unidad apostada (la unidad incluida), asi que
su probabilidad implicita es `1/o`. En un mercado de la casa esas probabilidades
suman mas de 1: el exceso es el margen. Para comparar el mercado con una
estimacion propia hay que quitarselo primero (§8.4 n.º 4).

Dos metodos, porque se elige en validacion el que mejor describe el cierre
(§8.5, punto 3):

- **Proporcional**: divide cada probabilidad implicita por la suma. Reparte el
  margen en proporcion a cada probabilidad.
- **Shin** (Shin, 1993, "Measuring the incidence of insider trading in a market
  for state-contingent claims"): supone una fraccion `z` de apostadores
  informados y carga mas margen sobre los resultados poco probables, que es lo
  que se observa en las casas (el sesgo favorito/no favorito). La probabilidad
  de cada resultado es

      p_i = (sqrt(z^2 + 4 (1 - z) pi_i^2 / S) - z) / (2 (1 - z))

  con `pi_i = 1/o_i` y `S = sum(pi_i)`, y `z` es el unico valor en [0, 1) que
  hace que las `p_i` sumen 1. Se resuelve por biseccion: la suma decrece con
  `z`; en z=0 vale `sqrt(S)`, que es > 1 cuando hay margen, y cuando z tiende
  a 1 tiende a `sum(pi_i^2) / S`, que es < 1.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import Enum


class MarginMethod(str, Enum):
    proportional = "proportional"
    shin = "shin"


def validate_odds(odds: Sequence[float]) -> None:
    """Una cuota decimal valida es finita y mayor que 1; un mercado tiene >= 2."""
    if len(odds) < 2:
        raise ValueError("un mercado necesita al menos dos resultados")
    for o in odds:
        if not math.isfinite(o) or o <= 1.0:
            raise ValueError(f"cuota decimal invalida: {o!r} (tiene que ser > 1)")


def implied(odds: Sequence[float]) -> list[float]:
    """Probabilidad implicita de cada cuota, con el margen incluido."""
    validate_odds(odds)
    return [1.0 / o for o in odds]


def overround(odds: Sequence[float]) -> float:
    """Margen de la casa: cuanto suman las probabilidades implicitas por encima de 1."""
    return sum(implied(odds)) - 1.0


def remove_margin_proportional(odds: Sequence[float]) -> list[float]:
    pis = implied(odds)
    total = sum(pis)
    return [p / total for p in pis]


def _shin_probs(pis: Sequence[float], total: float, z: float) -> list[float]:
    return [
        (math.sqrt(z * z + 4.0 * (1.0 - z) * p * p / total) - z) / (2.0 * (1.0 - z))
        for p in pis
    ]


def shin_z(odds: Sequence[float], tol: float = 1e-12) -> float:
    """La fraccion `z` de Shin para este mercado. 0 si no hay margen."""
    pis = implied(odds)
    total = sum(pis)
    if total <= 1.0:
        # Sin margen (o con uno negativo, un mercado cruzado): no hay nada que
        # repartir con Shin. El proporcional normaliza igual.
        return 0.0
    lo, hi = 0.0, 1.0 - 1e-12
    # La suma de las p_i decrece con z: en z=0 vale sqrt(S) > 1.
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if sum(_shin_probs(pis, total, mid)) > 1.0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def remove_margin_shin(odds: Sequence[float]) -> list[float]:
    pis = implied(odds)
    total = sum(pis)
    if total <= 1.0:
        return [p / total for p in pis]
    probs = _shin_probs(pis, total, shin_z(odds))
    # La biseccion deja la suma a 1e-12 de 1; se normaliza para que sea exacta.
    s = sum(probs)
    return [p / s for p in probs]


def remove_margin(odds: Sequence[float], method: MarginMethod) -> list[float]:
    """Probabilidades sin margen, en el mismo orden que las cuotas."""
    if method is MarginMethod.proportional:
        return remove_margin_proportional(odds)
    return remove_margin_shin(odds)
