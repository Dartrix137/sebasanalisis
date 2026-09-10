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
) -> tuple[GameConfig, list[str], list[str], int]:
    """Configuracion de la variante y los giros de la sesion, mas antiguo primero.

    Devuelve DOS listas a proposito: la ventana de recencia y el historial
    completo. `window_size` es un limite superior por rendimiento (§2.3) que
    aplica solo a las senales ponderadas, donde recortar no cuesta casi nada
    porque el peso ya decae exponencialmente. Aplicarselo tambien al
    chi-cuadrado lo dejaba viendo 50 giros por defecto y contradecia en silencio
    lo que esa prueba dice hacer (§2.4), que es mirar el historial entero.
    """
    session = get_owned_session(db, user_id, session_id)
    variant = db.get(GameVariant, session.game_variant_id)
    config = GameConfig.from_dict(variant.categories_json)

    # Orden cronologico ascendente, que es lo que espera el motor.
    completo = list(
        db.scalars(
            select(Spin.result_value)
            .where(Spin.session_id == session.id)
            .order_by(Spin.spin_index.asc())
        )
    )
    return config, completo[-session.window_size :], completo, session.window_size


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
    config, ventana, completo, window = _load_context(db, user.id, session_id)
    sugerencias = rank_suggestions(config, ventana, full_history=completo)

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
    # La racha activa es por definicion lo mas reciente: le basta la ventana.
    config, ventana, _, _ = _load_context(db, user.id, session_id)
    racha = longest_active_streak(config, ventana)
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
    # Va sobre la ventana y no sobre la sesion entera por costo: `evaluate`
    # re-simula giro a giro y cada paso vuelve a rankear, asi que el trabajo
    # crece con el cuadrado de los giros (800 giros ~ 1.4 s) y este endpoint se
    # llama despues de cada giro. La ventana da una comparacion mas ruidosa pero
    # igual de valida; el chi-cuadrado es el que no admite recorte, no esto.
    config, ventana, _, _ = _load_context(db, user.id, session_id)
    informe = evaluate(config, ventana)

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
