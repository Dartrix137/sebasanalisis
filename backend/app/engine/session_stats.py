"""Las apuestas de una sesion, contadas por giro (decidido el 2026-10-15).

Python puro: sin FastAPI, sin SQLAlchemy, sin red.

Describe apuestas ya resueltas contra giros ya ocurridos. No dice nada sobre
los giros siguientes: la ventaja de la casa no cambia con lo que paso.

- **Se cuenta por giro, no por apuesta.** Un giro apostado es el conjunto de
  apuestas resueltas contra el mismo numero. Una recomendacion de dos docenas
  son dos apuestas, y en cada giro al menos una pierde: contadas por separado,
  el porcentaje nunca pasaria del 50 % aunque el giro dejara ganancia. Un giro
  "con ganancia" es el que cerro con neto positivo.
- **Lo observado viaja con lo esperable** (regla anti-falacia del jugador, §2).
  Junto a los giros con ganancia va cuantos cabia esperar por azar con esas
  mismas apuestas: para cada giro, la proporcion de resultados posibles que lo
  habrian cerrado con ganancia, contando cada resultado como equiprobable, que
  es lo que supone el motor.
- **El camino de la banca se mide giro a giro.** Dentro de un giro las apuestas
  se resuelven a la vez; sumarlas una por una inventaria bajones que nunca se
  vivieron (la docena perdida "antes" de la ganada).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.engine.probability import GameConfig
from app.engine.settlement import settle


@dataclass(frozen=True)
class PlacedBet:
    """Una apuesta tal como se puso: casilla y monto."""

    category_id: str
    group_id: str
    amount: float


@dataclass(frozen=True)
class BetRound:
    """Las apuestas resueltas contra un mismo numero, y el numero que salio."""

    bets: tuple[PlacedBet, ...]
    outcome: str


@dataclass(frozen=True)
class SessionBetStats:
    rounds: int
    rounds_won: int
    #: Giros con ganancia que cabia esperar por azar con esas mismas apuestas.
    expected_rounds_won: float
    net_change: float
    #: Lo mas que la banca llego a estar por encima de la inicial. Cero si nunca
    #: la supero.
    best_moment: float
    #: La peor caida desde un pico previo (el pico puede ser la banca inicial).
    max_drawdown: float

    @property
    def win_rate(self) -> float:
        return self.rounds_won / self.rounds if self.rounds else 0.0

    @property
    def expected_win_rate(self) -> float:
        return self.expected_rounds_won / self.rounds if self.rounds else 0.0


def round_net(config: GameConfig, bets: Sequence[PlacedBet], outcome: str) -> float:
    """Cambio neto de la banca en un giro con esas apuestas y ese resultado."""
    return round(
        sum(
            settle(config, b.category_id, b.group_id, b.amount, outcome).net_change
            for b in bets
        ),
        2,
    )


def round_win_probability(config: GameConfig, bets: Sequence[PlacedBet]) -> float:
    """Proporcion de resultados posibles que cerrarian el giro con ganancia."""
    if config.total_outcomes == 0:
        raise ValueError("La configuracion no tiene resultados posibles")
    if not bets:
        return 0.0
    ganadores = sum(
        1 for outcome in config.possible_outcomes if round_net(config, bets, outcome) > 0
    )
    return ganadores / config.total_outcomes


def session_bet_stats(config: GameConfig, rounds: Sequence[BetRound]) -> SessionBetStats:
    """Resume los giros apostados de una sesion, en el orden en que salieron."""
    saldo = pico = 0.0
    mejor = caida = 0.0
    ganados = 0
    esperados = 0.0

    for r in rounds:
        neto = round_net(config, r.bets, r.outcome)
        if neto > 0:
            ganados += 1
        esperados += round_win_probability(config, r.bets)

        saldo += neto
        pico = max(pico, saldo)
        mejor = max(mejor, saldo)
        caida = max(caida, pico - saldo)

    return SessionBetStats(
        rounds=len(rounds),
        rounds_won=ganados,
        expected_rounds_won=esperados,
        net_change=round(saldo, 2),
        best_moment=round(mejor, 2),
        max_drawdown=round(caida, 2),
    )
