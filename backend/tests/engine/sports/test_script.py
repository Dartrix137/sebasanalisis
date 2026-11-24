"""Tests del script del backtest de deportes (`scripts/backtest_sports.py`).

Lo que se prueba es lo que protege la regla de §8.5: la prueba se corre una sola
vez y con los mismos datos que se validaron. Sin base de datos ni red.
"""

import json
from pathlib import Path

import pytest

from app.engine.sports.events import AWAY, DRAW, HOME
from scripts import backtest_sports as cli


def test_lee_columnas_de_otra_fuente_y_constantes(tmp_path: Path) -> None:
    csv = tmp_path / "fuente.csv"
    csv.write_text(
        "Fecha,Local,Visitante,GL,GV,CL,CE,CV\n"
        "15/08/2020,A,B,2,1,2.10,3.40,3.60\n"
        "16/08/2020,C,D,0,0,,3.10,2.50\n",
        encoding="utf-8",
    )
    columnas = {
        "competition": "=LIGA", "season": "=2020-2021", "date": "Fecha", "home": "Local", "away": "Visitante",
        "home_score": "GL", "away_score": "GV", "close_home": "CL", "close_draw": "CE", "close_away": "CV",
    }  # fmt: skip
    eventos = cli.load_events([csv], "football", columnas, "%d/%m/%Y")
    assert len(eventos) == 2
    primero = eventos[0]
    assert (primero.competition, primero.season, primero.home, primero.away) == ("LIGA", "2020-2021", "A", "B")
    assert primero.closing_odds == {HOME: 2.10, DRAW: 3.40, AWAY: 3.60}
    # Falta una cuota: el partido queda sin cuota de cierre, no con una inventada.
    assert eventos[1].closing_odds is None


def test_la_prueba_se_corre_una_sola_vez_y_con_los_mismos_datos(tmp_path: Path) -> None:
    datos = tmp_path / "sim.csv"
    config = tmp_path / "cfg.json"
    informe = tmp_path / "rep.json"
    assert cli.main(["synthetic", "--sport", "two-way", "--out", str(datos), "--teams", "6", "--seasons", "5"]) == 0
    assert cli.main(["validate", "--sport", "two-way", "--data", str(datos), "--config", str(config)]) == 0
    assert json.loads(config.read_text(encoding="utf-8"))["data_fingerprint"]

    # Datos cambiados despues de validar: no se corre.
    otros = tmp_path / "otros.csv"
    otros.write_text(datos.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert cli.main(["test", "--config", str(config), "--data", str(otros), "--report", str(informe)]) == 1
    assert not informe.exists()

    assert cli.main(["test", "--config", str(config), "--data", str(datos), "--report", str(informe)]) == 0
    resultado = json.loads(informe.read_text(encoding="utf-8"))
    assert "passed" in resultado["verdict"]

    # Segunda vez: se niega y no toca el informe.
    antes = informe.read_text(encoding="utf-8")
    assert cli.main(["test", "--config", str(config), "--data", str(datos), "--report", str(informe)]) == 1
    assert informe.read_text(encoding="utf-8") == antes


def test_cuota_americana_a_decimal_a_mano() -> None:
    # +130 paga 130 por 100: 2.30. -150 pide 150 para ganar 100: 1 + 100/150 = 1.666667.
    assert cli.american_to_decimal(130) == pytest.approx(2.30)
    assert cli.american_to_decimal(-150) == pytest.approx(1.666667, abs=1e-6)
    assert cli.american_to_decimal(100) == pytest.approx(2.0)
    with pytest.raises(ValueError):
        cli.american_to_decimal(0)


def test_nba_de_olivier_promedio_de_las_casas_con_las_dos_cuotas(tmp_path: Path) -> None:
    csv = tmp_path / "nba.csv"
    csv.write_text(
        "League,Game_ID,Season,Home_Team,Away_Team,Home_Score,Away_Score,"
        "Pinnacle_ML_Home_Close,Pinnacle_ML_Away_Close,FanDuel_ML_Home_Close,FanDuel_ML_Away_Close,"
        "Kalshi_ML_Home_Close,Kalshi_ML_Away_Close,Pinnacle_ML_Home_Open,Pinnacle_ML_Away_Open\n"
        # Juego de la costa este del 1 de noviembre aunque en UTC sea el 2.
        "NBA,20261101_BOS_ORL,2026/2027,Orlando Magic,Boston Celtics,97,108,200,-250,100,,500,-900,150,-180\n",
        encoding="utf-8",
    )
    [evento] = cli.load_olivier_nba([csv])
    assert evento.date.isoformat() == "2026-11-01"
    assert evento.season == "2026-2027"
    assert (evento.home, evento.away, evento.home_score, evento.away_score) == ("Orlando Magic", "Boston Celtics", 97, 108)
    # FanDuel no tiene la cuota del visitante y Kalshi no es una casa: solo entra Pinnacle.
    # +200 -> 3.00; -250 -> 1 + 100/250 = 1.40.
    assert evento.closing_odds == pytest.approx({HOME: 3.0, AWAY: 1.4})
    # Apertura: +150 -> 2.50; -180 -> 1.555556.
    assert evento.opening_odds == pytest.approx({HOME: 2.5, AWAY: 1.555556}, abs=1e-6)
    # Con una casa sola.
    [solo] = cli.load_olivier_nba([csv], "FanDuel")
    assert solo.closing_odds is None
