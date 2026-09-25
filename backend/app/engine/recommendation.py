"""Motor de recomendacion: que mercado sugerir para el giro siguiente (§2.10).

Python puro: sin FastAPI, sin SQLAlchemy, sin red.

Que hace y que no
-----------------
Recorre el catalogo de mercados de la variante, le pone a cada uno un
`signal_score` de 0 a 100 y devuelve UNA sola recomendacion, o `NO_BET` si
ninguna alternativa alcanza el umbral. Hay cuatro salidas y nada mas: SEÑAL
FUERTE (desde el umbral alto), SEÑAL MEDIA (del umbral medio al alto), SEÑAL
DEBIL (del umbral debil al medio: solo apuesta base) y SIN SEÑAL (por debajo
del debil, no apostar). Solo se evalua la mejor alternativa: una
segunda que tambien pase el umbral no se ofrece como otra apuesta. El score mide **cuanto se separo la
muestra ya ocurrida de lo que la mesa da de por si**, no la probabilidad de
acertar el proximo giro: esa sigue siendo la teorica, y no la cambia nada de lo
que se calcule aqui.

Generico igual que el resto de `engine/`: los mercados salen de
`game_variants.categories_json` (grupos con `market != false` mas
`allowed_combinations`). El motor nunca sabe que "docena" es cosa de ruleta.

Direccion de la señal
---------------------
Un mercado juega a favor cuando su frecuencia observada con shrinkage quedo
POR ENCIMA de su teorica. Es la misma direccion que ya usaba el ranking top-3:
alli la lleva el EV (`expected_value(observed_frequency_shrunk, payout)`), que
es monotona creciente en la frecuencia observada, asi que solo un grupo que
salio mas de lo esperado podia alcanzar MEDIA o FUERTE. Aqui se hace explicita
con el signo de `z`, en vez de quedar implicita en el EV.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from statistics import fmean
from typing import Sequence

from app.engine.chi_square import ChiSquareResult, all_chi_square_signals
from app.engine.frequency import (
    RECENCY_LAMBDA,
    recency_weights,
    shrinkage_estimate,
    wilson_interval,
)
from app.engine.probability import GameConfig

# --------------------------------------------------------------------------
# Constantes de calibracion
# --------------------------------------------------------------------------

#: Ventanas evaluadas, de la mas corta a la mas larga. Si la sesion tiene menos
#: giros que la ventana mas corta, se usa el historial entero como unica ventana.
WINDOWS: tuple[int, ...] = (10, 20, 50, 100)

#: Desviacion estandarizada que satura un componente del score.
#:
#: NO es un umbral de significancia. Un z de 2 sobre UNA prueba aislada seria el
#: clasico "dos sigmas", pero aqui se evalua sobre ~18 mercados solapados a la
#: vez y sin corregir por comparaciones multiples, asi que llegar a 2 no dice
#: que la desviacion se distinga del azar. Es la escala con la que el producto
#: decide cada cuanto habla, y junto con los pesos, cuantas de esas veces la
#: señal llega a FUERTE.
#:
#: Recalibrado el 2026-09-24 (antes: Z_MAX 2.0 y pesos 0.45/0.25/0.30). Con la
#: calibracion anterior el motor recomendaba en ~35% de los giros, pero solo ~5%
#: de esas recomendaciones llegaba a 80: la consistencia, que es un cociente y no
#: una magnitud, regalaba sus 30 puntos a cualquier inclinacion pareja por chica
#: que fuera, y apelotonaba los scores entre 60 y 79. Bajarle el peso y acortar
#: Z_MAX mantiene la frecuencia con la que el motor habla y abre el rango de
#: arriba. Medido sobre ruedas europeas justas con semillas distintas a la del
#: backtest (200 sesiones x 150 giros para calibrar; otras 200 y 40 de 400
#: giros, estas con chi-cuadrado activo, para validar): con umbral 60 el motor
#: recomienda en ~32-36% de los giros y ~18% de las recomendaciones son FUERTE
#: (~1 de cada 16 giros); con el umbral por defecto de 50, en ~58-60% y ~11%.
#: Las FUERTE son las mismas: el umbral alto no depende del minimo. La tasa de coincidencia y el ROI no mejoran con ninguna
#: calibracion — se quedan en la ventaja de la casa, que es lo esperado y lo que
#: el backtest de `scripts/` confirma. FUERTE dice que la muestra se separo mas,
#: no que se acierte mas.
Z_MAX = 1.6

#: Pesos de los tres componentes. Suman 1.0.
WEIGHT_DEVIATION = 0.58
WEIGHT_RECENCY = 0.32
WEIGHT_CONSISTENCY = 0.10

#: Puntos que suma el respaldo del chi-cuadrado, solo si la prueba esta activa
#: para la categoria del mercado: >=200 giros y p corregido por
#: Benjamini-Hochberg < 0.05 (§2.4). Es un bono, no un requisito.
CHI_SQUARE_BONUS = 10.0

#: Umbral alto (§2.10): piso inclusivo de SEÑAL FUERTE. Los otros dos salen de
#: la variante: `recommendation_threshold` es el piso de SEÑAL MEDIA y
#: `weak_threshold` el de SEÑAL DEBIL, que es el minimo para recomendar algo.
STRONG_THRESHOLD = 80.0


#: Por debajo de estos giros no hay recomendacion, llegue o no el score al
#: umbral, y el NO_BET se explica como falta de informacion: es la ventana mas
#: corta, y sin ella completa ni siquiera hay dos tramos para medir la
#: consistencia. Hasta el 2026-09-24 solo cambiaba la explicacion; con el umbral
#: en 50, cinco rojos seguidos ya daban 51 puntos y una recomendacion.
MIN_SPINS_FOR_SIGNAL = WINDOWS[0]


class Decision(str, Enum):
    """Que hacer en el giro siguiente."""

    recommend = "RECOMMEND"
    no_bet = "NO_BET"


class NoBetReason(str, Enum):
    """Por que el motor no recomienda apostar."""

    insufficient_data = "insufficient_data"
    below_threshold = "below_threshold"


def no_bet_reason(decision: Decision, total_spins: int) -> NoBetReason | None:
    """El motivo de un NO_BET, o None si hay recomendacion."""
    if decision is Decision.recommend:
        return None
    if total_spins < MIN_SPINS_FOR_SIGNAL:
        return NoBetReason.insufficient_data
    return NoBetReason.below_threshold


class SignalBand(str, Enum):
    """Los cuatro estados de salida del motor (§2.10).

    Describe la fuerza del criterio interno sobre la muestra ya ocurrida. No es
    una probabilidad de acertar.
    """

    none = "none"      # por debajo del umbral debil: SIN SEÑAL, no apostar
    weak = "weak"      # del umbral debil al medio: SEÑAL DEBIL, solo apuesta base
    medium = "medium"  # del umbral medio al alto: SEÑAL MEDIA
    strong = "strong"  # desde el umbral alto: SEÑAL FUERTE


def strong_threshold_for(threshold: float) -> float:
    """El piso efectivo de SEÑAL FUERTE: nunca por debajo del umbral medio."""
    return max(STRONG_THRESHOLD, threshold)


def weak_threshold_for(weak_threshold: float, threshold: float) -> float:
    """El piso efectivo de SEÑAL DEBIL: nunca por encima del umbral medio.
    Igualarlo al medio apaga la banda DEBIL."""
    return min(weak_threshold, threshold)


def band_for(score: float, threshold: float, weak_threshold: float) -> SignalBand:
    """La banda de un score contra los umbrales de la variante.

    La banda y la decision salen de los mismos umbrales, asi que DEBIL, MEDIA y
    FUERTE siempre llevan recomendacion y SIN SEÑAL nunca. Si el admin sube el
    umbral medio por encima del alto, desaparece la MEDIA; si iguala el debil
    al medio, desaparece la DEBIL.
    """
    if score < weak_threshold_for(weak_threshold, threshold):
        return SignalBand.none
    if score < threshold:
        return SignalBand.weak
    if score >= strong_threshold_for(threshold):
        return SignalBand.strong
    return SignalBand.medium


# --------------------------------------------------------------------------
# Catalogo de mercados
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Market:
    """Una alternativa que el motor puede recomendar."""

    key: str
    label: str
    category_id: str
    group_ids: tuple[str, ...]
    outcomes: frozenset[str]
    #: Pago del sector acertado, "X a 1". En una combinacion de dos docenas es 2,
    #: el de cada docena: el neto del giro lo arma `bankroll`, que sabe que el
    #: otro sector se pierde.
    payout: float
    #: Cuantos grupos se cubren a la vez. 1 o 2 en ruleta.
    sectors: int
    #: Alpha de shrinkage heredado de la categoria (§2.2).
    shrinkage_alpha: float
    #: Posicion en el catalogo, para el desempate determinista.
    order: int

    @property
    def coverage(self) -> int:
        return len(self.outcomes)


def market_catalog(config: GameConfig) -> list[Market]:
    """Mercados evaluables de la variante, en orden estable.

    Salen de dos sitios, ambos en los datos:

    - cada grupo con `market != false` (el verde de la ruleta lo excluye);
    - cada entrada de `allowed_combinations`.

    El orden **no** puede depender de iterar `groups`, que es un objeto JSON y
    pierde el orden al guardarse como JSONB. Se ordena por posicion de la
    categoria en el array `categories` y despues por `group_ids` alfabetico, que
    sobreviven al viaje por la base.
    """
    simples: list[Market] = []
    for category in config.categories:
        for group in category.groups:
            if not group.market:
                continue
            simples.append(
                Market(
                    key=f"{category.id}:{group.id}",
                    label=f"{category.label}: {group.label}",
                    category_id=category.id,
                    group_ids=(group.id,),
                    outcomes=group.outcomes,
                    payout=group.payout,
                    sectors=1,
                    shrinkage_alpha=category.shrinkage_alpha,
                    order=0,
                )
            )
    simples.sort(key=lambda m: (config.category_index(m.category_id), m.group_ids))

    combinados: list[Market] = []
    for combo in config.allowed_combinations:
        category = config.category(combo.category_id)
        if category is None:
            raise KeyError(
                f"La combinacion '{combo.id}' referencia la categoria "
                f"'{combo.category_id}', que no existe"
            )
        grupos = []
        for gid in combo.group_ids:
            group = category.group(gid)
            if group is None:
                raise KeyError(
                    f"La combinacion '{combo.id}' referencia el grupo '{gid}', "
                    f"que no existe en la categoria '{combo.category_id}'"
                )
            grupos.append(group)

        cubiertos: set[str] = set()
        for group in grupos:
            if cubiertos & group.outcomes:
                raise ValueError(
                    f"La combinacion '{combo.id}' tiene grupos que se solapan: "
                    "sumar su cobertura contaria resultados dos veces"
                )
            cubiertos |= group.outcomes

        pagos = {g.payout for g in grupos}
        if len(pagos) != 1:
            raise ValueError(
                f"La combinacion '{combo.id}' mezcla grupos de pagos distintos "
                f"({sorted(pagos)}): el monto por sector no estaria definido"
            )

        combinados.append(
            Market(
                key=combo.id,
                label=combo.label,
                category_id=combo.category_id,
                group_ids=tuple(combo.group_ids),
                outcomes=frozenset(cubiertos),
                payout=pagos.pop(),
                sectors=len(grupos),
                shrinkage_alpha=category.shrinkage_alpha,
                order=0,
            )
        )

    # Las combinaciones conservan el orden declarado, que si sobrevive a JSONB
    # porque `allowed_combinations` es un array.
    return [
        Market(**{**m.__dict__, "order": i})
        for i, m in enumerate(simples + combinados)
    ]


def market_for_key(config: GameConfig, key: str) -> Market | None:
    return next((m for m in market_catalog(config) if m.key == key), None)


# --------------------------------------------------------------------------
# Estadistica por ventana
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowStat:
    """Lo que el mercado hizo dentro de una ventana."""

    window: int
    spins_used: int
    #: Los dos viajan siempre juntos (regla anti-falacia del jugador, §2).
    theoretical_probability: float
    observed_frequency_shrunk: float
    raw_count: int
    #: Intervalo de Wilson sobre los conteos crudos (§2.2).
    observed_ci_low: float
    observed_ci_high: float
    deviation: float
    #: Desviacion estandarizada con signo. Es `significance_score` de §2.6 con
    #: signo y dividida por la desviacion tipica binomial; ese divisor es lo que
    #: vuelve comparables coberturas distintas (18/37 contra 24/37) y variantes
    #: distintas (18/37 contra 18/38).
    z: float


def _standardized_deviation(
    market: Market, total_outcomes: int, results: Sequence[str], lambda_: float
) -> WindowStat:
    p_teorica = market.coverage / total_outcomes
    n = len(results)
    pesos = recency_weights(n, lambda_)
    peso_total = sum(pesos)
    favorable = sum(w for r, w in zip(results, pesos) if r in market.outcomes)
    crudo = sum(1 for r in results if r in market.outcomes)

    p_shrunk = shrinkage_estimate(
        favorable=favorable,
        total=peso_total,
        p_teorica=p_teorica,
        alpha=market.shrinkage_alpha,
    )
    ci_low, ci_high = wilson_interval(crudo, n)

    if peso_total <= 0 or not 0 < p_teorica < 1:
        z = 0.0
    else:
        sigma = math.sqrt(p_teorica * (1 - p_teorica) / peso_total)
        z = (p_shrunk - p_teorica) / sigma

    return WindowStat(
        window=n,
        spins_used=n,
        theoretical_probability=p_teorica,
        observed_frequency_shrunk=p_shrunk,
        raw_count=crudo,
        observed_ci_low=ci_low,
        observed_ci_high=ci_high,
        deviation=p_shrunk - p_teorica,
        z=z,
    )


def available_windows(n_results: int, windows: Sequence[int] = WINDOWS) -> tuple[int, ...]:
    """Ventanas que la sesion alcanza a llenar, de la mas corta a la mas larga.

    Con menos giros que la ventana mas corta se usa el historial entero como
    ventana unica, que es lo que §2.10 pide ("y todo el historial si hay menos").
    """
    llenas = tuple(w for w in sorted(windows) if n_results >= w)
    if llenas:
        return llenas
    return (n_results,) if n_results else ()


def _segments(results: Sequence[str], windows: Sequence[int]) -> list[Sequence[str]]:
    """Tramos DISJUNTOS del historial, del mas reciente al mas antiguo.

    Las ventanas 10/20/50/100 estan anidadas: los 10 giros mas recientes caen
    dentro de las cuatro. Medir "consistencia" sobre ellas premiaria a un
    mercado por un unico tramo caliente contado cuatro veces. Los tramos
    disjuntos (0-10, 10-20, 20-50, 50-100) responden lo que la consistencia
    deberia responder: si la inclinacion aguanta en trozos distintos de la
    sesion o es un solo golpe de suerte.

    La explicacion que ve el usuario sigue mostrando las ventanas acumuladas;
    esto es solo para el componente C.
    """
    n = len(results)
    bordes = [0, *windows]
    tramos = []
    for desde, hasta in zip(bordes, bordes[1:]):
        tramo = results[max(0, n - hasta) : n - desde]
        if tramo:
            tramos.append(tramo)
    return tramos


# --------------------------------------------------------------------------
# Score
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreComponents:
    """Los tres componentes del score, ya normalizados a [0, 1], y sus pesos.

    Se exponen enteros para que "¿Por que recomienda esto?" pueda mostrar de
    donde sale cada punto en vez de un numero caido del cielo.
    """

    deviation: float
    recency: float
    consistency: float | None
    weight_deviation: float
    weight_recency: float
    weight_consistency: float
    chi_square_bonus: float

    @property
    def base_score(self) -> float:
        """Los tres componentes ponderados, antes del bono del chi-cuadrado."""
        pesos = self.weight_deviation + self.weight_recency + self.weight_consistency
        if pesos <= 0:
            return 0.0
        total = (
            self.weight_deviation * self.deviation
            + self.weight_recency * self.recency
            + self.weight_consistency * (self.consistency or 0.0)
        )
        return 100.0 * total / pesos


@dataclass(frozen=True)
class ScoredMarket:
    market: Market
    signal_score: float
    signal_band: SignalBand
    components: ScoreComponents
    #: Una entrada por ventana acumulada, de la mas corta a la mas larga.
    windows: tuple[WindowStat, ...]
    #: p-valor del chi-cuadrado YA corregido (§2.4), o None si no esta activo
    #: para la categoria de este mercado.
    chi_square_pvalue_adjusted: float | None

    @property
    def theoretical_probability(self) -> float:
        return self.windows[-1].theoretical_probability if self.windows else 0.0

    @property
    def observed_frequency_shrunk(self) -> float:
        return self.windows[-1].observed_frequency_shrunk if self.windows else 0.0


def _clamp_unit(value: float) -> float:
    return max(0.0, min(value, 1.0))


def score_market(
    config: GameConfig,
    market: Market,
    results: Sequence[str],
    chi: ChiSquareResult | None = None,
    lambda_: float = RECENCY_LAMBDA,
    threshold: float | None = None,
    weak_threshold: float | None = None,
) -> ScoredMarket:
    """`signal_score` de un mercado sobre el historial dado (§2.10).

        score = 100 x (0.58 D + 0.32 R + 0.10 C) + 10 [chi-cuadrado activo]

    - **D** (desviacion): `z` de la ventana mas larga disponible, la que mas
      muestra tiene, dividido por `Z_MAX` y acotado a [0, 1].
    - **R** (recencia): lo mismo sobre la ventana mas corta — cuanto se esta
      separando ahora, no hace cien giros.
    - **C** (consistencia): `media(z) / media(|z|)` sobre los tramos disjuntos.
      Vale 1 cuando todos los tramos se inclinan al mismo lado y 0 cuando se
      cancelan. Con un solo tramo queda indefinida (un tramo no tiene con que
      ser consistente) y su peso se reparte entre D y R.

    Solo cuenta la desviacion POR ENCIMA de la teorica: un mercado que salio
    menos de lo esperado da componentes en 0, no negativos. Recomendar lo que no
    ha salido seria la falacia del jugador, y el producto no juega a eso.

    `threshold` (umbral medio) y `weak_threshold` (umbral debil) son con los que
    se asigna la banda; por defecto, los de la variante.
    """
    umbral = threshold if threshold is not None else config.recommendation_threshold
    umbral_debil = weak_threshold if weak_threshold is not None else config.weak_threshold
    ventanas = available_windows(len(results))
    if not ventanas:
        vacio = ScoreComponents(
            deviation=0.0,
            recency=0.0,
            consistency=None,
            weight_deviation=WEIGHT_DEVIATION,
            weight_recency=WEIGHT_RECENCY,
            weight_consistency=0.0,
            chi_square_bonus=0.0,
        )
        return ScoredMarket(
            market=market,
            signal_score=0.0,
            signal_band=band_for(0.0, umbral, umbral_debil),
            components=vacio,
            windows=(),
            chi_square_pvalue_adjusted=None,
        )

    total_outcomes = len(config.possible_outcomes)
    stats = tuple(
        _standardized_deviation(market, total_outcomes, results[-w:], lambda_)
        for w in ventanas
    )

    D = _clamp_unit(stats[-1].z / Z_MAX)
    R = _clamp_unit(stats[0].z / Z_MAX)

    tramos = _segments(results, ventanas)
    if len(tramos) >= 2:
        zs = [
            _standardized_deviation(market, total_outcomes, t, lambda_).z for t in tramos
        ]
        magnitud = fmean(abs(z) for z in zs)
        C: float | None = _clamp_unit(fmean(zs) / magnitud) if magnitud > 1e-9 else 0.0
        peso_c = WEIGHT_CONSISTENCY
    else:
        # Un solo tramo no dice nada sobre consistencia. Dejarla en 0 castigaria
        # a todos por igual, y darla por 1 regalaria sus puntos a cualquier
        # mercado que asome por encima de la teorica en los primeros giros.
        C = None
        peso_c = 0.0

    bono = CHI_SQUARE_BONUS if chi is not None and chi.active else 0.0
    componentes = ScoreComponents(
        deviation=D,
        recency=R,
        consistency=C,
        weight_deviation=WEIGHT_DEVIATION,
        weight_recency=WEIGHT_RECENCY,
        weight_consistency=peso_c,
        chi_square_bonus=bono,
    )
    score = _clamp_unit((componentes.base_score + bono) / 100.0) * 100.0

    return ScoredMarket(
        market=market,
        signal_score=score,
        signal_band=band_for(score, umbral, umbral_debil),
        components=componentes,
        windows=stats,
        chi_square_pvalue_adjusted=(
            chi.p_value_adjusted if chi is not None and chi.active else None
        ),
    )


# --------------------------------------------------------------------------
# Recomendacion
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Recommendation:
    """Que hacer en el giro siguiente, y con que respaldo.

    `best` viene tambien cuando la decision es `NO_BET`: siempre hay un mejor
    candidato, solo que por debajo del umbral. Guardarlo es lo que permite que
    el backtest compare los giros en los que el motor hablo con los que callo.
    """

    decision: Decision
    #: Umbral medio: piso de SEÑAL MEDIA.
    threshold: float
    #: Umbral debil efectivo: piso de SEÑAL DEBIL y minimo para recomendar.
    weak_threshold: float
    best: ScoredMarket | None
    #: Todos los mercados, ya ordenados por el desempate. Incluye a `best`.
    candidates: tuple[ScoredMarket, ...]

    @property
    def market(self) -> Market | None:
        """El mercado a apostar, o None si la decision es no apostar."""
        return self.best.market if self.best and self.decision is Decision.recommend else None

    @property
    def signal_score(self) -> float:
        return self.best.signal_score if self.best else 0.0

    @property
    def signal_band(self) -> SignalBand:
        return (
            self.best.signal_band
            if self.best
            else band_for(0.0, self.threshold, self.weak_threshold)
        )


def _tie_break_key(config: GameConfig, scored: ScoredMarket) -> tuple:
    """Desempate determinista (§2.10): mayor score, menor cobertura, orden de
    catalogo.

    Ninguna parte de la clave depende del orden de un objeto JSON, que JSONB no
    conserva: el orden de catalogo sale del array `categories` y de `group_ids`
    ordenados alfabeticamente.
    """
    m = scored.market
    return (
        -scored.signal_score,
        m.coverage,
        config.category_index(m.category_id),
        tuple(sorted(m.group_ids)),
        m.key,
    )


def recommend(
    config: GameConfig,
    results: Sequence[str],
    lambda_: float = RECENCY_LAMBDA,
    full_history: Sequence[str] | None = None,
    threshold: float | None = None,
    weak_threshold: float | None = None,
) -> Recommendation:
    """La recomendacion para el giro siguiente.

    `results` es la ventana de recencia y `full_history` la sesion entera, igual
    que en `ranking.rank_suggestions` y por el mismo motivo: el chi-cuadrado
    pierde entero cada giro que se le recorte (§2.4), mientras que a las señales
    ponderadas recortar no les cuesta casi nada.

    `threshold` gana sobre el umbral medio de la variante; sirve para que el
    admin pruebe un valor sin tocar la configuracion guardada; `weak_threshold`,
    igual sobre el debil. El debil nunca queda por encima del medio.
    """
    umbral = threshold if threshold is not None else config.recommendation_threshold
    umbral_debil = weak_threshold_for(
        weak_threshold if weak_threshold is not None else config.weak_threshold, umbral
    )
    historial = results if full_history is None else full_history
    chis = all_chi_square_signals(config, historial)

    # Sin los giros minimos no se recomienda nada, y la banda tiene que decir
    # lo mismo: con un umbral infinito todo queda SIN SEÑAL.
    hay_datos = len(historial) >= MIN_SPINS_FOR_SIGNAL
    umbral_banda = umbral if hay_datos else math.inf
    umbral_debil_banda = umbral_debil if hay_datos else math.inf

    puntuados = [
        score_market(
            config,
            m,
            results,
            chis.get(m.category_id),
            lambda_,
            umbral_banda,
            umbral_debil_banda,
        )
        for m in market_catalog(config)
    ]
    puntuados.sort(key=lambda s: _tie_break_key(config, s))

    if not puntuados:
        return Recommendation(
            decision=Decision.no_bet,
            threshold=umbral,
            weak_threshold=umbral_debil,
            best=None,
            candidates=(),
        )

    mejor = puntuados[0]
    decision = (
        Decision.recommend
        if hay_datos and mejor.signal_score >= umbral_debil
        else Decision.no_bet
    )
    return Recommendation(
        decision=decision,
        threshold=umbral,
        weak_threshold=umbral_debil,
        best=mejor,
        candidates=tuple(puntuados),
    )


# --------------------------------------------------------------------------
# Resolucion
# --------------------------------------------------------------------------


class Outcome(str, Enum):
    """Como cerro una recomendacion ya emitida."""

    pending = "PENDING"
    hit = "HIT"
    miss = "MISS"


def resolve(market: Market | None, result_value: str) -> Outcome:
    """Marca una recomendacion contra el resultado que salio despues.

    Un `NO_BET` no se resuelve: no hubo nada que acertar ni que fallar, asi que
    queda en `PENDING` para siempre. Cuenta en el denominador de "% de NO
    APOSTAR", no en el de coincidencias.
    """
    if market is None:
        return Outcome.pending
    return Outcome.hit if result_value in market.outcomes else Outcome.miss
