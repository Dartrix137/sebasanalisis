"""Tests de los modelos de deportes: Dixon-Coles (futbol) y Elo (dos resultados).

Lo que no puede fallar: que un modelo use un partido de la fecha que estima o
posterior. Una fuga de datos futuros haria pasar el backtest sin que nada lo
delate.
"""

from datetime import date, timedelta

import numpy as np
import pytest
from scipy.optimize import check_grad

from app.engine.sports.events import AWAY, DRAW, HOME, Event
from app.engine.sports.models.dixon_coles import DixonColes, negative_log_likelihood
from app.engine.sports.models.elo import Elo
from app.engine.sports.synthetic import football_league


def _partido(n: int, dia: date, local: str, visitante: str, gl: int, gv: int) -> Event:
    return Event(f"p{n}", "LIGA", "2020", dia, local, visitante, gl, gv)


# --------------------------------------------------------------------------
# Dixon-Coles
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def liga() -> list[Event]:
    return football_league(n_teams=8, n_seasons=4, seed=3)


def test_dixon_coles_no_ve_el_dia_que_estima_ni_el_futuro(liga: list[Event]) -> None:
    corte = liga[len(liga) // 2].date
    pasado = [e for e in liga if e.date < corte]
    modelo = DixonColes(min_matches=1)
    con_todo = modelo.fit(liga, as_of=corte)
    solo_pasado = modelo.fit(pasado, as_of=corte)
    assert con_todo.attack == solo_pasado.attack
    assert con_todo.defence == solo_pasado.defence
    assert con_todo.rho == solo_pasado.rho


def test_dixon_coles_las_tres_probabilidades_suman_uno(liga: list[Event]) -> None:
    ajuste = DixonColes(min_matches=1, window_days=20 * 365).fit(liga, as_of=date(2030, 1, 1))
    probs = ajuste.estimate("Equipo 01", "Equipo 02")
    assert probs is not None
    assert set(probs) == {HOME, DRAW, AWAY}
    assert sum(probs.values()) == pytest.approx(1.0)
    assert all(0 < p < 1 for p in probs.values())


def test_dixon_coles_no_estima_un_equipo_con_pocos_partidos() -> None:
    dia = date(2020, 1, 1)
    partidos = [_partido(i, dia + timedelta(days=i), "A", "B", 1, 0) for i in range(3)]
    ajuste = DixonColes(min_matches=4).fit(partidos, as_of=date(2021, 1, 1))
    assert ajuste.estimate("A", "B") is None
    assert ajuste.estimate("A", "Desconocido") is None


def test_dixon_coles_gradiente_analitico_coincide_con_el_numerico(liga: list[Event]) -> None:
    equipos = sorted({e.home for e in liga})
    idx = {t: i for i, t in enumerate(equipos)}
    h = np.array([idx[e.home] for e in liga])
    a = np.array([idx[e.away] for e in liga])
    x = np.array([e.home_score for e in liga], dtype=float)
    y = np.array([e.away_score for e in liga], dtype=float)
    w = np.linspace(0.5, 1.0, len(liga))
    n = len(equipos)
    punto = np.random.default_rng(0).normal(0, 0.2, 2 * n + 2)
    punto[-1] = 0.05  # rho dentro de su cota

    def valor(p: np.ndarray) -> float:
        return negative_log_likelihood(p, h, a, x, y, w, n, 1e-3)[0]

    def gradiente(p: np.ndarray) -> np.ndarray:
        return negative_log_likelihood(p, h, a, x, y, w, n, 1e-3)[1]

    assert check_grad(valor, gradiente, punto) < 1e-4


def test_dixon_coles_recupera_quien_es_mas_fuerte() -> None:
    """Con muchas temporadas de una liga simulada, el modelo se acerca a la verdad."""
    liga = football_league(n_teams=6, n_seasons=10, seed=11, spread=0.5)
    ajuste = DixonColes(xi=0.0, window_days=20 * 365, min_matches=1).fit(liga, as_of=date(2040, 1, 1))
    # La ventaja de local simulada es 0.25.
    assert ajuste.home_advantage == pytest.approx(0.25, abs=0.12)
    # El rho simulado es 0 (goles independientes).
    assert abs(ajuste.rho) < 0.12


def test_dixon_coles_decaimiento_pondera_lo_reciente() -> None:
    """Un equipo que gano siempre antes y perdio siempre hace poco: con decaimiento
    alto pesa lo reciente."""
    dia = date(2020, 1, 1)
    partidos: list[Event] = []
    n = 0
    for i in range(20):
        partidos.append(_partido(n, dia + timedelta(days=i), "A", "B", 3, 0))
        n += 1
    for i in range(20):
        partidos.append(_partido(n, dia + timedelta(days=400 + i), "A", "B", 0, 3))
        n += 1
    corte = dia + timedelta(days=430)
    sin = DixonColes(xi=0.0, min_matches=1).fit(partidos, as_of=corte).estimate("A", "B")
    con = DixonColes(xi=0.02, min_matches=1).fit(partidos, as_of=corte).estimate("A", "B")
    assert sin is not None and con is not None
    assert con[AWAY] > sin[AWAY]


# --------------------------------------------------------------------------
# Elo
# --------------------------------------------------------------------------


def test_elo_a_mano() -> None:
    """1500 contra 1500 sin localia: E = 0.5, el ganador suma 20 * 0.5 = 10.

    Despues, 1510 contra 1490: E = 1 / (1 + 10^(-20/400)) = 1 / 1.891251 = 0.528751.
    """
    partido = _partido(0, date(2020, 1, 1), "A", "B", 1, 0)
    ajuste = Elo(k=20, home_advantage=0, min_games=1).fit([partido], as_of=date(2020, 1, 2))
    assert ajuste.ratings == {"A": 1510.0, "B": 1490.0}
    probs = ajuste.estimate("A", "B")
    assert probs is not None
    assert probs[HOME] == pytest.approx(0.528751, abs=1e-6)
    assert probs[HOME] + probs[AWAY] == pytest.approx(1.0)


def test_elo_ventaja_de_local_a_mano() -> None:
    """Iguales con H = 50: E = 1 / (1 + 10^(-50/400)) = 1 / 1.749894 = 0.571463."""
    partidos = [
        _partido(0, date(2020, 1, 1), "A", "B", 1, 0),
        _partido(1, date(2020, 1, 2), "B", "A", 1, 0),
    ]
    # K = 0: nadie se mueve, solo cuenta la localia.
    ajuste = Elo(k=0, home_advantage=50, min_games=1).fit(partidos, as_of=date(2020, 2, 1))
    probs = ajuste.estimate("A", "B")
    assert probs is not None
    assert probs[HOME] == pytest.approx(0.571463, abs=1e-6)


def test_elo_no_ve_el_dia_que_estima_ni_el_futuro() -> None:
    hoy = date(2020, 1, 10)
    pasado = [_partido(i, date(2020, 1, 1 + i), "A", "B", 1, 0) for i in range(5)]
    mismo_dia = _partido(98, hoy, "B", "A", 5, 0)
    futuro = _partido(99, hoy + timedelta(days=1), "B", "A", 5, 0)
    modelo = Elo(min_games=1)
    assert modelo.fit([*pasado, mismo_dia, futuro], as_of=hoy) == modelo.fit(pasado, as_of=hoy)


def test_elo_no_estima_equipos_con_pocos_partidos() -> None:
    partido = _partido(0, date(2020, 1, 1), "A", "B", 1, 0)
    assert Elo(min_games=2).fit([partido], as_of=date(2020, 2, 1)).estimate("A", "B") is None


def test_elo_un_empate_no_mueve_a_nadie() -> None:
    empate = _partido(0, date(2020, 1, 1), "A", "B", 1, 1)
    ajuste = Elo(min_games=1).fit([empate], as_of=date(2020, 2, 1))
    assert ajuste.ratings == {"A": 1500.0, "B": 1500.0}
