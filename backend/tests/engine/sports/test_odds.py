"""Tests de la probabilidad implicita y de quitar el margen (§8.4 n.º 4, §8.5).

Los valores esperados estan hechos a mano en los comentarios: si un metodo de
margen esta mal, la linea base del backtest queda mal y el veredicto con ella.
"""

import math

import pytest
from scipy.optimize import brentq

from app.engine.sports.odds import (
    MarginMethod,
    implied,
    overround,
    remove_margin,
    remove_margin_proportional,
    remove_margin_shin,
    shin_z,
)


def test_probabilidad_implicita_y_margen() -> None:
    assert implied([2.0, 4.0]) == [0.5, 0.25]
    # 1/2 + 1/2 = 1: sin margen.
    assert overround([2.0, 2.0]) == pytest.approx(0.0)
    # 2 / 1.9 - 1 = 0.0526315...
    assert overround([1.9, 1.9]) == pytest.approx(2 / 1.9 - 1)


@pytest.mark.parametrize("odds", [[1.0, 2.0], [0.5, 3.0], [2.0], [float("inf"), 2.0], [float("nan"), 2.0]])
def test_cuotas_invalidas_se_rechazan(odds: list[float]) -> None:
    with pytest.raises(ValueError):
        implied(odds)


def test_proporcional_a_mano() -> None:
    # 1/1.5 = 0.666667, 1/4 = 0.25, 1/6 = 0.166667; suma 1.083333.
    # 0.666667/1.083333 = 0.615385; 0.25/1.083333 = 0.230769; 0.166667/1.083333 = 0.153846.
    probs = remove_margin_proportional([1.5, 4.0, 6.0])
    assert probs == pytest.approx([0.615385, 0.230769, 0.153846], abs=1e-6)
    assert sum(probs) == pytest.approx(1.0)


def test_shin_con_dos_resultados_es_el_margen_repartido_por_igual() -> None:
    """Propiedad conocida del metodo de Shin: con dos resultados, a cada uno se le
    resta la mitad del margen.

    1/1.5 = 0.666667, 1/2.6 = 0.384615; margen 0.051282, la mitad 0.025641.
    0.666667 - 0.025641 = 0.641026; 0.384615 - 0.025641 = 0.358974.
    """
    assert remove_margin_shin([1.5, 2.6]) == pytest.approx([0.641026, 0.358974], abs=1e-6)


def test_shin_coincide_con_una_resolucion_independiente() -> None:
    """La z de Shin resuelta con brentq de scipy, en lugar de la biseccion del modulo."""
    odds = [1.5, 4.0, 6.0]
    pis = [1 / o for o in odds]
    s = sum(pis)

    def suma(z: float) -> float:
        return sum((math.sqrt(z * z + 4 * (1 - z) * p * p / s) - z) / (2 * (1 - z)) for p in pis) - 1

    z = brentq(suma, 0.0, 0.5)
    assert shin_z(odds) == pytest.approx(z, abs=1e-9)
    esperado = [(math.sqrt(z * z + 4 * (1 - z) * p * p / s) - z) / (2 * (1 - z)) for p in pis]
    assert remove_margin_shin(odds) == pytest.approx(esperado, abs=1e-9)


def test_shin_carga_mas_margen_sobre_los_menos_probables() -> None:
    """Frente al proporcional, Shin le deja mas probabilidad al favorito."""
    shin = remove_margin_shin([1.5, 4.0, 6.0])
    prop = remove_margin_proportional([1.5, 4.0, 6.0])
    assert sum(shin) == pytest.approx(1.0)
    assert shin[0] > prop[0]
    assert shin[2] < prop[2]


def test_sin_margen_los_dos_metodos_dejan_la_implicita() -> None:
    assert shin_z([2.0, 4.0, 4.0]) == 0.0
    for method in MarginMethod:
        assert remove_margin([2.0, 4.0, 4.0], method) == pytest.approx([0.5, 0.25, 0.25])


def test_cuotas_iguales_dan_probabilidades_iguales() -> None:
    for method in MarginMethod:
        assert remove_margin([2.8, 2.8, 2.8], method) == pytest.approx([1 / 3] * 3)
