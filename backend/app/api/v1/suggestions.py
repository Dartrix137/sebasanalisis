"""Senales estadisticas y auto-evaluacion de una sesion (§3.4).

Esta capa solo traduce: carga los giros, llama al motor puro de `engine/` y
mapea el resultado a los schemas. Ninguna formula vive aqui.
"""

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.v1.sessions import get_owned_session
from app.engine.baseline import evaluate
from app.engine.probability import GameConfig
from app.engine.ranking import Suggestion, rank_suggestions
from app.engine.streak import longest_active_streak
from app.models import GameVariant, Spin
from app.schemas.sessions import SessionPerformanceResponse
from app.schemas.suggestions import (
    SignalStrength,
    StatisticalSuggestionItem,
    StatisticalSuggestionsPanel,
    StreakAlert,
)

router = APIRouter(prefix="/sessions", tags=["suggestions"])


def _load_context(
    db: DbSession, user_id: UUID, session_id: UUID
) -> tuple[GameConfig, list[str], int]:
    """Configuracion de la variante y los giros de la sesion, mas antiguo primero.

    `window_size` es un limite superior por rendimiento (§2.3): se cargan los
    ultimos N giros. El peso real de cada uno lo decide el decaimiento
    exponencial dentro del motor, no este recorte.
    """
    session = get_owned_session(db, user_id, session_id)
    variant = db.get(GameVariant, session.game_variant_id)
    config = GameConfig.from_dict(variant.categories_json)

    stmt = (
        select(Spin.result_value)
        .where(Spin.session_id == session.id)
        .order_by(Spin.spin_index.desc())
        .limit(session.window_size)
    )
    # Se piden los ultimos N descendente y se invierte, para dejarlos en orden
    # cronologico ascendente, que es lo que espera el motor.
    resultados = list(reversed(list(db.scalars(stmt))))
    return config, resultados, session.window_size


def _to_item(s: Suggestion) -> StatisticalSuggestionItem:
    return StatisticalSuggestionItem(
        category=s.category_id,
        option_label=s.group_label,
        theoretical_probability=s.theoretical_probability,
        observed_frequency_shrunk=s.observed_frequency_shrunk,
        deviation=s.deviation,
        significance_score=s.significance_score,
        strength=SignalStrength(s.strength.value),
        ev=s.ev,
        chi_square_pvalue_adjusted=s.chi_square_pvalue_adjusted,
    )


@router.get("/{session_id}/suggestions/latest", response_model=StatisticalSuggestionsPanel)
def latest_suggestions(
    session_id: UUID, db: DbSession, user: CurrentUser
) -> StatisticalSuggestionsPanel:
    config, resultados, window = _load_context(db, user.id, session_id)
    sugerencias = rank_suggestions(config, resultados)

    por_categoria: dict[str, list[StatisticalSuggestionItem]] = {}
    for s in sugerencias:
        por_categoria.setdefault(s.category_id, []).append(_to_item(s))

    return StatisticalSuggestionsPanel(
        window_size_used=window,
        top=[_to_item(s) for s in sugerencias if s.is_top3],
        all_categories=por_categoria,
    )


@router.get("/{session_id}/streak", response_model=StreakAlert | None)
def active_streak_alert(session_id: UUID, db: DbSession, user: CurrentUser) -> StreakAlert | None:
    config, resultados, _ = _load_context(db, user.id, session_id)
    racha = longest_active_streak(config, resultados)
    if racha is None:
        return None
    return StreakAlert(
        category=racha.category_id,
        option_label=racha.group_label,
        consecutive_count=racha.consecutive_count,
        probability_of_streak=racha.probability_of_streak,
    )


@router.get("/{session_id}/performance", response_model=SessionPerformanceResponse)
def session_performance(
    session_id: UUID, db: DbSession, user: CurrentUser
) -> SessionPerformanceResponse:
    """Auto-evaluacion de §2.7.

    Se recalcula sobre el historial en cada llamada en vez de leerse de
    `session_performance`: el motor es determinista, asi que re-simular da el
    mismo resultado que haber ido acumulando fila a fila, y evita que un cambio
    en una formula deje conteos viejos e incomparables en la base.
    """
    session = get_owned_session(db, user.id, session_id)
    config, resultados, _ = _load_context(db, user.id, session_id)
    informe = evaluate(config, resultados)

    return SessionPerformanceResponse(
        session_id=session.id,
        total_suggestions=informe.total_suggestions,
        matched_suggestions=informe.matched_suggestions,
        match_rate=informe.match_rate,
        baseline_matched=informe.baseline_matched,
        baseline_match_rate=informe.baseline_match_rate,
        verdict=informe.verdict,
        updated_at=session.started_at,
    )
