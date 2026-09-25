"""Tests del backtest del motor de recomendacion (§2.10, §9 del comparativo).

El backtest es lo que distingue "el motor funciona" de "el motor aporta algo", y
por eso sus propias cuentas tienen que estar bien: un ROI mal calculado haria
pasar por util algo que no lo es.
"""

import pytest

from app.engine.backtest import (
    WARMUP,
    Report,
    Tally,
    backtest,
    fair_wheel_histories,
    net_units,
)
from app.engine.recommendation import SignalBand, market_for_key


# --------------------------------------------------------------------------
# Pagos reales
# --------------------------------------------------------------------------


def test_los_pagos_son_los_reales_de_la_mesa(europea) -> None:
    """1:1 en color, 2:1 en una docena, y 1:2 en dos docenas.

    El de dos docenas es el que se equivoca solo: se apuesta 1 unidad en CADA
    docena (2 arriesgadas), el sector acertado paga 2 y el otro se pierde entero,
    asi que el neto es +1 sobre 2 arriesgadas, no +2.
    """
    color = market_for_key(europea, "color:red")
    assert net_units(color, hit=True) == (1.0, 1.0)
    assert net_units(color, hit=False) == (-1.0, 1.0)

    docena = market_for_key(europea, "dozen:first")
    assert net_units(docena, hit=True) == (2.0, 1.0)
    assert net_units(docena, hit=False) == (-1.0, 1.0)

    dos_docenas = market_for_key(europea, "dozen:first+second")
    assert net_units(dos_docenas, hit=True) == (1.0, 2.0)
    assert net_units(dos_docenas, hit=False) == (-2.0, 2.0)


def test_el_roi_de_dos_docenas_es_por_unidad_arriesgada(europea) -> None:
    """Acertar dos docenas deja +1 sobre 2 puestas: un ROI de +0.5, no de +1."""
    t = Tally()
    dos = market_for_key(europea, "dozen:first+second")
    neto, arriesgado = net_units(dos, hit=True)
    t.register(True, neto, arriesgado)
    assert t.roi == pytest.approx(0.5)


# --------------------------------------------------------------------------
# Acumulados
# --------------------------------------------------------------------------


def test_la_caida_maxima_no_la_esconde_un_neto_final_en_cero() -> None:
    """Perder tres y recuperar deja el neto en 0, pero se vivio un -3."""
    t = Tally()
    for _ in range(3):
        t.register(False, -1.0, 1.0)
    for _ in range(3):
        t.register(True, 1.0, 1.0)
    assert t.units == pytest.approx(0.0)
    assert t.max_drawdown == pytest.approx(3.0)


def test_sin_recomendaciones_las_tasas_son_cero_y_no_revientan() -> None:
    t = Tally()
    assert t.hit_rate == 0.0
    assert t.roi == 0.0
    assert t.max_drawdown == 0.0

    informe = Report()
    assert informe.decisions == 0
    assert informe.no_bet_rate == 0.0


def test_la_tasa_de_coincidencia_cuenta_aciertos_sobre_recomendaciones() -> None:
    t = Tally()
    t.register(True, 1.0, 1.0)
    t.register(False, -1.0, 1.0)
    t.register(True, 1.0, 1.0)
    assert t.recommendations == 3
    assert t.hits == 2
    assert t.misses == 1
    assert t.hit_rate == pytest.approx(2 / 3)


# --------------------------------------------------------------------------
# Corrida completa
# --------------------------------------------------------------------------


def test_las_decisiones_cuadran_con_los_giros_evaluados(europea) -> None:
    """Cada giro evaluado produce exactamente una decision: recomendar o no."""
    historiales = fair_wheel_histories(europea, n_sessions=3, spins=40, seed=1)
    informe = backtest(europea, historiales)

    assert informe.spins_evaluated == 3 * (40 - WARMUP)
    assert informe.decisions == informe.spins_evaluated
    assert informe.overall.recommendations + informe.no_bets == informe.decisions


