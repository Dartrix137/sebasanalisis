"""Gestion de banca: progresiones de apuesta (§2.8).

Python puro: sin FastAPI, sin SQLAlchemy, sin red.

Advertencia que atraviesa todo el modulo y debe llegar intacta a la UI: una
progresion solo redistribuye el tamano de las perdidas y las ganancias. No
cambia la probabilidad de ningun giro ni la ventaja de la casa. Nada de lo que
se calcula aqui anticipa un resultado; describe cuanto dinero exige cada
escalon y con que riesgo, para que el riesgo sea visible y no abstracto.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations

from app.engine.probability import GameConfig, combined_probability


class Strategy(str, Enum):
    """Debe coincidir con `STRATEGIES` de `app.models.game_session`."""

    flat = "flat"
    martingale = "martingale"
    dalembert = "dalembert"
    fibonacci = "fibonacci"
    two_sector_recovery = "two_sector_recovery"


class StrategyMode(str, Enum):
    single = "single"
    two_sector = "two_sector"


#: Estrategias validas por modo (§2.8, regla de validacion cruzada).
STRATEGIES_BY_MODE: dict[StrategyMode, frozenset[Strategy]] = {
    StrategyMode.single: frozenset(
        {Strategy.flat, Strategy.martingale, Strategy.dalembert, Strategy.fibonacci}
    ),
    StrategyMode.two_sector: frozenset({Strategy.two_sector_recovery}),
}

#: En modo dos-sectores se cubren dos grupos a la vez (dos docenas o dos columnas).
SECTORS_IN_TWO_SECTOR_MODE = 2

#: Pago que define cada modo (§2.8). El modo 1:1 son las apuestas de pago par
#: (color, paridad, alto/bajo) y el de dos sectores las de pago 2:1 (docenas,
#: columnas). El motor lo lee del `payout` de cada grupo, nunca de su nombre:
#: asi un juego nuevo con otra estructura entra sin tocar este archivo.
PAYOUT_BY_MODE: dict[StrategyMode, float] = {
    StrategyMode.single: 1.0,
    StrategyMode.two_sector: 2.0,
}

#: Cuantos escalones se muestran por defecto en la tabla de progresion previa.
DEFAULT_PROGRESSION_STAGES = 10


def mode_for(strategy: Strategy) -> StrategyMode:
    """Modo al que pertenece una estrategia."""
    for mode, allowed in STRATEGIES_BY_MODE.items():
        if strategy in allowed:
            return mode
    raise ValueError(f"Estrategia desconocida: {strategy}")


def validate_combination(strategy: Strategy, mode: StrategyMode) -> None:
    """Rechaza mezclar un modo con una estrategia del otro modo.

    El endpoint traduce este error a un 422; el motor nunca intenta
    interpretar una combinacion invalida (§2.8).
    """
    if strategy not in STRATEGIES_BY_MODE[mode]:
        raise ValueError(
            f"La estrategia '{strategy.value}' no pertenece al modo '{mode.value}'"
        )


def _round_money(amount: float) -> float:
    return round(amount + 0.0, 2)


# --------------------------------------------------------------------------
# Multiplicadores por escalon (en unidades de apuesta base)
# --------------------------------------------------------------------------


def _fibonacci_multiplier(stage: int) -> int:
    """Fibonacci de apuesta: 1, 1, 2, 3, 5, 8, ... (`stage` es 0-indexado)."""
    previous, current = 1, 1
    for _ in range(stage):
        previous, current = current, previous + current
    return previous


def stage_multiplier(strategy: Strategy, stage: int) -> float:
    """Cuantas veces la apuesta base se arriesga en `stage` (0-indexado).

    En modo dos-sectores el valor es la apuesta *por sector*, no el total del
    giro: la secuencia validada 1, 2, 6, 18, 54 se expresa por docena.
    """
    if stage < 0:
        raise ValueError("El escalon no puede ser negativo")

    if strategy is Strategy.flat:
        return 1.0
    if strategy is Strategy.martingale:
        return float(2**stage)
    if strategy is Strategy.dalembert:
        return float(1 + stage)
    if strategy is Strategy.fibonacci:
        return float(_fibonacci_multiplier(stage))
    if strategy is Strategy.two_sector_recovery:
        # a_1 = 1; a_k = perdida acumulada tras el escalon k-1, que triplica en
        # cada paso => 1, 2, 6, 18, 54, 162, ...
        return 1.0 if stage == 0 else float(2 * 3 ** (stage - 1))
    raise ValueError(f"Estrategia desconocida: {strategy}")


def sectors_covered(strategy: Strategy) -> int:
    """Cuantos grupos se cubren por giro con esta estrategia."""
    return SECTORS_IN_TWO_SECTOR_MODE if strategy is Strategy.two_sector_recovery else 1


def bet_for_stage(strategy: Strategy, base_bet: float, stage: int) -> float:
    """Total arriesgado en el giro del escalon `stage`, sumando todos los sectores."""
    if base_bet <= 0:
        raise ValueError("La apuesta base debe ser positiva")
    per_sector = base_bet * stage_multiplier(strategy, stage)
    return _round_money(per_sector * sectors_covered(strategy))


def cumulative_risked(strategy: Strategy, base_bet: float, stage: int) -> float:
    """Dinero perdido si fallaron todos los escalones desde el 0 hasta `stage`."""
    return _round_money(
        sum(bet_for_stage(strategy, base_bet, s) for s in range(stage + 1))
    )


# --------------------------------------------------------------------------
# Avance de escalon
# --------------------------------------------------------------------------


def advance_stage_by_round(
    strategy: Strategy, stage: int, round_net_change: float
) -> int:
    """Escalon siguiente cuando el giro llevaba varias apuestas a la vez.

    En una mesa real se apuesta a varias cosas en el mismo giro, y entonces
    "gano" o "perdio" no es un booleano: unas aciertan y otras no. La progresion
    avanza segun como cerro el giro **completo**, que es como lo piensa quien la
    usa: si salio adelante cuenta como victoria, si salio atras como derrota.

    Un giro que cierra exactamente en cero no mueve el escalon: no hubo nada que
    recuperar ni nada que cerrar.
    """
    if stage < 0:
        raise ValueError("El escalon no puede ser negativo")

    if strategy is Strategy.flat:
        return 0
    if round_net_change == 0:
        return stage
    return advance_stage(strategy, stage, round_net_change > 0)


def net_result_if_won(
    strategy: Strategy, base_bet: float, stage: int, payout: float | None = None
) -> float:
    """Con cuanto queda la serie completa si el giro del escalon `stage` se gana.

    Es el punto donde las dos familias de progresion se separan, y la diferencia
    no es obvia mirando solo las tablas:

    - Martingala 1:1: ganar deja exactamente una apuesta base de ganancia.
    - Recuperacion de dos sectores: del escalon 2 en adelante, ganar devuelve la
      serie a **cero**, no deja ganancia. La apuesta por sector de un escalon es
      justo la perdida acumulada del anterior, asi que acertar recupera lo
      perdido y nada mas.
    - D'Alembert y Fibonacci no recuperan la serie completa: pueden cerrar en
      negativo aunque el giro se gane.

    `payout` se toma del modo de la estrategia si no se pasa explicito.
    """
    if base_bet <= 0:
        raise ValueError("La apuesta base debe ser positiva")

    pago = PAYOUT_BY_MODE[mode_for(strategy)] if payout is None else payout
    sectores = sectors_covered(strategy)
    apuesta_por_sector = base_bet * stage_multiplier(strategy, stage)

    # El sector acertado devuelve lo apostado mas su pago; los demas se pierden.
    neto_del_giro = apuesta_por_sector * pago - apuesta_por_sector * (sectores - 1)
    perdido_antes = (
        cumulative_risked(strategy, base_bet, stage - 1) if stage > 0 else 0.0
    )
    return _round_money(neto_del_giro - perdido_antes)


def recovers_only_to_break_even(
    strategy: Strategy, base_bet: float, stage: int
) -> bool:
    """Si ganar en este escalon recupera la serie sin dejar ganancia.

    Existe para que la UI pueda decirlo con datos y no con texto hardcodeado.
    """
    return net_result_if_won(strategy, base_bet, stage) == 0.0


@dataclass(frozen=True)
class EligibleBet:
    """Una apuesta compatible con el modo de la estrategia elegida.

    El motor la arma leyendo los `payout` de la configuracion, sin saber que es
    una docena o un color. Sirve para que la interfaz pueda preguntar "sobre que
    apuesta calculo el riesgo" sin recalcular ninguna probabilidad por su cuenta.
    """

    id: str
    label: str
    category_id: str
    group_ids: tuple[str, ...]
    theoretical_probability: float


def eligible_bets(config: GameConfig, mode: StrategyMode) -> list[EligibleBet]:
    """Apuestas de la variante que encajan con el modo de progresion.

    En modo 1:1, cada grupo de pago par por separado. En modo dos-sectores, cada
    pareja de grupos de pago 2:1 dentro de una misma categoria — que es lo que
    describe §2.8: no hay razon matematica para preferir una pareja sobre otra,
    asi que se ofrecen todas.
    """
    pago_buscado = PAYOUT_BY_MODE[mode]
    apuestas: list[EligibleBet] = []

    for category in config.categories:
        candidatos = [g for g in category.groups if g.payout == pago_buscado]

        if mode is StrategyMode.single:
            for group in candidatos:
                apuestas.append(
                    EligibleBet(
                        id=f"{category.id}:{group.id}",
                        label=f"{category.label}: {group.label}",
                        category_id=category.id,
                        group_ids=(group.id,),
                        theoretical_probability=combined_probability(
                            config, [(category.id, group.id)]
                        ),
                    )
                )
            continue

        for par in combinations(candidatos, SECTORS_IN_TWO_SECTOR_MODE):
            ids = tuple(g.id for g in par)
            apuestas.append(
                EligibleBet(
                    id=f"{category.id}:{'+'.join(ids)}",
                    label=f"{category.label}: {' + '.join(g.label for g in par)}",
                    category_id=category.id,
                    group_ids=ids,
                    theoretical_probability=combined_probability(
                        config, [(category.id, gid) for gid in ids]
                    ),
                )
            )

    return apuestas


def advance_stage(strategy: Strategy, stage: int, won: bool) -> int:
    """Escalon siguiente segun el resultado del giro ya ocurrido.

    No decide que apostar despues: solo mueve el contador de la progresion.
    """
    if stage < 0:
        raise ValueError("El escalon no puede ser negativo")

    if strategy is Strategy.flat:
        return 0
    if not won:
        return stage + 1
    if strategy is Strategy.dalembert:
        return max(0, stage - 1)
    if strategy is Strategy.fibonacci:
        return max(0, stage - 2)
    # Martingala y recuperacion de dos sectores: una victoria cierra la serie.
    return 0


# --------------------------------------------------------------------------
# Tabla de progresion (se muestra ANTES de activar la estrategia)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProgressionRow:
    """Una fila de la tabla de riesgo, con montos reales del usuario."""

    stage: int
    bet_per_sector: float
    total_bet: float
    cumulative_loss: float
    exceeds_table_limit: bool
    exceeds_bankroll: bool


def progression_table(
    strategy: Strategy,
    base_bet: float,
    *,
    stages: int = DEFAULT_PROGRESSION_STAGES,
    table_limit: float | None = None,
    bankroll: float | None = None,
) -> list[ProgressionRow]:
    """Tabla de progresion con montos reales, como las del documento verificado.

    `exceeds_table_limit` marca el escalon en el que la mesa ya no aceptaria la
    apuesta, y `exceeds_bankroll` aquel en el que la banca no alcanzaria: son
    justo los puntos donde la progresion deja de poder recuperarse.
    """
    if stages < 1:
        raise ValueError("La tabla necesita al menos un escalon")

    rows: list[ProgressionRow] = []
    accumulated = 0.0
    for stage in range(stages):
        per_sector = _round_money(base_bet * stage_multiplier(strategy, stage))
        total = _round_money(per_sector * sectors_covered(strategy))
        accumulated = _round_money(accumulated + total)
        rows.append(
            ProgressionRow(
                stage=stage,
                bet_per_sector=per_sector,
                total_bet=total,
                cumulative_loss=accumulated,
                exceeds_table_limit=table_limit is not None and per_sector > table_limit,
                exceeds_bankroll=bankroll is not None and accumulated > bankroll,
            )
        )
    return rows


def max_affordable_stages(
    strategy: Strategy,
    base_bet: float,
    bankroll: float,
    table_limit: float | None = None,
) -> int:
    """Cuantos escalones consecutivos soportaria la banca antes de agotarse.

    Se detiene tambien si la mesa dejaria de aceptar la apuesta: un escalon que
    no se puede colocar no forma parte del plan de recuperacion.
    """
    if base_bet <= 0:
        raise ValueError("La apuesta base debe ser positiva")

    affordable = 0
    accumulated = 0.0
    stage = 0
    while True:
        per_sector = base_bet * stage_multiplier(strategy, stage)
        if table_limit is not None and per_sector > table_limit:
            break
        accumulated += per_sector * sectors_covered(strategy)
        if accumulated > bankroll:
            break
        affordable += 1
        stage += 1
        if strategy is Strategy.flat and affordable > 10_000:
            # La progresion plana no crece: se corta para no iterar sin fin.
            break
    return affordable


def ruin_probability_estimate(
    strategy: Strategy,
    base_bet: float,
    bankroll: float,
    probability_of_winning_the_bet: float,
    table_limit: float | None = None,
) -> float:
    """Riesgo de agotar la banca siguiendo la progresion completa desde el escalon 0.

    Es la probabilidad de encadenar tantas derrotas como escalones soporta la
    banca, asumiendo giros independientes — que es justamente el supuesto
    correcto: la ruleta no tiene memoria, asi que las derrotas no se vuelven
    menos probables por haberse acumulado.
    """
    if not 0.0 <= probability_of_winning_the_bet <= 1.0:
        raise ValueError("La probabilidad debe estar entre 0 y 1")

    stages = max_affordable_stages(strategy, base_bet, bankroll, table_limit)
    if stages == 0:
        # La banca no cubre ni el primer escalon.
        return 1.0
    return (1.0 - probability_of_winning_the_bet) ** stages


# --------------------------------------------------------------------------
# Sugerencia de banca para el giro siguiente
# --------------------------------------------------------------------------

#: Advertencia fija: ninguna progresion altera la ventaja de la casa.
BANKROLL_DISCLAIMER = (
    "Ninguna progresion de apuesta cambia la probabilidad de un giro ni la "
    "ventaja de la casa. Solo redistribuye el tamano de las perdidas y las "
    "ganancias."
)


@dataclass(frozen=True)
class BankrollAdvice:
    """Cuanto exige el escalon actual de la progresion, y con que riesgo."""

    strategy: Strategy
    stage: int
    bet_per_sector: float
    suggested_bet: float
    sectors: int
    cumulative_risked: float
    exceeds_table_limit: bool
    exceeds_bankroll: bool
    ruin_probability_estimate: float | None
    risk_warning: str | None


def _risk_warning(
    strategy: Strategy,
    stage: int,
    exceeds_table_limit: bool,
    exceeds_bankroll: bool,
    ruin: float | None,
) -> str | None:
    partes: list[str] = []
    if exceeds_bankroll:
        partes.append(
            "Este escalon supera la banca disponible: la progresion no se puede "
            "sostener y la serie quedaria abierta en perdida."
        )
    if exceeds_table_limit:
        partes.append(
            "Este escalon supera el limite de la mesa: la apuesta no se podria "
            "colocar, que es donde toda progresion se rompe."
        )
    if strategy in (Strategy.martingale, Strategy.two_sector_recovery) and stage >= 3:
        partes.append(
            f"Vas en el escalon {stage + 1} de una progresion que crece de forma "
            "exponencial; cada escalon adicional multiplica el dinero expuesto."
        )
    if ruin is not None and ruin >= 0.01:
        partes.append(
            f"Riesgo estimado de agotar la banca en esta serie: {ruin:.2%}, "
            "asumiendo giros independientes."
        )
    if not partes:
        return None
    return " ".join(partes) + " " + BANKROLL_DISCLAIMER


def suggest_bet(
    strategy: Strategy,
    base_bet: float,
    stage: int,
    *,
    bankroll_current: float,
    table_limit: float | None = None,
    probability_of_winning_the_bet: float | None = None,
) -> BankrollAdvice:
    """Sugerencia de banca para el giro siguiente, con su advertencia de riesgo.

    Es una sugerencia de *tamano de apuesta* derivada de la progresion elegida
    por el usuario. No sugiere a que apostar ni afirma nada sobre el resultado
    del giro.
    """
    if base_bet <= 0:
        raise ValueError("La apuesta base debe ser positiva")

    per_sector = _round_money(base_bet * stage_multiplier(strategy, stage))
    sectors = sectors_covered(strategy)
    total = _round_money(per_sector * sectors)
    accumulated = cumulative_risked(strategy, base_bet, stage)

    exceeds_limit = table_limit is not None and per_sector > table_limit
    exceeds_bankroll = total > bankroll_current

    ruin = (
        ruin_probability_estimate(
            strategy,
            base_bet,
            bankroll_current,
            probability_of_winning_the_bet,
            table_limit,
        )
        if probability_of_winning_the_bet is not None
        else None
    )

    return BankrollAdvice(
        strategy=strategy,
        stage=stage,
        bet_per_sector=per_sector,
        suggested_bet=total,
        sectors=sectors,
        cumulative_risked=accumulated,
        exceeds_table_limit=exceeds_limit,
        exceeds_bankroll=exceeds_bankroll,
        ruin_probability_estimate=ruin,
        risk_warning=_risk_warning(
            strategy, stage, exceeds_limit, exceeds_bankroll, ruin
        ),
    )
