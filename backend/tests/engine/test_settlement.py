"""Resolucion de apuestas reales contra el resultado observado."""

import pytest

from app.engine.probability import GameConfig
from app.engine.settlement import settle

RULETA_MINI = {
    "possible_outcomes": ["0", "1", "2", "3", "4", "5", "6"],
    "categories": [
        {
            "id": "color",
            "label": "Color",
            "shrinkage_alpha": 8,
            "groups": {
                "red": {"label": "Rojo", "outcomes": ["1", "3", "5"], "payout": 1},
                "black": {"label": "Negro", "outcomes": ["2", "4", "6"], "payout": 1},
                "green": {"label": "Verde", "outcomes": ["0"], "payout": 6},
            },
        },
        {
            "id": "tercio",
            "label": "Tercio",
            "shrinkage_alpha": 8,
            "groups": {
                "t1": {"label": "Bajo", "outcomes": ["1", "2"], "payout": 2},
                "t2": {"label": "Medio", "outcomes": ["3", "4"], "payout": 2},
                "t3": {"label": "Alto", "outcomes": ["5", "6"], "payout": 2},
            },
        },
    ],
}


@pytest.fixture
def config() -> GameConfig:
    return GameConfig.from_dict(RULETA_MINI)


# ---------- Pago 1:1 ----------


def test_ganar_a_pago_1a1_devuelve_el_doble(config: GameConfig) -> None:
    """Vuelve lo apostado mas otro tanto: $1.000 puestos devuelven $2.000."""
    r = settle(config, "color", "red", 1_000, "3")
    assert r.won
    assert r.payout == 2_000
    assert r.net_change == 1_000


def test_perder_devuelve_cero_y_resta_lo_apostado(config: GameConfig) -> None:
    r = settle(config, "color", "red", 1_000, "2")
    assert not r.won
    assert r.payout == 0
    assert r.net_change == -1_000


# ---------- Pago 2:1 ----------


def test_ganar_a_pago_2a1_devuelve_el_triple(config: GameConfig) -> None:
    r = settle(config, "tercio", "t1", 1_000, "2")
    assert r.won
    assert r.payout == 3_000
    assert r.net_change == 2_000


# ---------- Pago alto ----------


def test_ganar_al_verde_paga_seis_a_uno(config: GameConfig) -> None:
    r = settle(config, "color", "green", 500, "0")
    assert r.won
    assert r.payout == 3_500
    assert r.net_change == 3_000


def test_el_verde_hace_perder_una_apuesta_a_color(config: GameConfig) -> None:
    """El cero es lo que le da la ventaja a la casa en las apuestas de color."""
    r = settle(config, "color", "red", 1_000, "0")
    assert not r.won
    assert r.net_change == -1_000


# ---------- Coherencia ----------


@pytest.mark.parametrize("outcome", ["0", "1", "2", "3", "4", "5", "6"])
def test_el_neto_siempre_es_payout_menos_lo_apostado(
    config: GameConfig, outcome: str
) -> None:
    r = settle(config, "color", "red", 1_000, outcome)
    assert r.net_change == pytest.approx(r.payout - 1_000)


def test_montos_con_decimales(config: GameConfig) -> None:
    r = settle(config, "color", "red", 1_500.50, "1")
    assert r.payout == 3_001.00
    assert r.net_change == 1_500.50


# ---------- Entradas invalidas ----------


def test_rechaza_monto_no_positivo(config: GameConfig) -> None:
    with pytest.raises(ValueError):
        settle(config, "color", "red", 0, "1")


def test_rechaza_categoria_inexistente(config: GameConfig) -> None:
    with pytest.raises(KeyError):
        settle(config, "inventada", "red", 100, "1")


def test_rechaza_grupo_inexistente(config: GameConfig) -> None:
    with pytest.raises(KeyError):
        settle(config, "color", "morado", 100, "1")


# ---------- Pureza ----------


def test_es_una_funcion_pura(config: GameConfig) -> None:
    a = settle(config, "color", "red", 1_000, "3")
    b = settle(config, "color", "red", 1_000, "3")
    assert a == b
