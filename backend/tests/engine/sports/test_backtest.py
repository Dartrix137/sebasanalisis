"""Tests del backtest de deportes y del veredicto de §8.5.

El backtest decide si deportes sale o no. Si sus cuentas o su particion estan
mal, un modelo sin valor pasaria por bueno: por eso se prueba sin fuga de datos,
con valores a mano y sobre ligas simuladas donde se sabe la respuesta.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import pytest

from app.engine.sports.backtest import (
    Interval,
    PhaseReport,
    bootstrap_mean_ci,
    brier,
    holdout_seasons,
    log_loss,
    max_drawdown,
    run_test,
    split_seasons,
    validate,
    verdict,
    walk_forward,
)
from app.engine.sports.events import AWAY, HOME, HOME_AWAY, Event
from app.engine.sports.models.dixon_coles import DixonColes
from app.engine.sports.models.elo import Elo
from app.engine.sports.synthetic import SyntheticMarket, football_league, two_way_league

# --------------------------------------------------------------------------
# Particion
# --------------------------------------------------------------------------


def _temporadas(comp: str, n: int) -> list[Event]:
    return [
        Event(f"{comp}{s}", comp, f"T{s}", date(2010 + s, 9, 1), "A", "B", 1, 0, {HOME: 2.0, AWAY: 2.0})
        for s in range(n)
    ]


def test_dos_de_prueba_dos_de_validacion_y_el_resto_historial() -> None:
    splits, skipped = split_seasons(_temporadas("L", 6))
    assert skipped == []
    assert splits[0].train == ("T0", "T1")
    assert splits[0].validation == ("T2", "T3")
    assert splits[0].test == ("T4", "T5")


def test_una_competicion_sin_temporadas_suficientes_queda_fuera() -> None:
    splits, skipped = split_seasons(_temporadas("L", 6) + _temporadas("M", 4))
    assert [s.competition for s in splits] == ["L"]
    assert skipped == ["M"]


def test_una_temporada_sin_terminar_se_excluye() -> None:
    splits, _ = split_seasons(_temporadas("L", 6), exclude=frozenset({("L", "T5")}))
    assert splits[0].test == ("T3", "T4")


# --------------------------------------------------------------------------
# Walk-forward sin fuga
# --------------------------------------------------------------------------


@dataclass
class _Espia:
    """Modelo que anota con que partidos lo ajustaron."""

    llamadas: list[tuple[date, list[Event]]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "espia"

    @property
    def outcomes(self) -> tuple[str, ...]:
        return HOME_AWAY

    def fit(self, history: Sequence[Event], as_of: date) -> "_Ajuste":
        self.llamadas.append((as_of, list(history)))
        return _Ajuste()


class _Ajuste:
    def estimate(self, home: str, away: str) -> dict[str, float] | None:
        return {HOME: 0.5, AWAY: 0.5}


def test_el_modelo_solo_ve_partidos_anteriores_a_la_fecha_que_estima() -> None:
    liga = two_way_league(n_teams=6, n_seasons=5, seed=2)
    splits, _ = split_seasons(liga)
    espia = _Espia()
    walk = walk_forward(liga, espia, holdout_seasons(splits), refit_days=1)
    assert walk.estimates
    for as_of, historia in espia.llamadas:
        assert historia, "el ajuste tiene que tener historial"
        assert max(e.date for e in historia) < as_of
    # Cada partido estimado se estimo con un ajuste de su fecha o anterior.
    fechas_de_ajuste = sorted(a for a, _ in espia.llamadas)
    for s in walk.estimates:
        assert any(f <= s.event.date for f in fechas_de_ajuste)


def test_se_reajusta_cada_refit_days() -> None:
    liga = two_way_league(n_teams=6, n_seasons=5, seed=2)
    splits, _ = split_seasons(liga)
    diario, semanal = _Espia(), _Espia()
    walk_forward(liga, diario, holdout_seasons(splits), refit_days=1)
    walk_forward(liga, semanal, holdout_seasons(splits), refit_days=7)
    assert len(semanal.llamadas) < len(diario.llamadas)


def test_partidos_sin_cuota_o_sin_resultado_se_cuentan_aparte() -> None:
    base = _temporadas("L", 5)
    sin_cuota = Event("x1", "L", "T4", date(2014, 9, 2), "A", "B", 1, 0, None)
    sin_resultado = Event("x2", "L", "T4", date(2014, 9, 3), "A", "B", None, None, {HOME: 2.0, AWAY: 2.0})
    splits, _ = split_seasons(base)
    walk = walk_forward([*base, sin_cuota, sin_resultado], _Espia(), holdout_seasons(splits))
    assert walk.no_odds == 1
    assert walk.no_result == 1


# --------------------------------------------------------------------------
# Cuentas
# --------------------------------------------------------------------------


def test_log_loss_y_brier_a_mano() -> None:
    # -ln(0.5) = 0.693147; Brier (0.5-1)^2 + 0.3^2 + 0.2^2 = 0.25 + 0.09 + 0.04 = 0.38.
    assert log_loss([0.5, 0.3, 0.2], 0) == pytest.approx(0.693147, abs=1e-6)
    assert brier([0.5, 0.3, 0.2], 0) == pytest.approx(0.38)


def test_caida_maxima_a_mano() -> None:
    # Acumulado 1, 3, 2, -1, 0: pico 3, peor punto -1 -> caida 4.
    assert max_drawdown([1, 2, -1, -3, 1]) == pytest.approx(4.0)
    assert max_drawdown([]) == 0.0


def test_bootstrap_contiene_la_media_y_es_reproducible() -> None:
    valores = [0.1, -0.2, 0.3, 0.05, -0.1, 0.2, 0.0, 0.15]
    ci = bootstrap_mean_ci(valores, samples=2000, seed=7)
    assert ci is not None
    media = sum(valores) / len(valores)
    assert ci.low < media < ci.high
    assert bootstrap_mean_ci(valores, samples=2000, seed=7) == ci
    assert bootstrap_mean_ci([1.0], samples=100) is None


# --------------------------------------------------------------------------
# Veredicto
# --------------------------------------------------------------------------


def _informe(ll_ci: Interval | None, recs: int, roi_ci: Interval | None) -> PhaseReport:
    return PhaseReport(
        events=1000, no_estimate=0, no_odds=0, no_result=0,
        model_log_loss=1.0, market_log_loss=1.0, log_loss_diff=0.0, log_loss_diff_ci=ll_ci,
        model_brier=0.6, market_brier=0.6, recommendations=recs, roi=0.0, roi_ci=roi_ci,
        max_drawdown=0.0, recommendations_opening=0, roi_opening=None, mean_clv=None, by_competition={},
    )  # fmt: skip


def test_veredicto_pasa_solo_con_las_dos_condiciones() -> None:
    assert verdict(_informe(Interval(-0.02, -0.001), 400, Interval(0.01, 0.08))).passed


@pytest.mark.parametrize(
    ("ll_ci", "recs", "roi_ci", "primaria", "secundaria"),
    [
        # El intervalo de log-loss toca el 0: no describe mejor que el mercado.
        (Interval(-0.02, 0.0), 400, Interval(0.01, 0.08), False, True),
        # Pocas recomendaciones: no concluyente, cuenta como no superar.
        (Interval(-0.02, -0.001), 299, Interval(0.01, 0.08), True, False),
        # El ROI puede ser negativo.
        (Interval(-0.02, -0.001), 400, Interval(-0.01, 0.08), True, False),
        (None, 400, None, False, False),
    ],
)
def test_veredicto_falla(
    ll_ci: Interval | None, recs: int, roi_ci: Interval | None, primaria: bool, secundaria: bool
) -> None:
    v = verdict(_informe(ll_ci, recs, roi_ci))
    assert not v.passed
    assert v.primary is primaria
    assert v.secondary is secundaria
    assert v.reasons


# --------------------------------------------------------------------------
# De punta a punta, sobre ligas simuladas
# --------------------------------------------------------------------------


def test_contra_un_mercado_informado_el_modelo_no_pasa() -> None:
    """Si la cuota sale de la probabilidad verdadera, nada la supera: el veredicto falla."""
    liga = football_league(n_teams=8, n_seasons=6, seed=5, market=SyntheticMarket(margin=0.05, informed=True))
    splits, _ = split_seasons(liga)
    grilla = [DixonColes(xi=0.0), DixonColes(xi=0.002)]
    val = validate(liga, grilla, splits, samples=1000)
    informe, veredicto = run_test(liga, grilla[val.model_index], val.policy, splits, samples=1000)
    assert informe.events > 0
    assert not veredicto.passed
    assert not veredicto.primary


def test_contra_un_mercado_desinformado_el_modelo_describe_mejor() -> None:
    """Si la cuota es la misma para todos los partidos, un modelo con informacion la mejora."""
    liga = two_way_league(n_teams=8, n_seasons=6, seed=9, market=SyntheticMarket(margin=0.04, informed=False))
    splits, _ = split_seasons(liga)
    grilla = [Elo(k=20, home_advantage=30), Elo(k=30, home_advantage=30)]
    val = validate(liga, grilla, splits, samples=1000)
    informe, veredicto = run_test(liga, grilla[val.model_index], val.policy, splits, samples=1000)
    assert informe.log_loss_diff < 0
    assert veredicto.primary


def test_validacion_elige_el_margen_y_congela_la_politica() -> None:
    liga = football_league(n_teams=8, n_seasons=6, seed=5)
    splits, _ = split_seasons(liga)
    val = validate(liga, [DixonColes()], splits, samples=500)
    assert set(val.market_log_loss) == {"proportional", "shin"}
    assert val.policy.margin_method.value == min(val.market_log_loss, key=lambda k: val.market_log_loss[k])
    assert val.policy.min_edge in {c.min_edge for c in val.edges} | {0.05}


def test_la_fecha_de_corte_es_estricta() -> None:
    """Un partido el mismo dia que el estimado no entra en su ajuste."""
    dia = date(2020, 5, 1)
    liga = _temporadas("L", 5)
    mismo_dia = Event("hoy", "L", "T4", dia, "A", "B", 9, 0, {HOME: 2.0, AWAY: 2.0})
    otro = Event("hoy2", "L", "T4", dia, "B", "A", 0, 9, {HOME: 2.0, AWAY: 2.0})
    espia = _Espia()
    walk_forward([*liga, mismo_dia, otro], espia, {"L": ("T4",)}, refit_days=1)
    for as_of, historia in espia.llamadas:
        assert all(e.date < as_of for e in historia)
        if as_of == dia:
            assert all(e.event_id not in {"hoy", "hoy2"} for e in historia)
