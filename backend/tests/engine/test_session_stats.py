"""Las apuestas de una sesion, contadas por giro (2026-10-15)."""

import pytest

from app.engine.probability import GameConfig
from app.engine.session_stats import (
    BetRound,
    PlacedBet,
    round_net,
    round_win_probability,
    session_bet_stats,
)

ROJO = PlacedBet("color", "red", 1_000)
PRIMERA = PlacedBet("dozen", "first", 1_000)
SEGUNDA = PlacedBet("dozen", "second", 1_000)


def test_dos_docenas_con_una_ganadora_cierran_el_giro_con_ganancia(europea: GameConfig) -> None:
    """Una docena paga 2 a 1: gana +2.000 y la otra pierde -1.000."""
    assert round_net(europea, [PRIMERA, SEGUNDA], "5") == 1_000
    assert round_net(europea, [PRIMERA, SEGUNDA], "30") == -2_000


def test_lo_esperable_de_un_color_es_su_probabilidad_teorica(europea: GameConfig) -> None:
    assert round_win_probability(europea, [ROJO]) == pytest.approx(18 / 37)


def test_lo_esperable_de_dos_docenas_es_24_de_37(europea: GameConfig) -> None:
    assert round_win_probability(europea, [PRIMERA, SEGUNDA]) == pytest.approx(24 / 37)


def test_en_la_americana_lo_esperable_baja_por_el_doble_cero(americana: GameConfig) -> None:
    assert round_win_probability(americana, [ROJO]) == pytest.approx(18 / 38)


def test_apuestas_que_se_cubren_entre_si_no_cuentan_como_giro_con_ganancia(
    europea: GameConfig,
) -> None:
    """Rojo y negro por igual: neto cero en 36 resultados, perdida con el cero."""
    negro = PlacedBet("color", "black", 1_000)
    assert round_win_probability(europea, [ROJO, negro]) == 0.0


def test_se_cuenta_por_giro_y_no_por_apuesta(europea: GameConfig) -> None:
    giros = [
        BetRound((PRIMERA, SEGUNDA), "5"),  # +1.000
        BetRound((PRIMERA, SEGUNDA), "14"),  # +1.000
        BetRound((PRIMERA, SEGUNDA), "0"),  # -2.000
    ]
    stats = session_bet_stats(europea, giros)

    assert stats.rounds == 3
    assert stats.rounds_won == 2
    assert stats.win_rate == pytest.approx(2 / 3)
    assert stats.expected_rounds_won == pytest.approx(3 * 24 / 37)
    assert stats.expected_win_rate == pytest.approx(24 / 37)
    assert stats.net_change == 0


def test_el_mejor_momento_y_la_peor_caida(europea: GameConfig) -> None:
    """+1.000, +1.000, -1.000, -1.000, -1.000: subio a +2.000 y cayo a -1.000."""
    giros = [BetRound((ROJO,), v) for v in ["1", "3", "2", "4", "6"]]
    stats = session_bet_stats(europea, giros)

    assert stats.best_moment == 2_000
    assert stats.max_drawdown == 3_000
    assert stats.net_change == -1_000


def test_la_caida_cuenta_desde_la_banca_inicial(europea: GameConfig) -> None:
    giros = [BetRound((ROJO,), v) for v in ["2", "4"]]
    stats = session_bet_stats(europea, giros)

    assert stats.best_moment == 0
    assert stats.max_drawdown == 2_000


def test_dentro_de_un_giro_no_hay_bajon_intermedio(europea: GameConfig) -> None:
    """Las dos docenas se resuelven a la vez: el giro que gana no tiene caida."""
    stats = session_bet_stats(europea, [BetRound((PRIMERA, SEGUNDA), "5")])
    assert stats.max_drawdown == 0
    assert stats.best_moment == 1_000


def test_sin_giros_apostados_todo_queda_en_cero(europea: GameConfig) -> None:
    stats = session_bet_stats(europea, [])
    assert stats.rounds == 0
    assert stats.win_rate == 0.0
    assert stats.expected_win_rate == 0.0
    assert stats.best_moment == 0
    assert stats.max_drawdown == 0


def test_funciona_con_un_juego_que_no_es_ruleta(dados: GameConfig) -> None:
    """El calculo sale de `categories_json`: nada supone ruleta."""
    categoria = dados.categories[0]
    grupo = next(iter(categoria.groups))
    apuesta = PlacedBet(categoria.id, grupo.id, 100)
    esperado = len(grupo.outcomes) / dados.total_outcomes
    assert round_win_probability(dados, [apuesta]) == pytest.approx(esperado)
