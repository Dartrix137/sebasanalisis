"""Auto-evaluacion contra una linea base ingenua (§2.7).

Python puro.

Es el control de honestidad del producto, no un adorno: si el motor no supera a
un rival que se limita a repetir la ultima categoria ganadora, la conclusion
honesta —y la que se muestra en la UI— es que esa mesa no exhibe estructura
aprovechable.

Vocabulario: se cuentan COINCIDENCIAS entre la senal emitida y el resultado que
salio despues. No son "aciertos" ni "precision": la senal nunca afirmo que ese
resultado fuera a salir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.engine.probability import GameConfig
from app.engine.ranking import Suggestion, top3


def naive_baseline_choice(
    config: GameConfig, category_id: str, results: Sequence[str]
) -> str | None:
    """El rival tonto: repetir el grupo del ultimo resultado observado.

    Devuelve None si aun no hay giros o si el ultimo no cae en ningun grupo de
    esa categoria (el 0 frente a las docenas).
    """
    category = config.category(category_id)
    if category is None:
        raise KeyError(f"La configuracion no tiene la categoria '{category_id}'")
    if not results:
        return None
    group = category.group_for(results[-1])
    return group.id if group else None


def matches(config: GameConfig, suggestion: Suggestion, outcome: str) -> bool:
    """Si el resultado observado cayo en el grupo que la senal senalaba."""
    category = config.category(suggestion.category_id)
    if category is None:
        return False
    group = category.group(suggestion.group_id)
    return bool(group and outcome in group.outcomes)


@dataclass(frozen=True)
class PerformanceReport:
    total_suggestions: int
    matched_suggestions: int
    match_rate: float
    baseline_suggestions: int
    baseline_matched: int
    baseline_match_rate: float
    verdict: str


VERDICT_NO_DATA = (
    "Todavia no hay giros suficientes para evaluar el desempeno del motor."
)
VERDICT_BELOW = (
    "La tasa de coincidencia del motor en esta muestra no muestra evidencia de "
    "estructura aprovechable en esta mesa. Es una observacion retrospectiva sobre "
    "los giros ya ocurridos y no implica ventaja sobre los proximos: la ventaja de "
    "la casa no cambia."
)
VERDICT_EQUAL = (
    "La tasa de coincidencia del motor en esta muestra no muestra evidencia de "
    "aportar informacion adicional sobre esta mesa. Es una observacion "
    "retrospectiva sobre los giros ya ocurridos y no implica ventaja sobre los "
    "proximos: la ventaja de la casa no cambia."
)
VERDICT_ABOVE = (
    "La tasa de coincidencia del motor en esta muestra es una observacion "
    "retrospectiva sobre los giros ya ocurridos y no implica ventaja sobre los "
    "proximos: la ventaja de la casa no cambia."
)


def evaluate(
    config: GameConfig,
    results: Sequence[str],
    min_history: int = 1,
) -> PerformanceReport:
    """Recorre la secuencia y, en cada giro, compara lo que el motor habria
    senalado con lo que la linea base habria repetido, ambos contra el resultado
    que salio a continuacion.

    Es una re-simulacion sobre el historial: en el paso i solo se usan los giros
    hasta i-1, nunca el resultado que se esta evaluando.
    """
    total = matched = 0
    base_total = base_matched = 0

    for i in range(min_history, len(results)):
        historial = results[:i]
        siguiente = results[i]

        for s in top3(config, historial):
            total += 1
            if matches(config, s, siguiente):
                matched += 1

        for category in config.categories:
            eleccion = naive_baseline_choice(config, category.id, historial)
            if eleccion is None:
                continue
            base_total += 1
            group = category.group(eleccion)
            if group and siguiente in group.outcomes:
                base_matched += 1

    tasa = matched / total if total else 0.0
    tasa_base = base_matched / base_total if base_total else 0.0

    if total == 0 or base_total == 0:
        veredicto = VERDICT_NO_DATA
    elif tasa > tasa_base:
        veredicto = VERDICT_ABOVE
    elif tasa < tasa_base:
        veredicto = VERDICT_BELOW
    else:
        veredicto = VERDICT_EQUAL

    return PerformanceReport(
        total_suggestions=total,
        matched_suggestions=matched,
        match_rate=tasa,
        baseline_suggestions=base_total,
        baseline_matched=base_matched,
        baseline_match_rate=tasa_base,
        verdict=veredicto,
    )
