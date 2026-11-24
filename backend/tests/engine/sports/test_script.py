"""Tests del script del backtest de deportes (`scripts/backtest_sports.py`).

Lo que se prueba es lo que protege la regla de §8.5: la prueba se corre una sola
vez y con los mismos datos que se validaron. Sin base de datos ni red.
"""

import json
from pathlib import Path

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
