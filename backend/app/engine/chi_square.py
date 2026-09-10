"""Prueba chi-cuadrado: senal de sesgo global de una dimension (§2.4).

Python puro (numpy/scipy son calculo, no infraestructura).

A diferencia del resto del motor, esta senal usa el historial COMPLETO de la
sesion sin decaimiento por recencia: un sesgo fisico real de una mesa necesita
volumen para distinguirse del ruido, y descontar los giros viejos lo escondería.

Cuando la prueba se corre sobre varias categorias a la vez (color, docena,
columna, paridad, alto/bajo), los p-valores se corrigen por comparaciones
multiples antes de decidir si la senal se activa. Ver `all_chi_square_signals`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from scipy import stats

from app.engine.probability import GameConfig, theoretical_probability

#: Minimo duro de giros. No es una sugerencia: por debajo de esto la senal no se
#: activa aunque el p-valor calculado saliera "significativo" (§2.4).
MIN_SPINS = 36

#: Umbral de significancia. Aplicado sobre el p-valor ya corregido cuando hay
#: mas de una prueba en juego, nunca sobre el crudo.
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
    #: p-valor corregido por comparaciones multiples (Benjamini-Hochberg). Es el
    #: que decide `active`; `p_value` queda como el dato crudo de la prueba. Con
    #: una sola prueba en la familia ambos coinciden por definicion.
    p_value_adjusted: float | None
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
            p_value_adjusted=None,
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
            p_value_adjusted=None,
            degrees_of_freedom=None,
            evidence=tuple(evidencia),
        )

    statistic = float(sum((o - e) ** 2 / e for o, e in zip(observados, esperados)))
    df = len(observados) - 1
    p_value = float(stats.chi2.sf(statistic, df))

    # Una prueba aislada es una familia de tamano 1: no hay nada que corregir y
    # el p ajustado coincide con el crudo. La correccion real la aplica
    # `all_chi_square_signals`, que es quien conoce la familia completa.
    activa = p_value < P_VALUE_THRESHOLD
    return ChiSquareResult(
        category_id=category_id,
        active=activa,
        reason=None if activa else f"Desviacion compatible con el azar (p={p_value:.3f})",
        spins_used=n,
        statistic=statistic,
        p_value=p_value,
        p_value_adjusted=p_value,
        degrees_of_freedom=df,
        evidence=tuple(evidencia),
    )


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """p-valores ajustados por FDR (Benjamini-Hochberg), en el orden de entrada.

    q_(i) = min sobre j>=i de (m/j * p_(j)), acotado a 1 y forzado monotono. Un
    q por debajo del umbral equivale exactamente a la regla de rechazo de BH.

    BH controla la tasa de falsos descubrimientos bajo independencia o
    dependencia positiva. Las categorias de la ruleta no son independientes
    —color, paridad y alto/bajo reparten los mismos 37 numeros, y un sesgo real
    hacia una zona de la rueda infla varias a la vez—, pero esa dependencia es
    positiva, que es el caso que BH cubre.
    """
    m = len(p_values)
    if m == 0:
        return []

    ascendente = sorted(range(m), key=lambda i: p_values[i])
    ajustados = [0.0] * m
    minimo = 1.0
    # De mayor a menor p, arrastrando el minimo: eso da el "min sobre j>=i" sin
    # recorrer la cola completa en cada paso, y de paso deja la serie monotona.
    for rango, idx in enumerate(reversed(ascendente), start=1):
        posicion = m - rango + 1
        minimo = min(minimo, m / posicion * p_values[idx])
        ajustados[idx] = minimo
    return ajustados


def _apply_correction(
    result: ChiSquareResult, p_adjusted: float, family_size: int
) -> ChiSquareResult:
    activa = p_adjusted < P_VALUE_THRESHOLD
    if activa:
        motivo = None
    elif result.p_value < P_VALUE_THRESHOLD:
        # Pasaba sola pero no sobrevive a la familia. Hay que decirlo con todas
        # las letras: desde fuera, ver p=0.041 junto a una senal apagada parece
        # un error de calculo y no lo es.
        motivo = (
            f"Desviacion no significativa al corregir por {family_size} pruebas "
            f"simultaneas (p={result.p_value:.3f}, corregido {p_adjusted:.3f})"
        )
    else:
        motivo = f"Desviacion compatible con el azar (p={result.p_value:.3f})"

    return replace(result, active=activa, reason=motivo, p_value_adjusted=p_adjusted)


def all_chi_square_signals(
    config: GameConfig, results: Sequence[str]
) -> dict[str, ChiSquareResult]:
    """La prueba en todas las categorias, corregida por comparaciones multiples.

    Sin correccion cada categoria se contrasta contra el umbral por separado, y
    con cinco categorias la probabilidad de que al menos una salga "significativa"
    por puro azar es 1 - 0.95^5 = 23%, no 5%. Traducido al producto: una de cada
    cuatro sesiones mostraria una senal FUERTE espuria, porque `active` es lo que
    habilita esa etiqueta en `ranking.classify_strength`.
    """
    crudos = {c.id: chi_square_signal(config, c.id, results) for c in config.categories}

    # Solo entran a la familia las categorias que llegaron a calcular un p-valor.
    # Las que se detuvieron por muestra insuficiente no son pruebas: contarlas
    # inflaria m y castigaria a las demas sin haber mirado nada.
    evaluadas = [cid for cid, r in crudos.items() if r.p_value is not None]
    if not evaluadas:
        return crudos

    ajustados = benjamini_hochberg([crudos[cid].p_value for cid in evaluadas])
    corregidos = dict(crudos)
    for cid, q in zip(evaluadas, ajustados):
        corregidos[cid] = _apply_correction(crudos[cid], q, len(evaluadas))
    return corregidos
