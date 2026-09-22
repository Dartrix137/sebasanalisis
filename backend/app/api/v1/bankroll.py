"""Gestion de banca de una sesion (§2.8).

Esta capa solo traduce: lee el estado de la sesion, llama al motor puro de
`engine/bankroll.py` y mapea el resultado a los schemas. Ninguna formula de
progresion vive aqui.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.api.v1.sessions import get_owned_session
from app.engine import bankroll as engine
from app.models import GameVariant
from app.schemas.sessions import BankrollStrategy
from app.schemas.suggestions import (
    BankrollAlertLevel,
    BankrollAlertResponse,
    BankrollSuggestionResponse,
    EligibleBetResponse,
    NextStepResponse,
    ProgressionRowResponse,
    ProgressionTableResponse,
)

router = APIRouter(tags=["bankroll"])

#: Tope de escalones que se pueden pedir en una tabla de progresion. Mas alla
#: de esto los montos dejan de ser informativos y solo cargan la respuesta.
MAX_PROGRESSION_STAGES = 20


def _stage_for(session, strategy: engine.Strategy) -> int:
    """Escalon de esa progresion en la sesion.

    Desde la Fase 3 no hay un escalon unico: las tres progresiones corren a la
    vez y cada una lleva el suyo (§2.10). La plana no tiene escalon porque no
    tiene progresion.
    """
    if strategy is engine.Strategy.martingale:
        return session.stage_martingale
    if strategy is engine.Strategy.two_sector_recovery:
        return session.stage_two_sector
    return 0


#: La progresion sobre la que responden los endpoints de banca cuando el cliente
#: no pide una. La plana es la lectura mas conservadora: no escala nada.
DEFAULT_STRATEGY = BankrollStrategy.flat

STRATEGY_QUERY = Query(
    default=DEFAULT_STRATEGY,
    description=(
        "Progresion sobre la que calcular. La mesa muestra las tres a la vez "
        "(§2.10), asi que el cliente pide la que quiere ver."
    ),
)


def _to_engine_strategy(strategy: BankrollStrategy) -> engine.Strategy:
    """Los valores de ambos enums coinciden carater por caracter a proposito."""
    return engine.Strategy(strategy.value)


def _to_next_step(step: engine.NextStep) -> NextStepResponse:
    return NextStepResponse(
        stage=step.stage,
        bet_per_sector=step.bet_per_sector,
        suggested_bet=step.suggested_bet,
        bankroll_after=step.bankroll_after,
        exceeds_table_limit=step.exceeds_table_limit,
        exceeds_bankroll=step.exceeds_bankroll,
        reaches_loss_limit=step.reaches_loss_limit,
    )


def _to_advice_response(
    advice: engine.BankrollAdvice, plan: engine.BankrollPlan, base_bet: float
) -> BankrollSuggestionResponse:
    neto = engine.net_result_if_won(advice.strategy, base_bet, advice.stage)
    return BankrollSuggestionResponse(
        strategy=BankrollStrategy(advice.strategy.value),
        suggested_bet=advice.suggested_bet,
        bet_per_sector=advice.bet_per_sector,
        sectors=advice.sectors,
        stage=advice.stage,
        cumulative_risked=advice.cumulative_risked,
        net_result_if_won=neto,
        recovers_only_to_break_even=neto == 0.0,
        exceeds_table_limit=advice.exceeds_table_limit,
        exceeds_bankroll=advice.exceeds_bankroll,
        risk_warning=advice.risk_warning,
        ruin_probability_estimate=advice.ruin_probability_estimate,
        disclaimer=engine.BANKROLL_DISCLAIMER,
        next_if_lost=_to_next_step(plan.if_lost),
        next_if_won=_to_next_step(plan.if_won),
        stages_supported=plan.stages_supported,
        alerts=[
            BankrollAlertResponse(
                code=a.code, level=BankrollAlertLevel(a.level.value), message=a.message
            )
            for a in plan.alerts
        ],
    )


def _load_config(db: DbSession, variant_id: UUID) -> engine.GameConfig:
    variant = db.get(GameVariant, variant_id)
    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Variante no encontrada"
        )
    return engine.GameConfig.from_dict(variant.categories_json)


def _probability_for_bet(
    config: engine.GameConfig, mode: engine.StrategyMode, bet_id: str | None
) -> float | None:
    """Probabilidad teorica de la apuesta elegida, calculada por el motor.

    Devuelve None cuando no se eligio ninguna: sin saber sobre que apuesta se
    juega, el riesgo de agotar la banca no se puede estimar, y es preferible no
    mostrarlo antes que mostrar un numero inventado.
    """
    if bet_id is None:
        return None
    for apuesta in engine.eligible_bets(config, mode):
        if apuesta.id == bet_id:
            return apuesta.theoretical_probability
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"La apuesta '{bet_id}' no es compatible con el modo '{mode.value}'",
    )


def _build_table(
    strategy: engine.Strategy,
    base_bet: float,
    stages: int,
    table_limit: float | None,
    bankroll: float,
    win_probability: float | None,
) -> ProgressionTableResponse:
    rows = engine.progression_table(
        strategy,
        base_bet,
        stages=stages,
        table_limit=table_limit,
        bankroll=bankroll,
    )
    ruin = (
        engine.ruin_probability_estimate(
            strategy, base_bet, bankroll, win_probability, table_limit
        )
        if win_probability is not None
        else None
    )
    return ProgressionTableResponse(
        strategy=BankrollStrategy(strategy.value),
        base_bet=base_bet,
        sectors=engine.sectors_covered(strategy),
        rows=[
            ProgressionRowResponse(
                stage=r.stage,
                bet_per_sector=r.bet_per_sector,
                total_bet=r.total_bet,
                cumulative_loss=r.cumulative_loss,
                exceeds_table_limit=r.exceeds_table_limit,
                exceeds_bankroll=r.exceeds_bankroll,
            )
            for r in rows
        ],
        max_affordable_stages=engine.max_affordable_stages(
            strategy, base_bet, bankroll, table_limit
        ),
        ruin_probability_estimate=ruin,
        disclaimer=engine.BANKROLL_DISCLAIMER,
    )


@router.get(
    "/sessions/{session_id}/bankroll/suggestion",
    response_model=BankrollSuggestionResponse,
)
def bankroll_suggestion(
    session_id: UUID,
    db: DbSession,
    user: CurrentUser,
    bet: str | None = Query(
        default=None,
        description=(
            "Id de la apuesta sobre la que estimar el riesgo, de las que lista "
            "/bankroll/eligible-bets. Es opcional porque el motor no decide a "
            "que se apuesta: sin ella no se estima el riesgo de agotar la banca."
        ),
    ),
    strategy_key: BankrollStrategy = STRATEGY_QUERY,
) -> BankrollSuggestionResponse:
    """Tamano de apuesta que exige el escalon actual de la progresion.

    No sugiere a que apostar ni afirma nada sobre el resultado del giro
    siguiente: solo traduce la progresion elegida a un monto y su advertencia.
    """
    session = get_owned_session(db, user.id, session_id)
    strategy = _to_engine_strategy(strategy_key)
    stage = _stage_for(session, strategy)
    win_probability = _probability_for_bet(
        _load_config(db, session.game_variant_id), engine.mode_for(strategy), bet
    )
    base_bet = float(session.base_bet)
    table_limit = float(session.table_limit) if session.table_limit else None
    advice = engine.suggest_bet(
        strategy,
        base_bet,
        stage,
        bankroll_current=float(session.bankroll_current),
        table_limit=table_limit,
        probability_of_winning_the_bet=win_probability,
    )
    plan = engine.bankroll_plan(
        strategy,
        base_bet,
        stage,
        bankroll_current=float(session.bankroll_current),
        bankroll_start=float(session.bankroll_start),
        table_limit=table_limit,
        loss_limit=float(session.loss_limit) if session.loss_limit is not None else None,
    )
    return _to_advice_response(advice, plan, base_bet)


@router.get(
    "/sessions/{session_id}/bankroll/eligible-bets",
    response_model=list[EligibleBetResponse],
)
def eligible_bets(
    session_id: UUID,
    db: DbSession,
    user: CurrentUser,
    strategy_key: BankrollStrategy = STRATEGY_QUERY,
) -> list[EligibleBetResponse]:
    """Apuestas de la variante compatibles con el modo de esa progresion.

    Cada una viene con su probabilidad teorica ya calculada por el motor, para
    que la interfaz no tenga que derivarla y no se abra una segunda fuente de
    verdad sobre las probabilidades.
    """
    session = get_owned_session(db, user.id, session_id)
    strategy = _to_engine_strategy(strategy_key)
    apuestas = engine.eligible_bets(
        _load_config(db, session.game_variant_id), engine.mode_for(strategy)
    )
    return [
        EligibleBetResponse(
            id=a.id,
            label=a.label,
            category_id=a.category_id,
            group_ids=list(a.group_ids),
            theoretical_probability=a.theoretical_probability,
        )
        for a in apuestas
    ]


@router.get(
    "/sessions/{session_id}/bankroll/progression",
    response_model=ProgressionTableResponse,
)
def session_progression_table(
    session_id: UUID,
    db: DbSession,
    user: CurrentUser,
    stages: int = Query(default=engine.DEFAULT_PROGRESSION_STAGES, ge=1, le=MAX_PROGRESSION_STAGES),
    bet: str | None = Query(default=None),
    strategy_key: BankrollStrategy = STRATEGY_QUERY,
) -> ProgressionTableResponse:
    """Tabla de progresion con los montos reales de esta sesion."""
    session = get_owned_session(db, user.id, session_id)
    strategy = _to_engine_strategy(strategy_key)
    win_probability = _probability_for_bet(
        _load_config(db, session.game_variant_id), engine.mode_for(strategy), bet
    )
    return _build_table(
        strategy,
        float(session.base_bet),
        stages,
        float(session.table_limit) if session.table_limit else None,
        float(session.bankroll_current),
        win_probability,
    )


@router.get("/bankroll/progression", response_model=ProgressionTableResponse)
def progression_preview(
    strategy: BankrollStrategy,
    base_bet: float = Query(gt=0),
    bankroll: float = Query(gt=0),
    table_limit: float | None = Query(default=None, gt=0),
    stages: int = Query(default=engine.DEFAULT_PROGRESSION_STAGES, ge=1, le=MAX_PROGRESSION_STAGES),
    win_probability: float | None = Query(default=None, ge=0.0, le=1.0),
    *,
    user: CurrentUser,
) -> ProgressionTableResponse:
    """Tabla de progresion ANTES de activar una estrategia (§2.8).

    Existe sin sesion a proposito: el requisito es que el usuario vea en pesos
    lo que cuesta cada escalon antes de comprometerse con la progresion.
    """
    return _build_table(
        _to_engine_strategy(strategy),
        base_bet,
        stages,
        table_limit,
        bankroll,
        win_probability,
    )