def test_los_aciertos_por_banda_suman_el_total(europea) -> None:
    historiales = fair_wheel_histories(europea, n_sessions=3, spins=60, seed=2)
    informe = backtest(europea, historiales)

    assert sum(t.recommendations for t in informe.by_band.values()) == (
        informe.overall.recommendations
    )
    assert sum(t.hits for t in informe.by_band.values()) == informe.overall.hits
    assert sum(informe.no_bet_by_band.values()) == informe.no_bets


def test_un_umbral_imposible_deja_todo_en_no_apostar(europea) -> None:
    historiales = fair_wheel_histories(europea, n_sessions=2, spins=40, seed=3)
    informe = backtest(europea, historiales, threshold=101, weak_threshold=101)

    assert informe.overall.recommendations == 0
    assert informe.no_bets == informe.decisions
    assert informe.no_bet_rate == pytest.approx(1.0)


def test_un_umbral_de_cero_recomienda_siempre(europea) -> None:
    historiales = fair_wheel_histories(europea, n_sessions=2, spins=40, seed=4)
    informe = backtest(europea, historiales, threshold=0)

    assert informe.no_bets == 0
    assert informe.overall.recommendations == informe.decisions


def test_el_backtest_es_determinista(europea) -> None:
    """Mismos historiales, mismo informe: el motor no tiene azar propio."""
    historiales = fair_wheel_histories(europea, n_sessions=2, spins=50, seed=5)
    a = backtest(europea, historiales)
    b = backtest(europea, historiales)
    assert (a.overall.hits, a.overall.units, a.no_bets) == (
        b.overall.hits,
        b.overall.units,
        b.no_bets,
    )


def test_la_misma_semilla_da_los_mismos_historiales(europea) -> None:
    assert fair_wheel_histories(europea, 2, 30, seed=7) == fair_wheel_histories(
        europea, 2, 30, seed=7
    )
    assert fair_wheel_histories(europea, 2, 30, seed=7) != fair_wheel_histories(
        europea, 2, 30, seed=8
    )


def test_el_motor_nunca_ve_el_giro_que_se_esta_evaluando(europea) -> None:
    """Cambiar el ultimo giro no puede cambiar las decisiones anteriores.

    Es la garantia de que la re-simulacion es honesta: en el paso i solo se usan
    los giros hasta i-1.
    """
    base = fair_wheel_histories(europea, n_sessions=1, spins=40, seed=9)[0]
    otro = base[:-1] + ["0" if base[-1] != "0" else "1"]

    a = backtest(europea, [base[:-1]])
    b = backtest(europea, [otro[:-1]])
    assert a.overall.recommendations == b.overall.recommendations
    assert a.no_bets == b.no_bets


def test_sobre_una_rueda_justa_el_roi_no_supera_la_ventaja_de_la_casa(europea) -> None:
    """La comprobacion honesta de §9: el motor no encuentra estructura donde no
    la hay.

    Se contrasta contra un margen generoso porque con esta muestra el ROI tiene
    ruido de sobra; lo que el test descarta es un error de calculo que hiciera
    aparecer una ventaja sistematica — el sintoma de haber confundido un pago.
    """
    historiales = fair_wheel_histories(europea, n_sessions=25, spins=120, seed=4242)
    informe = backtest(europea, historiales)

    assert informe.overall.recommendations > 50, "muestra demasiado chica para leer nada"
    assert informe.overall.roi < 0.15


def test_funciona_con_un_juego_que_no_es_ruleta(dados) -> None:
    historiales = fair_wheel_histories(dados, n_sessions=2, spins=40, seed=11)
    informe = backtest(dados, historiales)
    assert informe.decisions == 2 * (40 - WARMUP)


def test_las_bandas_estan_todas_en_el_informe(europea) -> None:
    """El informe desglosa por banda aunque alguna quede vacia (§2.10)."""
    informe = backtest(europea, fair_wheel_histories(europea, 1, 30, seed=12))
    assert set(informe.by_band) == set(SignalBand)
    assert set(informe.no_bet_by_band) == set(SignalBand)
