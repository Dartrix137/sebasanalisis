"""Tests de la recomendacion de un partido (§8.4 n.º 4).

"Apostar: ..." solo si la cuota paga mas que la estimacion propia por al menos
`min_edge`; si no, NO_BET, con la mejor candidata igual a la vista.
"""

import pytest

from app.engine.recommendation import Decision
from app.engine.sports.events import AWAY, DRAW, HOME, HOME_DRAW_AWAY
from app.engine.sports.odds import MarginMethod
from app.engine.sports.recommendation import Policy, recommend

POLITICA = Policy(min_edge=0.05, margin_method=MarginMethod.proportional)


def test_edge_a_mano_y_recomendacion() -> None:
    # Local: 0.50 * 2.2 - 1 = 0.10. Empate: 0.25 * 3.4 - 1 = -0.15. Visitante: 0.25 * 3.6 - 1 = -0.10.
    rec = recommend(
        {HOME: 0.5, DRAW: 0.25, AWAY: 0.25},
        {HOME: 2.2, DRAW: 3.4, AWAY: 3.6},
        HOME_DRAW_AWAY,
        POLITICA,
    )
    assert rec.decision is Decision.recommend
    assert rec.outcome == HOME
    assert rec.best.edge == pytest.approx(0.10)
    edges = {c.outcome: c.edge for c in rec.candidates}
    assert edges == pytest.approx({HOME: 0.10, DRAW: -0.15, AWAY: -0.10})


def test_cada_candidata_trae_la_estimacion_y_la_implicita_sin_margen() -> None:
    rec = recommend({HOME: 0.5, DRAW: 0.25, AWAY: 0.25}, {HOME: 2.0, DRAW: 4.0, AWAY: 4.0}, HOME_DRAW_AWAY, POLITICA)
    for c in rec.candidates:
        assert c.model_probability > 0
        assert c.market_probability > 0
    assert sum(c.market_probability for c in rec.candidates) == pytest.approx(1.0)
    assert rec.overround == pytest.approx(0.0)


def test_bajo_el_umbral_no_se_apuesta_pero_la_mejor_viaja() -> None:
    # Local: 0.5 * 2.08 - 1 = 0.04, bajo 0.05.
    rec = recommend({HOME: 0.5, DRAW: 0.25, AWAY: 0.25}, {HOME: 2.08, DRAW: 3.4, AWAY: 3.6}, HOME_DRAW_AWAY, POLITICA)
    assert rec.decision is Decision.no_bet
    assert rec.outcome is None
    assert rec.best.outcome == HOME


def test_el_umbral_es_inclusivo() -> None:
    # 0.5 * 2.5 - 1 = 0.25, y el umbral es 0.25.
    rec = recommend({HOME: 0.5, AWAY: 0.5}, {HOME: 2.5, AWAY: 1.6}, (HOME, AWAY), Policy(0.25, MarginMethod.shin))
    assert rec.decision is Decision.recommend


def test_desempate_por_probabilidad_y_despues_por_orden() -> None:
    # Local 0.4 * 2.5 - 1 = 0; visitante 0.2 * 5 - 1 = 0. Mismo edge: gana el mas probable.
    rec = recommend({HOME: 0.4, DRAW: 0.4, AWAY: 0.2}, {HOME: 2.5, DRAW: 2.0, AWAY: 5.0}, HOME_DRAW_AWAY, Policy(-1.0, MarginMethod.proportional))
    assert rec.best.outcome == HOME
    # Todo igual: el orden del deporte.
    rec = recommend({HOME: 0.5, AWAY: 0.5}, {HOME: 2.0, AWAY: 2.0}, (HOME, AWAY), Policy(-1.0, MarginMethod.proportional))
    assert rec.best.outcome == HOME


def test_tope_de_cuota() -> None:
    # Visitante: 0.2 * 6.0 - 1 = 0.2, pero la cuota pasa el tope; local 0.6 * 1.8 - 1 = 0.08.
    rec = recommend(
        {HOME: 0.6, DRAW: 0.2, AWAY: 0.2},
        {HOME: 1.8, DRAW: 4.0, AWAY: 6.0},
        HOME_DRAW_AWAY,
        Policy(0.05, MarginMethod.proportional, max_odds=5.0),
    )
    assert rec.outcome == HOME


def test_resultados_que_no_cuadran_se_rechazan() -> None:
    with pytest.raises(ValueError):
        recommend({HOME: 0.5, AWAY: 0.5}, {HOME: 2.0, DRAW: 3.0, AWAY: 2.0}, HOME_DRAW_AWAY, POLITICA)
    with pytest.raises(ValueError):
        recommend({HOME: 0.6, AWAY: 0.6}, {HOME: 2.0, AWAY: 2.0}, (HOME, AWAY), POLITICA)
