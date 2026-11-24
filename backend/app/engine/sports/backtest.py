"""Backtest fuera de muestra de deportes y el veredicto de §8.5.

Python puro, sin red ni base: recibe partidos y devuelve metricas. Nada de lo
que calcula se muestra al cliente.

**Lo que hace que sirva de algo** (`PLATAFORMA_COMPLETA.md` §8.5):

1. Por competicion, las dos temporadas mas recientes son de prueba, las dos
   anteriores de validacion y el resto, solo historial (`split_seasons`).
2. Walk-forward: cada partido se estima con un modelo ajustado solo con los
   partidos anteriores a su fecha, de la misma competicion (`walk_forward`).
3. En validacion se eligen el metodo del margen, el modelo de la grilla y el
   umbral `min_edge` (`validate`). En prueba se corre **una sola vez** lo
   congelado (`run_test`), y el veredicto sale de `verdict`.

El mercado contra el que se mide es la cuota de cierre sin margen: la mas
dificil de batir. El ROI se cuenta en unidades, una por recomendacion, a la
cuota de cierre.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app.engine.recommendation import Decision
from app.engine.sports.events import Event, odds_vector
from app.engine.sports.models import Model
from app.engine.sports.odds import MarginMethod, remove_margin
from app.engine.sports.recommendation import Policy, SportsRecommendation, recommend

#: Condiciones de §8.5. Fijadas antes de correr nada: no se cambian despues de
#: ver un resultado de prueba.
N_TEST_SEASONS = 2
N_VALIDATION_SEASONS = 2
MIN_TEST_RECOMMENDATIONS = 300
BOOTSTRAP_SAMPLES = 10_000
CONFIDENCE = 0.95

#: Grilla del umbral y lo minimo para elegir uno en validacion.
DEFAULT_EDGE_GRID: tuple[float, ...] = (0.02, 0.04, 0.06, 0.08, 0.10)
DEFAULT_MIN_EDGE = 0.05
MIN_VALIDATION_RECOMMENDATIONS = 100

#: Cada cuantos dias se reajusta el modelo dentro de una temporada.
DEFAULT_REFIT_DAYS = 7

LOG_FLOOR = 1e-15


# --------------------------------------------------------------------------
# Particion por temporadas
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SeasonSplit:
    competition: str
    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]


def seasons_in_order(events: Sequence[Event]) -> dict[str, list[str]]:
    """Las temporadas de cada competicion, de la mas antigua a la mas reciente."""
    first: dict[tuple[str, str], date] = {}
    for e in events:
        key = (e.competition, e.season)
        if key not in first or e.date < first[key]:
            first[key] = e.date
    by_comp: dict[str, list[tuple[date, str]]] = defaultdict(list)
    for (comp, season), start in first.items():
        by_comp[comp].append((start, season))
    return {comp: [s for _, s in sorted(items)] for comp, items in sorted(by_comp.items())}


def split_seasons(
    events: Sequence[Event],
    exclude: frozenset[tuple[str, str]] = frozenset(),
    n_test: int = N_TEST_SEASONS,
    n_validation: int = N_VALIDATION_SEASONS,
) -> tuple[list[SeasonSplit], list[str]]:
    """La particion de cada competicion y las que no tienen temporadas suficientes.

    `exclude` saca temporadas sin terminar (competicion, temporada): el conjunto
    no sabe que partidos faltan por jugarse, asi que lo dice quien lo carga.
    Una competicion necesita al menos una temporada de historial ademas de las
    de validacion y prueba.
    """
    splits: list[SeasonSplit] = []
    skipped: list[str] = []
    for comp, seasons in seasons_in_order(events).items():
        complete = [s for s in seasons if (comp, s) not in exclude]
        if len(complete) < n_test + n_validation + 1:
            skipped.append(comp)
            continue
        test = tuple(complete[-n_test:])
        validation = tuple(complete[-(n_test + n_validation) : -n_test])
        train = tuple(complete[: -(n_test + n_validation)])
        splits.append(SeasonSplit(comp, train, validation, test))
    return splits, skipped


def validation_seasons(splits: Sequence[SeasonSplit]) -> dict[str, tuple[str, ...]]:
    return {s.competition: s.validation for s in splits}


def holdout_seasons(splits: Sequence[SeasonSplit]) -> dict[str, tuple[str, ...]]:
    return {s.competition: s.test for s in splits}


# --------------------------------------------------------------------------
# Walk-forward
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Estimate:
    event: Event
    model_probs: dict[str, float]
    outcome: str


@dataclass
class WalkForward:
    estimates: list[Estimate] = field(default_factory=list)
    #: Partidos de la fase que no se pudieron medir, por motivo.
    no_estimate: int = 0
    no_odds: int = 0
    no_result: int = 0


def walk_forward(
    events: Sequence[Event],
    model: Model,
    phase_seasons: Mapping[str, Sequence[str]],
    refit_days: int = DEFAULT_REFIT_DAYS,
) -> WalkForward:
    """Estima cada partido de las temporadas pedidas con un modelo que solo vio el pasado.

    El modelo se ajusta con los partidos de la competicion **anteriores a la
    fecha** del partido (los del mismo dia tampoco entran) y se reutiliza
    durante `refit_days`: un partido posterior usa un ajuste mas viejo, nunca
    uno con datos de su propio dia o posteriores.
    """
    outcomes = model.outcomes
    walk = WalkForward()
    for comp, seasons in phase_seasons.items():
        wanted = set(seasons)
        comp_events = sorted((e for e in events if e.competition == comp), key=lambda e: (e.date, e.event_id))
        dates = [e.date for e in comp_events]
        fitted = None
        fit_date = None
        for e in comp_events:
            if e.season not in wanted:
                continue
            result = e.outcome(outcomes)
            if result is None:
                walk.no_result += 1
                continue
            if odds_vector(e.closing_odds, outcomes) is None:
                walk.no_odds += 1
                continue
            if fitted is None or fit_date is None or (e.date - fit_date).days >= refit_days:
                cut = bisect_left(dates, e.date)
                fitted = model.fit(comp_events[:cut], as_of=e.date)
                fit_date = e.date
            probs = fitted.estimate(e.home, e.away)
            if probs is None:
                walk.no_estimate += 1
                continue
            walk.estimates.append(Estimate(e, probs, result))
    walk.estimates.sort(key=lambda s: (s.event.date, s.event.competition, s.event.event_id))
    return walk


# --------------------------------------------------------------------------
# Evaluacion
# --------------------------------------------------------------------------


def log_loss(probs: Sequence[float], index: int) -> float:
    return -math.log(max(probs[index], LOG_FLOOR))


def brier(probs: Sequence[float], index: int) -> float:
    return sum((p - (1.0 if i == index else 0.0)) ** 2 for i, p in enumerate(probs))


def net_units(recommendation: SportsRecommendation, outcome: str) -> float | None:
    """Unidades ganadas con una unidad apostada a lo recomendado; None con NO_BET."""
    if recommendation.decision is not Decision.recommend:
        return None
    best = recommendation.best
    return best.odds - 1.0 if best.outcome == outcome else -1.0


@dataclass(frozen=True)
class Evaluated:
    estimate: Estimate
    market_probs: tuple[float, ...]
    model_log_loss: float
    market_log_loss: float
    model_brier: float
    market_brier: float
    recommendation: SportsRecommendation
    #: Unidades a la cuota de cierre, si se recomendo.
    net: float | None
    #: Lo mismo decidiendo con la cuota de apertura, si el conjunto la trae.
    net_opening: float | None = None
    #: Cuota de apertura / cuota de cierre - 1 de lo recomendado con la de apertura.
    clv: float | None = None


def evaluate(estimates: Sequence[Estimate], outcomes: Sequence[str], policy: Policy) -> list[Evaluated]:
    evaluated: list[Evaluated] = []
    for s in estimates:
        closing = odds_vector(s.event.closing_odds, outcomes)
        if closing is None:  # walk_forward ya los descarta; por si llegan de otro lado
            continue
        index = list(outcomes).index(s.outcome)
        model_vec = [s.model_probs[o] for o in outcomes]
        market = remove_margin(closing, policy.margin_method)
        rec = recommend(s.model_probs, dict(zip(outcomes, closing, strict=True)), outcomes, policy)

        net_opening: float | None = None
        clv: float | None = None
        opening = odds_vector(s.event.opening_odds, outcomes)
        if opening is not None:
            rec_open = recommend(s.model_probs, dict(zip(outcomes, opening, strict=True)), outcomes, policy)
            net_opening = net_units(rec_open, s.outcome)
            if net_opening is not None:
                j = list(outcomes).index(rec_open.best.outcome)
                clv = opening[j] / closing[j] - 1.0

        evaluated.append(
            Evaluated(
                estimate=s,
                market_probs=tuple(market),
                model_log_loss=log_loss(model_vec, index),
                market_log_loss=log_loss(market, index),
                model_brier=brier(model_vec, index),
                market_brier=brier(market, index),
                recommendation=rec,
                net=net_units(rec, s.outcome),
                net_opening=net_opening,
                clv=clv,
            )
        )
    return evaluated


# --------------------------------------------------------------------------
# Informe
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Interval:
    low: float
    high: float


def bootstrap_mean_ci(
    values: Sequence[float],
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = 0,
    confidence: float = CONFIDENCE,
) -> Interval | None:
    """Intervalo bootstrap por percentiles de la media, remuestreando cada valor."""
    n = len(values)
    if n < 2:
        return None
    data = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    means = np.empty(samples)
    chunk = max(1, min(samples, 2_000_000 // n))
    done = 0
    while done < samples:
        size = min(chunk, samples - done)
        idx = rng.integers(0, n, size=(size, n))
        means[done : done + size] = data[idx].mean(axis=1)
        done += size
    tail = (1.0 - confidence) / 2.0
    low, high = np.quantile(means, [tail, 1.0 - tail])
    return Interval(float(low), float(high))


def max_drawdown(nets: Sequence[float]) -> float:
    """Peor caida del acumulado desde un pico previo, en unidades."""
    peak = 0.0
    worst = 0.0
    total = 0.0
    for v in nets:
        total += v
        peak = max(peak, total)
        worst = min(worst, total - peak)
    return abs(worst)


@dataclass(frozen=True)
class CompetitionSummary:
    events: int
    log_loss_diff: float
    recommendations: int
    roi: float | None


@dataclass(frozen=True)
class PhaseReport:
    events: int
    no_estimate: int
    no_odds: int
    no_result: int
    model_log_loss: float
    market_log_loss: float
    #: Media de (log-loss del modelo - log-loss del mercado). Negativa = el modelo describe mejor.
    log_loss_diff: float
    log_loss_diff_ci: Interval | None
    model_brier: float
    market_brier: float
    recommendations: int
    roi: float | None
    roi_ci: Interval | None
    max_drawdown: float
    recommendations_opening: int
    roi_opening: float | None
    mean_clv: float | None
    by_competition: dict[str, CompetitionSummary]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def summarize(
    walk: WalkForward,
    evaluated: Sequence[Evaluated],
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = 0,
) -> PhaseReport:
    diffs = [e.model_log_loss - e.market_log_loss for e in evaluated]
    nets = [e.net for e in evaluated if e.net is not None]
    nets_opening = [e.net_opening for e in evaluated if e.net_opening is not None]
    clvs = [e.clv for e in evaluated if e.clv is not None]

    per_comp: dict[str, list[Evaluated]] = defaultdict(list)
    for e in evaluated:
        per_comp[e.estimate.event.competition].append(e)
    by_competition = {
        comp: CompetitionSummary(
            events=len(items),
            log_loss_diff=_mean([i.model_log_loss - i.market_log_loss for i in items]),
            recommendations=sum(1 for i in items if i.net is not None),
            roi=_mean([i.net for i in items if i.net is not None]) if any(i.net is not None for i in items) else None,
        )
        for comp, items in sorted(per_comp.items())
    }

    return PhaseReport(
        events=len(evaluated),
        no_estimate=walk.no_estimate,
        no_odds=walk.no_odds,
        no_result=walk.no_result,
        model_log_loss=_mean([e.model_log_loss for e in evaluated]),
        market_log_loss=_mean([e.market_log_loss for e in evaluated]),
        log_loss_diff=_mean(diffs),
        log_loss_diff_ci=bootstrap_mean_ci(diffs, samples, seed),
        model_brier=_mean([e.model_brier for e in evaluated]),
        market_brier=_mean([e.market_brier for e in evaluated]),
        recommendations=len(nets),
        # Una unidad por recomendacion: el ROI es la media del resultado neto.
        roi=_mean(nets) if nets else None,
        roi_ci=bootstrap_mean_ci(nets, samples, seed + 1),
        max_drawdown=max_drawdown(nets),
        recommendations_opening=len(nets_opening),
        roi_opening=_mean(nets_opening) if nets_opening else None,
        mean_clv=_mean(clvs) if clvs else None,
        by_competition=by_competition,
    )


# --------------------------------------------------------------------------
# Veredicto (§8.5)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    passed: bool
    primary: bool
    secondary: bool
    reasons: tuple[str, ...]


def verdict(report: PhaseReport, min_recommendations: int = MIN_TEST_RECOMMENDATIONS) -> Verdict:
    """Supera al mercado solo si se cumplen las dos condiciones de §8.5."""
    reasons: list[str] = []

    ci = report.log_loss_diff_ci
    primary = ci is not None and ci.high < 0.0
    if ci is None:
        reasons.append("primaria: no hay partidos suficientes para el intervalo")
    elif not primary:
        reasons.append(
            f"primaria: el intervalo de la diferencia de log-loss [{ci.low:.5f}, {ci.high:.5f}] no queda bajo 0"
        )

    roi_ci = report.roi_ci
    if report.recommendations < min_recommendations:
        secondary = False
        reasons.append(
            f"secundaria: {report.recommendations} recomendaciones, menos de {min_recommendations} (no concluyente)"
        )
    elif roi_ci is None or roi_ci.low <= 0.0:
        secondary = False
        low = "sin intervalo" if roi_ci is None else f"[{roi_ci.low:.4f}, {roi_ci.high:.4f}]"
        reasons.append(f"secundaria: el intervalo del ROI {low} no queda sobre 0")
    else:
        secondary = True

    return Verdict(primary and secondary, primary, secondary, tuple(reasons))


# --------------------------------------------------------------------------
# Validacion y prueba
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeChoice:
    min_edge: float
    recommendations: int
    roi: float | None


@dataclass(frozen=True)
class ValidationResult:
    margin_method: MarginMethod
    #: Log-loss del mercado sin margen en validacion, por metodo.
    market_log_loss: dict[str, float]
    model_index: int
    #: Diferencia media de log-loss contra el mercado, por modelo de la grilla.
    model_log_loss_diff: tuple[float, ...]
    edges: tuple[EdgeChoice, ...]
    policy: Policy
    report: PhaseReport


def market_log_loss(
    events: Sequence[Event],
    outcomes: Sequence[str],
    phase_seasons: Mapping[str, Sequence[str]],
    method: MarginMethod,
) -> float:
    """Log-loss media de la cuota de cierre sin margen en las temporadas pedidas."""
    losses: list[float] = []
    for e in events:
        if e.season not in phase_seasons.get(e.competition, ()):
            continue
        result = e.outcome(outcomes)
        closing = odds_vector(e.closing_odds, outcomes)
        if result is None or closing is None:
            continue
        losses.append(log_loss(remove_margin(closing, method), list(outcomes).index(result)))
    return _mean(losses)


def choose_edge(
    estimates: Sequence[Estimate],
    outcomes: Sequence[str],
    margin_method: MarginMethod,
    edge_grid: Sequence[float],
    max_odds: float | None,
    min_recommendations: int = MIN_VALIDATION_RECOMMENDATIONS,
) -> tuple[float, tuple[EdgeChoice, ...]]:
    """El umbral de mayor ROI en validacion entre los que tienen volumen suficiente.

    Si ninguno llega a `min_recommendations`, queda `DEFAULT_MIN_EDGE`: un ROI
    medido sobre pocas apuestas es ruido.
    """
    choices: list[EdgeChoice] = []
    for edge in edge_grid:
        policy = Policy(edge, margin_method, max_odds)
        nets = [e.net for e in evaluate(estimates, outcomes, policy) if e.net is not None]
        choices.append(EdgeChoice(edge, len(nets), _mean(nets) if nets else None))
    eligible = [c for c in choices if c.recommendations >= min_recommendations and c.roi is not None]
    if not eligible:
        return DEFAULT_MIN_EDGE, tuple(choices)
    best = max(eligible, key=lambda c: (c.roi, c.min_edge))
    return best.min_edge, tuple(choices)


def validate(
    events: Sequence[Event],
    model_grid: Sequence[Model],
    splits: Sequence[SeasonSplit],
    edge_grid: Sequence[float] = DEFAULT_EDGE_GRID,
    max_odds: float | None = None,
    refit_days: int = DEFAULT_REFIT_DAYS,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = 0,
) -> ValidationResult:
    """Elige margen, modelo y umbral mirando solo las temporadas de validacion."""
    if not model_grid:
        raise ValueError("la grilla de modelos esta vacia")
    outcomes = model_grid[0].outcomes
    if any(m.outcomes != outcomes for m in model_grid):
        raise ValueError("todos los modelos de la grilla tienen que ser del mismo deporte")
    phase = validation_seasons(splits)

    # 1. El metodo del margen que mejor describe el cierre: la linea base mas fuerte.
    by_method = {m.value: market_log_loss(events, outcomes, phase, m) for m in MarginMethod}
    method = min(MarginMethod, key=lambda m: (by_method[m.value], m.value))

    # 2. El modelo que mas se acerca (o supera) al mercado, cada uno en sus partidos.
    walks = [walk_forward(events, m, phase, refit_days) for m in model_grid]
    base_policy = Policy(DEFAULT_MIN_EDGE, method, max_odds)
    diffs: list[float] = []
    for walk in walks:
        ev = evaluate(walk.estimates, outcomes, base_policy)
        diffs.append(_mean([e.model_log_loss - e.market_log_loss for e in ev]) if ev else math.inf)
    model_index = min(range(len(model_grid)), key=lambda i: (diffs[i], i))
    walk = walks[model_index]

    # 3. El umbral, con el modelo ya elegido.
    min_edge, edges = choose_edge(walk.estimates, outcomes, method, edge_grid, max_odds)
    policy = Policy(min_edge, method, max_odds)
    report = summarize(walk, evaluate(walk.estimates, outcomes, policy), samples, seed)
    return ValidationResult(method, by_method, model_index, tuple(diffs), edges, policy, report)


def run_test(
    events: Sequence[Event],
    model: Model,
    policy: Policy,
    splits: Sequence[SeasonSplit],
    refit_days: int = DEFAULT_REFIT_DAYS,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = 0,
) -> tuple[PhaseReport, Verdict]:
    """La unica corrida sobre las temporadas de prueba, con todo congelado."""
    walk = walk_forward(events, model, holdout_seasons(splits), refit_days)
    report = summarize(walk, evaluate(walk.estimates, model.outcomes, policy), samples, seed)
    return report, verdict(report)
