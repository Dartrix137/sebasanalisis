"""Backtest del motor de recomendacion (§2.10).

Python puro: sin FastAPI, sin SQLAlchemy, sin red, igual que el resto de
`engine/`. Recibe historiales y devuelve metricas; de donde salgan esos
historiales es problema de quien lo llame — el script de `scripts/` los genera o
los lee de un archivo, y el endpoint de admin los saca de la base.

Es el control de honestidad de §9 del comparativo: responde si el motor aporta
informacion util o si solo describe el pasado. Nada de lo que calcula aqui se
muestra al cliente.

**La regla que hace que esto sirva de algo:** los pesos del score se fijaron
mirando simulaciones de ruedas justas, no historiales concretos. Medir el motor
sobre los mismos datos con los que se calibro no mide nada. Por eso el endpoint
de admin corre sobre sesiones reales —fuera de muestra por construccion— y las
ruedas simuladas quedan como linea base, donde el ROI TIENE que quedarse en la
ventaja de la casa.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from app.engine.probability import GameConfig
from app.engine.recommendation import Decision, Market, SignalBand, recommend

BAND_LABEL: dict[SignalBand, str] = {
    SignalBand.none: "SIN SEÑAL",
    SignalBand.weak: "DEBIL",
    SignalBand.medium: "MEDIA",
    SignalBand.strong: "FUERTE",
}

#: Giros iniciales que se usan solo como historial, sin evaluar. Sin ellos las
#: primeras recomendaciones se emitirian sobre una mesa practicamente vacia.
WARMUP = 12


# --------------------------------------------------------------------------
# Metricas
# --------------------------------------------------------------------------


@dataclass
class Tally:
    """Resultado acumulado de un grupo de recomendaciones."""

    recommendations: int = 0
    hits: int = 0
    misses: int = 0
    #: Resultado neto en unidades de apuesta base, con los pagos reales.
    units: float = 0.0
    #: Unidades arriesgadas, para el ROI.
    staked: float = 0.0
    #: Serie del acumulado, para la caida maxima.
    equity: list[float] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        return self.hits / self.recommendations if self.recommendations else 0.0

    @property
    def roi(self) -> float:
        """Resultado por unidad arriesgada. En una mesa justa tiende a -house_edge."""
        return self.units / self.staked if self.staked else 0.0

    @property
    def max_drawdown(self) -> float:
        """Peor caida desde un pico previo, en unidades."""
        pico = 0.0
        peor = 0.0
        for v in self.equity:
            pico = max(pico, v)
            peor = min(peor, v - pico)
        return abs(peor)

    def register(self, hit: bool, net: float, staked: float) -> None:
        self.recommendations += 1
        self.hits += int(hit)
        self.misses += int(not hit)
        self.units += net
        self.staked += staked
        self.equity.append(self.units)


@dataclass
class Report:
    spins_evaluated: int = 0
    no_bets: int = 0
    overall: Tally = field(default_factory=Tally)
    by_band: dict[SignalBand, Tally] = field(
        default_factory=lambda: {b: Tally() for b in SignalBand}
    )
    #: Cuantos NO APOSTAR salieron con cada banda del mejor candidato.
    no_bet_by_band: dict[SignalBand, int] = field(
        default_factory=lambda: {b: 0 for b in SignalBand}
    )

    @property
    def decisions(self) -> int:
        return self.overall.recommendations + self.no_bets

    @property
    def no_bet_rate(self) -> float:
        return self.no_bets / self.decisions if self.decisions else 0.0


def net_units(market: Market, hit: bool) -> tuple[float, float]:
    """Resultado neto y unidades arriesgadas de apostar 1 unidad por sector.

    Con los pagos reales: 1:1 en color/paridad/alto-bajo, 2:1 en una docena o
    columna, y 1:2 en dos docenas — donde acertar paga 2 sobre la unidad del
    sector ganador y se pierde la del otro, o sea +1 neto sobre 2 arriesgadas.
    """
    arriesgado = float(market.sectors)
    if not hit:
        return -arriesgado, arriesgado
    # El sector acertado cobra su pago; los demas se pierden enteros.
    return market.payout - (market.sectors - 1), arriesgado


# --------------------------------------------------------------------------
# Corrida
# --------------------------------------------------------------------------


def backtest(
    config: GameConfig,
    historiales: Iterable[Sequence[str]],
    *,
    threshold: float | None = None,
    weak_threshold: float | None = None,
    window_size: int = 50,
    warmup: int = WARMUP,
) -> Report:
    """Corre el motor giro a giro y anota como cerro cada recomendacion.

    En el paso `i` el motor solo ve los giros hasta `i-1`: nunca el resultado que
    se esta evaluando. Es la misma re-simulacion honesta que `engine/baseline.py`.
    """
    informe = Report()

    for historial in historiales:
        for i in range(warmup, len(historial)):
            previos = list(historial[:i])
            siguiente = historial[i]
            informe.spins_evaluated += 1

            resultado = recommend(
                config,
                previos[-window_size:],
                full_history=previos,
                threshold=threshold,
                weak_threshold=weak_threshold,
            )

            banda = resultado.best.signal_band if resultado.best else SignalBand.none
            if resultado.decision is Decision.no_bet:
                informe.no_bets += 1
                informe.no_bet_by_band[banda] += 1
                continue

            market = resultado.market
            assert market is not None
            hit = siguiente in market.outcomes
            neto, arriesgado = net_units(market, hit)
            informe.overall.register(hit, neto, arriesgado)
            informe.by_band[banda].register(hit, neto, arriesgado)

    return informe



def fair_wheel_histories(
    config: GameConfig, n_sessions: int, spins: int, seed: int
) -> list[list[str]]:
    """Ruedas perfectamente justas. La linea base contra la que comparar.

    La semilla se pasa explicita y distinta a la de cualquier calibracion: si se
    reutilizara, el backtest estaria midiendo sobre los mismos datos con los que
    se ajustaron los pesos, que es justo lo que §9 del comparativo prohibe.
    """
    rng = random.Random(seed)
    outcomes = list(config.possible_outcomes)
    return [[rng.choice(outcomes) for _ in range(spins)] for _ in range(n_sessions)]
