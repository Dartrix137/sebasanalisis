"""Backtest fuera de muestra de deportes (Fase 6, etapa 1; PLATAFORMA_COMPLETA.md §8.5).

Herramienta interna: nada de lo que imprime se muestra al cliente. Decide si un
deporte sale o no, con el criterio que §8.5 fijo antes de correr nada.

Uso, en tres pasos:

    # 0. (Opcional) una liga simulada para probar que todo corre.
    python -m scripts.backtest_sports synthetic --sport football --out data/sports/sim.csv

    # 1. Validacion: elige margen, modelo y umbral, y congela todo en un archivo.
    python -m scripts.backtest_sports validate --sport football \\
        --data data/sports/liga.csv --config data/sports/futbol.config.json

    # 2. Prueba: la unica corrida sobre las temporadas de prueba.
    python -m scripts.backtest_sports test --config data/sports/futbol.config.json \\
        --data data/sports/liga.csv --report data/sports/futbol.report.json

La regla que hace que esto sirva de algo
----------------------------------------
La prueba se corre **una sola vez**. `test` se niega a escribir sobre un
informe que ya existe y a correr con datos distintos de los que se validaron
(compara su huella). Si se vuelve a validar despues de ver la prueba, esas
temporadas ya no miden nada: hay que esperar temporadas nuevas.

Los datos
---------
CSV con estas columnas (los nombres de otra fuente se traducen con --columns):

    competition, season, date, home, away, home_score, away_score,
    close_home, close_draw, close_away, open_home, open_draw, open_away

`close_draw` y `open_draw` solo en deportes con empate; las de apertura son
opcionales. --columns es un JSON {nuestra_columna: columna_de_la_fuente}; un
valor que empieza con "=" es una constante (por ejemplo, "season": "=2023-2024").

Los archivos van en `backend/data/sports/`, fuera del repositorio (es publico):
la licencia de la fuente se verifica antes de bajarlos y casi nunca deja
redistribuirlos.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Permite `python scripts/backtest_sports.py` ademas de `-m`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.sports.backtest import (  # noqa: E402
    DEFAULT_REFIT_DAYS,
    PhaseReport,
    SeasonSplit,
    ValidationResult,
    Verdict,
    run_test,
    split_seasons,
    validate,
)
from app.engine.sports.events import AWAY, DRAW, HOME, Event  # noqa: E402
from app.engine.sports.models import Model  # noqa: E402
from app.engine.sports.models.dixon_coles import DixonColes  # noqa: E402
from app.engine.sports.models.elo import Elo  # noqa: E402
from app.engine.sports.odds import MarginMethod  # noqa: E402
from app.engine.sports.recommendation import Policy  # noqa: E402
from app.engine.sports.synthetic import (  # noqa: E402
    SyntheticMarket,
    football_league,
    two_way_league,
)

SPORTS = ("football", "two-way")

COLUMNS = (
    "competition", "season", "date", "home", "away", "home_score", "away_score",
    "close_home", "close_draw", "close_away", "open_home", "open_draw", "open_away",
)  # fmt: skip


def model_grid(sport: str) -> list[Model]:
    """La grilla que se compara en validacion, por deporte. Se fija aqui, no en la linea de comandos."""
    if sport == "football":
        return [DixonColes(xi=xi) for xi in (0.0, 0.001, 0.002, 0.004)]
    return [Elo(k=k, home_advantage=h) for k in (10.0, 20.0, 30.0) for h in (0.0, 50.0, 100.0)]


def build_model(sport: str, params: dict[str, Any]) -> Model:
    return DixonColes(**params) if sport == "football" else Elo(**params)


# --------------------------------------------------------------------------
# Lectura de datos
# --------------------------------------------------------------------------


def _parse_date(value: str, fmt: str | None) -> date:
    if fmt:
        return datetime.strptime(value, fmt).date()
    return date.fromisoformat(value)


def _float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(float(value))


def _odds(row: dict[str, str | None], prefix: str, with_draw: bool) -> dict[str, float] | None:
    home = _float(row.get(f"{prefix}_home"))
    away = _float(row.get(f"{prefix}_away"))
    draw = _float(row.get(f"{prefix}_draw")) if with_draw else None
    if home is None or away is None or (with_draw and draw is None):
        return None
    odds = {HOME: home, AWAY: away}
    if with_draw and draw is not None:
        odds[DRAW] = draw
    return odds


def load_events(
    paths: Sequence[Path],
    sport: str,
    columns: dict[str, str] | None = None,
    date_format: str | None = None,
) -> list[Event]:
    columns = columns or {}
    with_draw = sport == "football"
    events: list[Event] = []
    for path in paths:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for n, raw in enumerate(csv.DictReader(fh)):
                row: dict[str, str | None] = {}
                for col in COLUMNS:
                    source = columns.get(col, col)
                    row[col] = source[1:] if source.startswith("=") else raw.get(source)
                if not row["date"] or not row["home"] or not row["away"]:
                    continue
                events.append(
                    Event(
                        event_id=f"{path.name}:{n}",
                        competition=row["competition"] or path.stem,
                        season=row["season"] or "",
                        date=_parse_date(row["date"], date_format),
                        home=row["home"],
                        away=row["away"],
                        home_score=_int(row["home_score"]),
                        away_score=_int(row["away_score"]),
                        closing_odds=_odds(row, "close", with_draw),
                        opening_odds=_odds(row, "open", with_draw),
                    )
                )
    return events


def fingerprint(paths: Sequence[Path], extra: dict[str, Any]) -> str:
    """Huella de los datos y de como se leyeron: la prueba tiene que usar los mismos."""
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.name):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update(json.dumps(extra, sort_keys=True).encode())
    return digest.hexdigest()


def write_events(path: Path, events: Sequence[Event]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for e in events:
            odds = e.closing_odds or {}
            opening = e.opening_odds or {}
            writer.writerow(
                {
                    "competition": e.competition, "season": e.season, "date": e.date.isoformat(),
                    "home": e.home, "away": e.away, "home_score": e.home_score, "away_score": e.away_score,
                    "close_home": odds.get(HOME), "close_draw": odds.get(DRAW), "close_away": odds.get(AWAY),
                    "open_home": opening.get(HOME), "open_draw": opening.get(DRAW), "open_away": opening.get(AWAY),
                }  # fmt: skip
            )


# --------------------------------------------------------------------------
# football-data.co.uk
# --------------------------------------------------------------------------

#: Columnas de sus CSV, segun su `notes.txt` (pegado por el usuario el 2026-11-24):
#: Div, Date (dd/mm/yy; los archivos recientes traen dd/mm/yyyy), HomeTeam,
#: AwayTeam, FTHG, FTAG; la cuota antes del cierre es <casa>H/D/A y la de cierre
#: lleva una "C" despues de la casa: AvgCH = promedio del mercado al cierre.
FOOTBALL_DATA_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y")

#: Mercado de cierre fijado en PLATAFORMA_COMPLETA.md 8.5: el promedio (Avg).
FOOTBALL_DATA_BOOK = "Avg"


def _football_data_date(value: str) -> date:
    for fmt in FOOTBALL_DATA_DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"fecha que no se entiende: {value!r}")


def _football_data_season(path: Path) -> str:
    """`E0_2324.csv` -> "2023-2024": la temporada va en el nombre del archivo."""
    code = path.stem.rsplit("_", 1)[-1]
    if len(code) != 4 or not code.isdigit():
        raise SystemExit(f"{path.name}: el archivo tiene que llamarse <liga>_<aaAA>.csv, como E0_2324.csv")
    return f"20{code[:2]}-20{code[2:]}"


def load_football_data(paths: Sequence[Path], book: str = FOOTBALL_DATA_BOOK) -> list[Event]:
    events: list[Event] = []
    for path in paths:
        season = _football_data_season(path)
        with path.open(newline="", encoding="utf-8-sig", errors="replace") as fh:
            for n, raw in enumerate(csv.DictReader(fh)):
                if not raw.get("Date") or not raw.get("HomeTeam") or not raw.get("AwayTeam"):
                    continue

                def odds(suffix: str, raw: dict[str, str] = raw) -> dict[str, float] | None:
                    values = [_float(raw.get(f"{book}{suffix}{side}")) for side in ("H", "D", "A")]
                    if any(v is None for v in values):
                        return None
                    return {HOME: values[0], DRAW: values[1], AWAY: values[2]}  # type: ignore[dict-item]

                events.append(
                    Event(
                        event_id=f"{path.stem}:{n}",
                        competition=raw.get("Div") or path.stem.rsplit("_", 1)[0],
                        season=season,
                        date=_football_data_date(raw["Date"]),
                        home=raw["HomeTeam"].strip(),
                        away=raw["AwayTeam"].strip(),
                        home_score=_int(raw.get("FTHG")),
                        away_score=_int(raw.get("FTAG")),
                        closing_odds=odds("C"),
                        opening_odds=odds(""),
                    )
                )
    return events


# --------------------------------------------------------------------------
# Salida
# --------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:+.2f} %"


def print_report(title: str, report: PhaseReport) -> None:
    print(f"\n== {title} ==")
    print(f"Partidos medidos: {report.events}  (sin estimacion: {report.no_estimate}, "
          f"sin cuota de cierre: {report.no_odds}, sin resultado: {report.no_result})")  # fmt: skip
    print(f"Log-loss  modelo {report.model_log_loss:.5f} | mercado sin margen {report.market_log_loss:.5f}")
    ci = report.log_loss_diff_ci
    ci_text = "-" if ci is None else f"[{ci.low:+.5f}, {ci.high:+.5f}]"
    print(f"Diferencia (modelo - mercado) {report.log_loss_diff:+.5f}  IC 95 % {ci_text}")
    print(f"Brier     modelo {report.model_brier:.5f} | mercado sin margen {report.market_brier:.5f}")
    roi_ci = report.roi_ci
    roi_ci_text = "-" if roi_ci is None else f"[{_pct(roi_ci.low)}, {_pct(roi_ci.high)}]"
    print(f"Recomendaciones {report.recommendations}  ROI al cierre {_pct(report.roi)}  IC 95 % {roi_ci_text}")
    print(f"Caida maxima {report.max_drawdown:.2f} unidades")
    if report.recommendations_opening:
        print(f"Con la cuota de apertura: {report.recommendations_opening} recomendaciones, "
              f"ROI {_pct(report.roi_opening)}, CLV medio {_pct(report.mean_clv)}")  # fmt: skip
    for comp, s in report.by_competition.items():
        print(f"  {comp}: {s.events} partidos, diferencia {s.log_loss_diff:+.5f}, "
              f"{s.recommendations} recomendaciones, ROI {_pct(s.roi)}")  # fmt: skip


def print_verdict(verdict: Verdict) -> None:
    print("\n== Veredicto (PLATAFORMA_COMPLETA.md 8.5) ==")
    print("SUPERA AL MERCADO" if verdict.passed else "NO SUPERA AL MERCADO")
    print(f"Condicion primaria (log-loss): {'cumple' if verdict.primary else 'no cumple'}")
    print(f"Condicion secundaria (ROI y volumen): {'cumple' if verdict.secondary else 'no cumple'}")
    for reason in verdict.reasons:
        print(f"  - {reason}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, MarginMethod):
        return value.value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------


def _exclude(values: Sequence[str]) -> frozenset[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for v in values:
        comp, sep, season = v.partition(":")
        if not sep:
            raise SystemExit(f"--exclude espera COMPETICION:TEMPORADA, no {v!r}")
        out.add((comp, season))
    return frozenset(out)


def _read_columns(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    unknown = set(data) - set(COLUMNS)
    if unknown:
        raise SystemExit(f"--columns trae columnas desconocidas: {sorted(unknown)}")
    return {str(k): str(v) for k, v in data.items()}


def cmd_synthetic(args: argparse.Namespace) -> int:
    market = SyntheticMarket(margin=args.margin, informed=not args.uninformed)
    if args.sport == "football":
        events = football_league(n_teams=args.teams, n_seasons=args.seasons, seed=args.seed, market=market)
    else:
        events = two_way_league(n_teams=args.teams, n_seasons=args.seasons, seed=args.seed, market=market)
    write_events(Path(args.out), events)
    print(f"{len(events)} partidos simulados en {args.out}. Sirven para probar el backtest, no para medir nada.")
    return 0


# --------------------------------------------------------------------------
# NBA de Olivier Sports Data
# --------------------------------------------------------------------------

#: Las once casas del archivo (su README). Kalshi y Polymarket no entran: son
#: mercados de prediccion, no casas, y aparecen en diciembre de 2025, en plena
#: temporada de prueba, con lo que cambiarian el promedio a mitad de camino.
OLIVIER_NBA_BOOKS = (
    "Pinnacle", "Bet365", "FanDuel", "DraftKings", "BetMGM", "Caesars",
    "BetRivers", "BetOnline", "theScore", "Fanatics", "HardRock",
)  # fmt: skip

#: "Avg" = promedio de las casas con las dos cuotas, como el AvgC* de football-data.
OLIVIER_AVERAGE = "Avg"


def american_to_decimal(value: float) -> float:
    """Cuota americana a decimal: +130 -> 2.30; -150 -> 1.6667."""
    if value > 0:
        return 1.0 + value / 100.0
    if value < 0:
        return 1.0 + 100.0 / -value
    raise ValueError("una cuota americana no puede ser 0")


def _olivier_odds(raw: dict[str, str], book: str, phase: str) -> dict[str, float] | None:
    """Cuota de local y visitante de una casa (o el promedio) en apertura ("Open") o cierre ("Close")."""
    books = OLIVIER_NBA_BOOKS if book == OLIVIER_AVERAGE else (book,)
    homes: list[float] = []
    aways: list[float] = []
    for b in books:
        home = _float(raw.get(f"{b}_ML_Home_{phase}"))
        away = _float(raw.get(f"{b}_ML_Away_{phase}"))
        if home is None or away is None or home == 0 or away == 0:
            continue
        homes.append(american_to_decimal(home))
        aways.append(american_to_decimal(away))
    if not homes:
        return None
    return {HOME: sum(homes) / len(homes), AWAY: sum(aways) / len(aways)}


def load_olivier_nba(paths: Sequence[Path], book: str = OLIVIER_AVERAGE) -> list[Event]:
    """Lee el CSV de "NBA Opening & Closing Odds" (una fila por partido, cuotas americanas).

    Segun su README: `Game_ID` es `AAAAMMDD_VISITANTE_LOCAL` con la fecha de la
    costa este, `Season` es `2018/2019`, el marcador incluye la prorroga (la
    linea de dinero tambien) y el cierre es el ultimo precio antes del salto.
    """
    if book != OLIVIER_AVERAGE and book not in OLIVIER_NBA_BOOKS:
        raise SystemExit(f"casa desconocida: {book!r}; validas: {OLIVIER_AVERAGE}, {', '.join(OLIVIER_NBA_BOOKS)}")
    events: list[Event] = []
    for path in paths:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for raw in csv.DictReader(fh):
                game_id = raw.get("Game_ID", "")
                if not game_id or not raw.get("Home_Team") or not raw.get("Away_Team"):
                    continue
                events.append(
                    Event(
                        event_id=game_id,
                        competition=raw.get("League") or "NBA",
                        season=(raw.get("Season") or "").replace("/", "-"),
                        date=datetime.strptime(game_id[:8], "%Y%m%d").date(),
                        home=raw["Home_Team"].strip(),
                        away=raw["Away_Team"].strip(),
                        home_score=_int(raw.get("Home_Score")),
                        away_score=_int(raw.get("Away_Score")),
                        closing_odds=_olivier_odds(raw, book, "Close"),
                        opening_odds=_olivier_odds(raw, book, "Open"),
                    )
                )
    return events


def cmd_from_olivier_nba(args: argparse.Namespace) -> int:
    events = load_olivier_nba([Path(p) for p in args.raw], args.book)
    events.sort(key=lambda e: (e.date, e.event_id))
    write_events(Path(args.out), events)
    with_close = sum(1 for e in events if e.closing_odds is not None)
    print(f"{len(events)} partidos en {args.out}; {with_close} con cuota de cierre ({args.book}).")
    return 0


def cmd_from_football_data(args: argparse.Namespace) -> int:
    paths = sorted(Path(p) for p in args.raw)
    events = load_football_data(paths, args.book)
    events.sort(key=lambda e: (e.competition, e.date, e.event_id))
    write_events(Path(args.out), events)
    with_close = sum(1 for e in events if e.closing_odds is not None)
    print(f"{len(events)} partidos de {len(paths)} archivos en {args.out}; {with_close} con cuota de cierre {args.book}C.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.data]
    columns = _read_columns(args.columns)
    exclude = _exclude(args.exclude)
    events = load_events(paths, args.sport, columns, args.date_format)
    splits, skipped = split_seasons(events, exclude)
    if skipped:
        print(f"Sin temporadas suficientes (necesitan 5 terminadas), fuera: {', '.join(skipped)}")
    if not splits:
        print("Ninguna competicion tiene temporadas suficientes.")
        return 1
    for s in splits:
        print(f"{s.competition}: historial {', '.join(s.train)} | validacion {', '.join(s.validation)} | "
              f"prueba {', '.join(s.test)}")  # fmt: skip

    grid = model_grid(args.sport)
    result: ValidationResult = validate(
        events, grid, splits, max_odds=args.max_odds, refit_days=args.refit_days, seed=args.seed
    )
    chosen = grid[result.model_index]
    print("\nMargen: log-loss del mercado en validacion por metodo:",
          {k: round(v, 5) for k, v in result.market_log_loss.items()}, "->", result.margin_method.value)  # fmt: skip
    for i, (model, diff) in enumerate(zip(grid, result.model_log_loss_diff, strict=True)):
        mark = "  <- elegido" if i == result.model_index else ""
        print(f"  {model}: diferencia con el mercado {diff:+.5f}{mark}")
    for e in result.edges:
        print(f"  umbral {e.min_edge:.2f}: {e.recommendations} recomendaciones, ROI {_pct(e.roi)}")
    print(f"Umbral elegido: {result.policy.min_edge:.2f}")
    print_report("Validacion (no decide nada)", result.report)

    config = {
        "sport": args.sport,
        "model": asdict(chosen),  # type: ignore[call-overload]
        "policy": _jsonable(asdict(result.policy)),
        "refit_days": args.refit_days,
        "seed": args.seed,
        "exclude": sorted(f"{c}:{s}" for c, s in exclude),
        "columns": columns,
        "date_format": args.date_format,
        "splits": [asdict(s) for s in splits],
        "data_fingerprint": fingerprint(paths, {"columns": columns, "date_format": args.date_format}),
        "validated_at": datetime.now().isoformat(timespec="seconds"),
    }
    Path(args.config).parent.mkdir(parents=True, exist_ok=True)
    Path(args.config).write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nConfiguracion congelada en {args.config}. La prueba se corre una sola vez con `test`.")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    report_path = Path(args.report)
    if report_path.exists():
        print(f"{report_path} ya existe: la prueba se corre una sola vez (PLATAFORMA_COMPLETA.md 8.5). No se sobrescribe.")
        return 1
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    paths = [Path(p) for p in args.data]
    columns = config["columns"]
    date_format = config["date_format"]
    if fingerprint(paths, {"columns": columns, "date_format": date_format}) != config["data_fingerprint"]:
        print("Los datos no son los que se validaron (la huella no coincide). No se corre la prueba.")
        return 1

    sport = config["sport"]
    events = load_events(paths, sport, columns, date_format)
    splits = [SeasonSplit(s["competition"], tuple(s["train"]), tuple(s["validation"]), tuple(s["test"]))
              for s in config["splits"]]  # fmt: skip
    p = config["policy"]
    policy = Policy(p["min_edge"], MarginMethod(p["margin_method"]), p["max_odds"])
    model = build_model(sport, config["model"])
    report, result = run_test(events, model, policy, splits, config["refit_days"], seed=config["seed"])
    print_report("Prueba (decide)", report)
    print_verdict(result)

    out = {
        "config": config,
        "report": _jsonable(asdict(report)),
        "verdict": _jsonable(asdict(result)),
        "tested_at": datetime.now().isoformat(timespec="seconds"),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nInforme en {report_path}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    syn = sub.add_parser("synthetic", help="liga simulada para probar el backtest")
    syn.add_argument("--sport", choices=SPORTS, required=True)
    syn.add_argument("--out", required=True)
    syn.add_argument("--teams", type=int, default=12)
    syn.add_argument("--seasons", type=int, default=7)
    syn.add_argument("--seed", type=int, default=0)
    syn.add_argument("--margin", type=float, default=0.05)
    syn.add_argument("--uninformed", action="store_true", help="la cuota no sale de la probabilidad verdadera")
    syn.set_defaults(func=cmd_synthetic)

    fd = sub.add_parser("from-football-data", help="convierte los CSV de football-data.co.uk (<liga>_<aaAA>.csv)")
    fd.add_argument("--raw", nargs="+", required=True)
    fd.add_argument("--out", required=True)
    fd.add_argument("--book", default=FOOTBALL_DATA_BOOK, help="casa o mercado de la cuota (Avg, por PLATAFORMA_COMPLETA.md 8.5)")
    fd.set_defaults(func=cmd_from_football_data)

    nba = sub.add_parser("from-olivier-nba", help="convierte el CSV de NBA de Olivier Sports Data")
    nba.add_argument("--raw", nargs="+", required=True)
    nba.add_argument("--out", required=True)
    nba.add_argument("--book", default=OLIVIER_AVERAGE, help="Avg (promedio de las once casas) o una casa")
    nba.set_defaults(func=cmd_from_olivier_nba)

    val = sub.add_parser("validate", help="elige margen, modelo y umbral, y congela la configuracion")
    val.add_argument("--sport", choices=SPORTS, required=True)
    val.add_argument("--data", nargs="+", required=True)
    val.add_argument("--config", required=True)
    val.add_argument("--columns")
    val.add_argument("--date-format")
    val.add_argument("--exclude", nargs="*", default=[], help="COMPETICION:TEMPORADA sin terminar")
    val.add_argument("--max-odds", type=float)
    val.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS)
    val.add_argument("--seed", type=int, default=0)
    val.set_defaults(func=cmd_validate)

    tst = sub.add_parser("test", help="la unica corrida sobre las temporadas de prueba")
    tst.add_argument("--config", required=True)
    tst.add_argument("--data", nargs="+", required=True)
    tst.add_argument("--report", required=True)
    tst.set_defaults(func=cmd_test)

    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
