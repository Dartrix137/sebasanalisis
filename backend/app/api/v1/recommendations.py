"""Motor de recomendacion: que apostar en el giro siguiente (§2.10).

Esta capa solo traduce y persiste: carga los giros, llama al motor puro de
`engine/recommendation.py` y mapea el resultado a los schemas. Ninguna formula
vive aqui.

A diferencia de `suggestions.py`, que recalcula todo en cada llamada, aqui **si
se guarda**: `outcome` y `resolved_spin_id` son hechos del pasado que no se
pueden re-simular. Dependen de que recomendo el motor con la formula vigente en
ese momento, no con la de hoy, y esa es justamente la comparacion que el
backtest necesita poder hacer.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.v1.sessions import get_owned_session
from app.engine import bankroll as bk
from app.engine.probability import GameConfig, expected_value
from app.engine.recommendation import (
    MIN_SPINS_FOR_SIGNAL,
    Decision,
    Market,
    Recommendation,
    ScoredMarket,
    no_bet_reason,
    recommend,
    resolve,
    strong_threshold_for,
)
from app.models import GameSession, GameVariant, Spin, StatisticalSuggestion
from app.schemas.suggestions import (
    MarketResponse,
    MarketStakeResponse,
    RecommendationRecord,
    RecommendationResponse,
    ScoreComponentsResponse,
    ScoredMarketResponse,
    WindowStatResponse,
)

router = APIRouter(prefix="/sessions", tags=["recommendations"])

#: Linea fija al pie de la tarjeta. Es el unico recordatorio que queda en la
#: pantalla de ruleta desde la Fase 3: el banner fijo de §0 se retiro porque el
#: caracter estadistico del producto esta cubierto en los terminos y
#: condiciones (decision de producto del 2026-09-22).
RECOMMENDATION_DISCLAIMER = (
    "Recomendación generada a partir del análisis estadístico de los resultados "
    "registrados. No es una predicción."
)

#: Moneda de los montos persistidos. Unica por ahora; viaja explicita en cada
#: fila para que un cambio futuro no reinterprete los centavos ya guardados.
CURRENCY = "COP"


# --------------------------------------------------------------------------
# Carga de contexto
# --------------------------------------------------------------------------


def load_config(db: DbSession, session: GameSession) -> GameConfig:
    variant = db.get(GameVariant, session.game_variant_id)
    return GameConfig.from_dict(variant.categories_json)


def load_spins(db: DbSession, session: GameSession) -> list[str]:
    """Giros de la sesion en orden cronologico ascendente, como espera el motor."""
    return list(
        db.scalars(
            select(Spin.result_value)
            .where(Spin.session_id == session.id)
            .order_by(Spin.spin_index.asc())
        )
    )


def build_recommendation(
    config: GameConfig, session: GameSession, historial: list[str]
) -> Recommendation:
    """La recomendacion para el giro siguiente.

    La ventana de recencia y el historial completo van por separado: el
    chi-cuadrado pierde entero cada giro que se le recorte (§2.4), mientras que
    a las señales ponderadas recortar no les cuesta casi nada (§2.3).
    """
    ventana = historial[-session.window_size :]
    return recommend(config, ventana, full_history=historial)


def current_stages(session: GameSession) -> dict[bk.Strategy, int]:
    """Escalon de cada progresion. La plana no tiene: siempre esta en 0."""
    return {
        bk.Strategy.flat: 0,
        bk.Strategy.martingale: session.stage_martingale,
        bk.Strategy.two_sector_recovery: session.stage_two_sector,
    }


def apply_stages(session: GameSession, stages: dict[bk.Strategy, int]) -> None:
    session.stage_martingale = stages[bk.Strategy.martingale]
    session.stage_two_sector = stages[bk.Strategy.two_sector_recovery]


# --------------------------------------------------------------------------
# Persistencia y resolucion
# --------------------------------------------------------------------------


def _to_cents(amount: float) -> int:
    """Pesos a centavos. Dinero en enteros, nunca float."""
    return int(round(amount * 100))


def pending_recommendation(
    db: DbSession, session_id: UUID
) -> StatisticalSuggestion | None:
    """La ultima recomendacion emitida que todavia no se resolvio."""
    return db.scalar(
        select(StatisticalSuggestion)
        .where(
            StatisticalSuggestion.session_id == session_id,
            StatisticalSuggestion.outcome == "PENDING",
            StatisticalSuggestion.decision == Decision.recommend.value,
        )
        .order_by(StatisticalSuggestion.created_at.desc())
        .limit(1)
    )


def resolve_pending_recommendation(
    db: DbSession,
    session: GameSession,
    config: GameConfig,
    spin: Spin,
    followed: frozenset[bk.Strategy],
) -> StatisticalSuggestion | None:
    """Marca la recomendacion anterior contra el giro que acaba de entrar y mueve
    las progresiones con las que se aposto (`followed`).

    La recomendacion se resuelve siempre, se haya apostado o no: el backtest
    mide al motor, no al usuario. Los escalones, en cambio, solo se mueven para
    las gestiones que el usuario siguio de verdad en este giro.

    Un NO APOSTAR no llega aqui: se guarda con `outcome='PENDING'` y se queda
    asi, y ninguna progresion avanza.
    """
    pendiente = pending_recommendation(db, session.id)
    if pendiente is None:
        return None

    from app.engine.recommendation import market_for_key

    market = market_for_key(config, pendiente.market_key)
    if market is None:
        # El admin cambio la configuracion de la variante y el mercado ya no
        # existe. No se inventa un resultado: la recomendacion queda sin
        # resolver y no mueve ninguna progresion.
        return None

    outcome = resolve(market, spin.result_value)
    pendiente.outcome = outcome.value
    pendiente.resolved_spin_id = spin.id

    apply_stages(
        session,
        bk.advance_stages_on_outcome(
            current_stages(session),
            hit=outcome.value == "HIT",
            sectors=market.sectors,
            followed=followed,
        ),
    )
    return pendiente


def persist_recommendation(
    db: DbSession,
    session: GameSession,
    resultado: Recommendation,
    last_spin: Spin | None,
    stake: float | None,
) -> StatisticalSuggestion | None:
    """Guarda la recomendacion emitida.

    Se guarda tambien el NO APOSTAR, con los datos del mejor candidato: siempre
    hay uno, solo que por debajo del umbral. Sin esa fila el backtest no podria
    comparar los giros en los que el motor hablo con los que callo, que es la
    mitad de lo que §9 del comparativo pide medir.
    """
    mejor = resultado.best
    if mejor is None:
        return None

    ventana = mejor.windows[-1] if mejor.windows else None
    fila = StatisticalSuggestion(
        session_id=session.id,
        spin_id=last_spin.id if last_spin is not None else None,
        decision=resultado.decision.value,
        market_key=mejor.market.key,
        category=mejor.market.category_id,
        option_label=mejor.market.label,
        signal_score=mejor.signal_score,
        signal_band=mejor.signal_band.value,
        theoretical_probability=ventana.theoretical_probability if ventana else 0.0,
        observed_frequency_shrunk=ventana.observed_frequency_shrunk if ventana else 0.0,
        deviation=ventana.deviation if ventana else 0.0,
        observed_ci_low=ventana.observed_ci_low if ventana else 0.0,
        observed_ci_high=ventana.observed_ci_high if ventana else 1.0,
        ev=expected_value(
            ventana.observed_frequency_shrunk if ventana else 0.0, mejor.market.payout
        ),
        chi_square_pvalue_adjusted=mejor.chi_square_pvalue_adjusted,
        stake_cents=(
            _to_cents(stake)
            if stake is not None and resultado.decision is Decision.recommend
            else None
        ),
        currency=CURRENCY,
        outcome="PENDING",
        window_size_used=session.window_size,
    )
    db.add(fila)
    return fila


# --------------------------------------------------------------------------
# Mapeo a schemas
# --------------------------------------------------------------------------


def _market_response(market: Market) -> MarketResponse:
    return MarketResponse(
        key=market.key,
        label=market.label,
        category_id=market.category_id,
        group_ids=list(market.group_ids),
        sectors=market.sectors,
        coverage=market.coverage,
        payout=market.payout,
    )


def _scored_response(scored: ScoredMarket) -> ScoredMarketResponse:
    c = scored.components
    return ScoredMarketResponse(
        market=_market_response(scored.market),
        signal_score=scored.signal_score,
        signal_band=scored.signal_band.value,
        components=ScoreComponentsResponse(
            deviation=c.deviation,
            recency=c.recency,
            consistency=c.consistency,
            weight_deviation=c.weight_deviation,
            weight_recency=c.weight_recency,
            weight_consistency=c.weight_consistency,
            chi_square_bonus=c.chi_square_bonus,
        ),
        windows=[
            WindowStatResponse(
                window=w.window,
                spins_used=w.spins_used,
                theoretical_probability=w.theoretical_probability,
                observed_frequency_shrunk=w.observed_frequency_shrunk,
                raw_count=w.raw_count,
                observed_ci_low=w.observed_ci_low,
                observed_ci_high=w.observed_ci_high,
                deviation=w.deviation,
                z=w.z,
            )
            for w in scored.windows
        ],
        chi_square_pvalue_adjusted=scored.chi_square_pvalue_adjusted,
    )


def _stake_response(stake: bk.MarketStake) -> MarketStakeResponse:
    return MarketStakeResponse(
        strategy=stake.strategy.value,
        applicable=stake.applicable,
        reason=stake.reason,
        stage=stake.stage,
        bet_per_sector=stake.bet_per_sector,
        total_bet=stake.total_bet,
        sectors=stake.sectors,
        cumulative_risked=stake.cumulative_risked,
        net_result_if_won=stake.net_result_if_won,
        recovers_only_to_break_even=stake.recovers_only_to_break_even,
        exceeds_bankroll=stake.exceeds_bankroll,
        exceeds_table_limit=stake.exceeds_table_limit,
    )


def stakes_for(
    session: GameSession, resultado: Recommendation
) -> list[bk.MarketStake]:
    """Las tres progresiones sobre el mercado recomendado.

    Vacio con NO APOSTAR: no hay mercado, asi que no hay monto que calcular ni
    escalon que mover.
    """
    market = resultado.market
    if market is None:
        return []
    return bk.stakes_for_market(
        float(session.base_bet),
        current_stages(session),
        sectors=market.sectors,
        payout=market.payout,
        bankroll_current=float(session.bankroll_current),
        table_limit=float(session.table_limit),
    )


def to_response(
    session: GameSession,
    resultado: Recommendation,
    stakes: list[bk.MarketStake],
    total_spins: int,
) -> RecommendationResponse:
    motivo = no_bet_reason(resultado.decision, total_spins)
    return RecommendationResponse(
        session_id=session.id,
        decision=resultado.decision.value,
        no_bet_reason=motivo.value if motivo is not None else None,
        min_spins_for_signal=MIN_SPINS_FOR_SIGNAL,
        threshold=resultado.threshold,
        strong_threshold=strong_threshold_for(resultado.threshold),
        signal_score=resultado.signal_score,
        signal_band=resultado.signal_band.value,
        market=_market_response(resultado.market) if resultado.market else None,
        best=_scored_response(resultado.best) if resultado.best else None,
        stakes=[_stake_response(s) for s in stakes],
        candidates=[_scored_response(c) for c in resultado.candidates],
        window_size_used=session.window_size,
        total_spins=total_spins,
        disclaimer=RECOMMENDATION_DISCLAIMER,
    )


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@router.get("/{session_id}/recommendation", response_model=RecommendationResponse)
def latest_recommendation(
    session_id: UUID, db: DbSession, user: CurrentUser
) -> RecommendationResponse:
    """La recomendacion vigente para el giro siguiente.

    Se recalcula en cada llamada a partir de los giros: el motor es
    determinista, asi que leerla o recalcularla da lo mismo, y recalcular evita
    servir una recomendacion vieja si entretanto se deshizo un giro.
    """
    session = get_owned_session(db, user.id, session_id)
    config = load_config(db, session)
    historial = load_spins(db, session)
    resultado = build_recommendation(config, session, historial)
    return to_response(session, resultado, stakes_for(session, resultado), len(historial))


@router.get(
    "/{session_id}/recommendation/history", response_model=list[RecommendationRecord]
)
def recommendation_history(
    session_id: UUID, db: DbSession, user: CurrentUser
) -> list[StatisticalSuggestion]:
    """Las recomendaciones emitidas en la sesion y como cerro cada una.

    Es el historico real, no una re-simulacion: cada fila guarda lo que el motor
    dijo en su momento.
    """
    session = get_owned_session(db, user.id, session_id)
    return list(
        db.scalars(
            select(StatisticalSuggestion)
            .where(StatisticalSuggestion.session_id == session.id)
            .order_by(StatisticalSuggestion.created_at.asc())
        )
    )
