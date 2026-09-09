"""Racha activa y su cola binomial (§2.5).

Python puro.

Esta senal es la que mas facilmente se malinterpreta, asi que el resultado
incluye siempre la probabilidad del proximo giro, que NO cambia por la racha.
Que el rojo haya salido seis veces seguidas no altera en nada el septimo giro.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.engine.probability import GameConfig, theoretical_probability


def streak_probability(n: int, p_teorica: float) -> float:
    """P(racha de n) = p_teorica ** n.

    Es la probabilidad de que la racha ocurriera de antemano, no la de que
    continue: esa sigue siendo `p_teorica` en cada giro.
    """
    if n < 0:
        raise ValueError("n no puede ser negativo")
    if not 0 <= p_teorica <= 1:
        raise ValueError("p_teorica debe estar entre 0 y 1")
    return p_teorica**n


@dataclass(frozen=True)
class StreakResult:
    category_id: str
    group_id: str
    group_label: str
    consecutive_count: int
    #: Probabilidad de que se diera una racha asi de larga.
    probability_of_streak: float
    #: Probabilidad del PROXIMO giro. Igual a la teorica, siempre.
    theoretical_probability_next: float


def active_streak(
    config: GameConfig, category_id: str, results: Sequence[str]
) -> StreakResult | None:
    """Cuenta cuantas veces seguidas se repitio el mismo grupo al final de la
    secuencia.

    Un resultado que no pertenece a ningun grupo corta la racha: si sale el 0, la
    racha de "par" se termina, porque el 0 no es par.
    """
    category = config.category(category_id)
    if category is None:
        raise KeyError(f"La configuracion no tiene la categoria '{category_id}'")
    if not results:
        return None

    ultimo = category.group_for(results[-1])
    if ultimo is None:
        return None

    cuenta = 0
    for r in reversed(results):
        if r in ultimo.outcomes:
            cuenta += 1
        else:
            break

    p_teorica = theoretical_probability(config, category_id, ultimo.id)
    return StreakResult(
        category_id=category_id,
        group_id=ultimo.id,
        group_label=ultimo.label,
        consecutive_count=cuenta,
        probability_of_streak=streak_probability(cuenta, p_teorica),
        theoretical_probability_next=p_teorica,
    )


def longest_active_streak(
    config: GameConfig, results: Sequence[str], min_length: int = 2
) -> StreakResult | None:
    """La racha activa mas larga entre todas las categorias, si alcanza el minimo."""
    rachas = [
        s
        for c in config.categories
        if (s := active_streak(config, c.id, results)) is not None
        and s.consecutive_count >= min_length
    ]
    if not rachas:
        return None
    return max(rachas, key=lambda s: s.consecutive_count)
