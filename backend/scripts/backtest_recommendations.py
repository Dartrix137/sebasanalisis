"""Backtest del motor de recomendacion sobre historiales fuera de calibracion.

Responde la pregunta de §9 del comparativo: *¿el motor aporta informacion util o
solo describe el pasado?* Es una herramienta interna de validacion — nada de lo
que imprime se muestra al cliente.

Uso:

    python -m scripts.backtest_recommendations --variant european --sessions 200
    python -m scripts.backtest_recommendations --file historiales.txt
    python -m scripts.backtest_recommendations --from-db --limit 50

La regla que hace que esto sirva de algo
----------------------------------------
Los pesos del score (`engine/recommendation.py`) se fijaron mirando
**simulaciones de ruedas justas**, no estos historiales. Si alguna vez se
calibran los pesos contra un conjunto de datos, ese conjunto deja de servir para
medir: hay que correr el backtest sobre historiales que el motor no haya visto.
`--from-db` lee sesiones reales de usuarios, que son fuera de muestra por
construccion; `--variant` genera ruedas justas nuevas con una semilla distinta.

Como se lee el resultado
------------------------
Una rueda justa da un ROI de -1/37 (europea) o -2/38 (americana) **haga lo que
haga el motor**. Un ROI cercano a eso es el resultado correcto y esperado, no un
fallo del backtest: significa que el motor no encontro estructura donde no la
hay. Lo que si seria informativo es un ROI sistematicamente mejor que la ventaja
de la casa sobre historiales reales y con volumen — y eso pediria muchisimos mas
giros de los que cabe en una sesion (§2.4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Permite `python scripts/backtest_recommendations.py` ademas de `-m`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.backtest import (  # noqa: E402
    BAND_LABEL,
    WARMUP,
    Report,
    Tally,
    backtest,
    fair_wheel_histories,
)
from app.engine.probability import GameConfig  # noqa: E402
from app.engine.recommendation import SignalBand, weak_threshold_for  # noqa: E402

SEED_DATA = Path(__file__).resolve().parents[1] / "app" / "db" / "seed_data"


# --------------------------------------------------------------------------
# Fuentes de historiales
# --------------------------------------------------------------------------


def histories_from_file(path: Path) -> list[list[str]]:
    """Un historial por linea, valores separados por coma o espacio."""
    historiales = []
    for linea in path.read_text(encoding="utf-8").splitlines():
        valores = [v for v in linea.replace(",", " ").split() if v]
        if valores:
            historiales.append(valores)
    return historiales


def histories_from_db(limit: int, variant_name: str | None) -> tuple[GameConfig, list[list[str]]]:
    """Sesiones reales de usuarios: fuera de muestra por construccion.

    Se importa SQLAlchemy aqui dentro y no arriba para que el resto del script
    siga corriendo sin base de datos.
    """
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import GameSession, GameVariant, Spin

    with SessionLocal() as db:
        stmt = select(GameVariant)
        if variant_name:
            stmt = stmt.where(GameVariant.name == variant_name)
        variant = db.scalars(stmt).first()
        if variant is None:
            raise SystemExit("No hay ninguna variante que coincida en la base")
        config = GameConfig.from_dict(variant.categories_json)

        sesiones = db.scalars(
            select(GameSession.id)
            .where(GameSession.game_variant_id == variant.id)
            .limit(limit)
        ).all()

        historiales = []
        for sid in sesiones:
            giros = list(
                db.scalars(
                    select(Spin.result_value)
                    .where(Spin.session_id == sid)
                    .order_by(Spin.spin_index.asc())
                )
            )
            if len(giros) > WARMUP:
                historiales.append(giros)

    return config, historiales


def load_seed_config(nombre: str) -> GameConfig:
    ruta = SEED_DATA / f"roulette_{nombre}.json"
    if not ruta.exists():
        raise SystemExit(f"No existe {ruta}")
    return GameConfig.from_dict(json.loads(ruta.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------
# Salida
# --------------------------------------------------------------------------


def _fmt_tally(nombre: str, t: Tally) -> str:
    if t.recommendations == 0:
        return f"  {nombre:<12} {'—':>8}  (ninguna recomendacion en esta banda)"
    return (
        f"  {nombre:<12} {t.recommendations:>8}  "
        f"aciertos {t.hits:>6}  fallos {t.misses:>6}  "
        f"coincidencia {t.hit_rate:>6.1%}  "
        f"ROI {t.roi:>+7.3f}  "
        f"unidades {t.units:>+9.1f}  "
        f"caida max {t.max_drawdown:>8.1f}"
    )


def print_report(
    informe: Report, config: GameConfig, threshold: float, weak_threshold: float
) -> None:
    ventaja = -1 / len(config.possible_outcomes)
    print()
    print("=" * 96)
    print("BACKTEST DEL MOTOR DE RECOMENDACION — metrica interna, no visible al cliente")
    print("=" * 96)
    print(f"  Giros evaluados        {informe.spins_evaluated:>8}")
    print(f"  Decisiones             {informe.decisions:>8}")
    print(f"  Recomendaciones        {informe.overall.recommendations:>8}")
    print(f"  NO APOSTAR             {informe.no_bets:>8}  ({informe.no_bet_rate:.1%})")
    print(f"  Umbral debil           {weak_threshold:>8.0f}")
    print(f"  Umbral medio           {threshold:>8.0f}")
    print()
    print("  TOTAL")
    print(_fmt_tally("todas", informe.overall))
    print()
    print("  POR BANDA DE SEÑAL")
    for banda in SignalBand:
        print(_fmt_tally(BAND_LABEL[banda], informe.by_band[banda]))
    print()
    print("  NO APOSTAR, por banda del mejor candidato")
    for banda in SignalBand:
        print(f"    {BAND_LABEL[banda]:<12} {informe.no_bet_by_band[banda]:>8}")
    print()
    print(
        f"  Referencia: en una mesa sin sesgo el ROI de CUALQUIER apuesta es "
        f"{ventaja:+.4f}."
    )
    print(
        "  Un ROI cercano a esa cifra es el resultado esperado, no un fallo: "
        "significa que"
    )
    print(
        "  el motor no encontro estructura donde no la hay. Ninguna progresion "
        "ni ningun"
    )
    print("  umbral cambia esa ventaja.")
    print("=" * 96)
    print()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--variant", default="european", help="european | american")
    p.add_argument("--sessions", type=int, default=100)
    p.add_argument("--spins", type=int, default=150)
    p.add_argument(
        "--seed",
        type=int,
        default=90_217,
        help="Semilla del generador. Distinta a la de calibracion a proposito.",
    )
    p.add_argument("--threshold", type=float, default=None, help="Umbral medio")
    p.add_argument("--weak-threshold", type=float, default=None, help="Umbral debil")
    p.add_argument("--window-size", type=int, default=50)
    p.add_argument("--file", type=Path, help="Historiales reales, uno por linea")
    p.add_argument("--from-db", action="store_true", help="Sesiones reales de la base")
    p.add_argument("--limit", type=int, default=50, help="Sesiones a leer con --from-db")
    args = p.parse_args()

    if args.from_db:
        config, historiales = histories_from_db(args.limit, None)
        origen = f"{len(historiales)} sesiones reales de la base"
    elif args.file:
        config = load_seed_config(args.variant)
        historiales = histories_from_file(args.file)
        origen = f"{len(historiales)} historiales de {args.file}"
    else:
        config = load_seed_config(args.variant)
        historiales = fair_wheel_histories(
            config, args.sessions, args.spins, args.seed
        )
        origen = (
            f"{args.sessions} ruedas justas simuladas de {args.spins} giros "
            f"(semilla {args.seed})"
        )

    if not historiales:
        raise SystemExit("No hay historiales que evaluar")

    umbral = (
        args.threshold if args.threshold is not None else config.recommendation_threshold
    )
    umbral_debil = weak_threshold_for(
        args.weak_threshold if args.weak_threshold is not None else config.weak_threshold,
        umbral,
    )
    print(f"\nFuente: {origen}")
    informe = backtest(
        config,
        historiales,
        threshold=umbral,
        weak_threshold=umbral_debil,
        window_size=args.window_size,
    )
    print_report(informe, config, umbral, umbral_debil)


if __name__ == "__main__":
    main()
