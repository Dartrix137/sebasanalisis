"""Prueba chi-cuadrado: senal de sesgo global de una dimension (§2.4).

Python puro (numpy/scipy son calculo, no infraestructura).

A diferencia del resto del motor, esta senal usa el historial COMPLETO de la
sesion sin decaimiento por recencia: un sesgo fisico real de una mesa necesita
volumen para distinguirse del ruido, y descontar los giros viejos lo escondería.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from scipy import stats

from app.engine.probability import GameConfig, theoretical_probability

#: Minimo duro de giros. No es una sugerencia: por debajo de esto la senal no se
#: activa aunque el p-valor calculado saliera "significativo" (§2.4).
MIN_SPINS = 36

#: Umbral de significancia.
P_VALUE_THRESHOLD = 0.05


@dataclass(frozen=True)
class ChiSquareResult:
    category_id: str
    active: bool
    #: Motivo por el que no esta activa, para poder explicarlo en la UI.
    reason: str | None
    spins_used: int
    statistic: float | None
    p_value: float | None
    degrees_of_freedom: int | None
    #: Por grupo: (label, observados, esperados, frecuencia observada, teorica).
    evidence: tuple[str, ...]


def chi_square_signal(
    config: GameConfig, category_id: str, results: Sequence[str]
) -> ChiSquareResult:
    """Contrasta las frecuencias observadas de todos los grupos de una categoria
    contra sus probabilidades teoricas.

    Los resultados que no caen en ningun grupo (el 0 frente a las docenas) se
    agrupan en una celda propia en vez de descartarse: asi los esperados suman el
    total de giros y la prueba es valida. Descartarlos cambiaria la hipotesis que
    se esta probando sin decirlo.
    """
    category = config.category(category_id)
    if category is None:
        raise KeyError(f"La configuracion no tiene la categoria '{category_id}'")

    n = len(results)
    if n < MIN_SPINS:
        return ChiSquareResult(
            category_id=category_id,
            active=False,
            reason=f"Muestra insuficiente: {n} de {MIN_SPINS} giros minimos",
            spins_used=n,
            statistic=None,
            p_value=None,
            degrees_of_freedom=None,
            evidence=(),
        )

    observados: list[float] = []
    esperados: list[float] = []
    evidencia: list[str] = []

    for group in category.groups:
        p = theoretical_probability(config, category_id, group.id)
        obs = sum(1 for r in results if r in group.outcomes)
        observados.append(obs)
        esperados.append(p * n)
        evidencia.append(
            f"{group.label} salio {obs} de {n} ({obs / n:.1%}) vs. {p:.1%} esperado"
        )

    # Celda para lo que no pertenece a ningun grupo, si la categoria deja algo
    # fuera (el cero en docenas, columnas, paridad y alto/bajo).
    cubiertos = category.covered_outcomes
    sin_grupo = sum(1 for r in results if r not in cubiertos)
    p_sin_grupo = 1 - sum(
        theoretical_probability(config, category_id, g.id) for g in category.groups
    )
    if p_sin_grupo > 1e-9:
        observados.append(sin_grupo)
        esperados.append(p_sin_grupo * n)

    if any(e <= 0 for e in esperados):
        return ChiSquareResult(
            category_id=category_id,
            active=False,
            reason="Alguna categoria tiene frecuencia esperada cero",
            spins_used=n,
            statistic=None,
            p_value=None,
            degrees_of_freedom=None,
            evidence=tuple(evidencia),
        )

    statistic = float(sum((o - e) ** 2 / e for o, e in zip(observados, esperados)))
    df = len(observados) - 1
    p_value = float(stats.chi2.sf(statistic, df))

    activa = p_value < P_VALUE_THRESHOLD
    return ChiSquareResult(
        category_id=category_id,
        active=activa,
        reason=None if activa else f"Desviacion compatible con el azar (p={p_value:.3f})",
        spins_used=n,
        statistic=statistic,
        p_value=p_value,
        degrees_of_freedom=df,
        evidence=tuple(evidencia),
    )


def all_chi_square_signals(
    config: GameConfig, results: Sequence[str]
) -> dict[str, ChiSquareResult]:
    return {c.id: chi_square_signal(config, c.id, results) for c in config.categories}
