"""Apuestas reales del usuario y su resolucion automatica (§4).

El usuario registra lo que efectivamente puso en la mesa. Las apuestas quedan
`pending` y se resuelven solas cuando entra el giro siguiente (ver
`resolve_pending_bets`, que llama el router de giros).

En una mesa real se apuesta a varias cosas en el mismo giro, asi que se admiten
varias pendientes: todas se resuelven contra el mismo numero. Cubrir mas opciones
reparte el riesgo pero no lo reduce — la ventaja de la casa se aplica a cada
apuesta por separado.

Registrar una apuesta no es una recomendacion del sistema: el motor describe la
muestra pasada y nunca dice a que apostar. `followed_suggestion` es una nota del
usuario sobre su propia decision, para poder medir despues si seguir las senales
le fue mejor o peor.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.v1.sessions import get_owned_session, require_active
from app.engine.probability import GameConfig
from app.engine.settlement import settle
from app.models import Bet, GameSession, GameVariant, Spin
from app.schemas.bets import BetResolution, BetResponse, CreateBetRequest

router = APIRouter(prefix="/sessions", tags=["bets"])


def _group_id_for_label(
    config: GameConfig, category_id: str, option_label: str
) -> str:
    """Traduce la etiqueta visible al id del grupo.

    La API habla en etiquetas porque es lo que ve el usuario en la pantalla; el
    motor trabaja con ids.
    """
    category = config.category(category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La variante no tiene la categoria '{category_id}'",
        )
    for group in category.groups:
        if group.label == option_label or group.id == option_label:
            return group.id
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"La categoria '{category_id}' no tiene la opcion '{option_label}'",
    )


def pending_bets(db: DbSession, session_id: UUID) -> list[Bet]:
    """Apuestas sin resolver de la sesion, de la mas antigua a la mas reciente."""
    return list(
        db.scalars(
            select(Bet)
            .where(Bet.session_id == session_id, Bet.status == "pending")
            .order_by(Bet.created_at)
        )
    )


def committed_amount(db: DbSession, session_id: UUID) -> float:
    """Dinero ya comprometido en apuestas que aun no se resolvieron."""
    return sum(float(b.amount) for b in pending_bets(db, session_id))


def resolve_pending_bets(
    db: DbSession, session: GameSession, config: GameConfig, spin: Spin
) -> list[BetResolution]:
    """Resuelve todas las apuestas pendientes contra el giro que acaba de entrar.

    Mueve `bankroll_current` y nada mas. **Los escalones de las progresiones no
    se tocan aqui** desde la Fase 3: los mueve el cierre de la recomendacion
    (`recommendations.resolve_pending_recommendation`), no el neto de las
    apuestas reales.

    Son dos cosas distintas y conviene no volver a juntarlas. La banca refleja lo
    que el usuario apostó de verdad en la mesa, que puede ser cualquier cosa; el
    escalon refleja donde estaria quien hubiera seguido al motor. Hacerlo avanzar
    con las apuestas reales significaba que apostar por fuera de la recomendacion
    —o no apostar -- corria la progresion que la mesa muestra.

    No hace commit: lo hace quien la llama, para que el giro y sus resoluciones
    entren o no entren juntos.
    """
    apuestas = pending_bets(db, session.id)
    if not apuestas:
        return []

    resoluciones: list[BetResolution] = []
    neto_del_giro = 0.0

    for bet in apuestas:
        group_id = _group_id_for_label(config, bet.category, bet.option_label)
        resultado = settle(
            config, bet.category, group_id, float(bet.amount), spin.result_value
        )

        bet.spin_id = spin.id
        bet.status = "resolved"
        bet.won = resultado.won
        bet.payout = resultado.payout
        bet.net_change = resultado.net_change
        bet.resolved_at = datetime.now(UTC)

        neto_del_giro += resultado.net_change
        resoluciones.append(
            BetResolution(
                bet_id=bet.id,
                category=bet.category,
                option_label=bet.option_label,
                won=resultado.won,
                amount=float(bet.amount),
                payout=resultado.payout,
                net_change=resultado.net_change,
                followed_suggestion=bet.followed_suggestion,
            )
        )

    session.bankroll_current = float(session.bankroll_current) + neto_del_giro
    return resoluciones


@router.post(
    "/{session_id}/bets", response_model=BetResponse, status_code=status.HTTP_201_CREATED
)
def create_bet(
    session_id: UUID, payload: CreateBetRequest, db: DbSession, user: CurrentUser
) -> Bet:
    """Registra lo que el usuario puso en la mesa, a la espera del giro siguiente.

    Se admiten varias pendientes a la vez, como en una mesa real: todas se
    resuelven contra el mismo numero. Lo que se valida es la **suma** de lo
    comprometido, para no poder apostar mas dinero del que hay en la banca.
    """
    session = require_active(get_owned_session(db, user.id, session_id))
    variant = db.get(GameVariant, session.game_variant_id)
    config = GameConfig.from_dict(variant.categories_json)

    _group_id_for_label(config, payload.category, payload.option_label)

    comprometido = committed_amount(db, session.id)
    disponible = float(session.bankroll_current) - comprometido
    if payload.amount > disponible:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "La apuesta supera lo que queda disponible: ya tienes "
                f"{comprometido:,.0f} comprometido en apuestas sin resolver"
            ),
        )

    bet = Bet(
        session_id=session.id,
        category=payload.category,
        option_label=payload.option_label,
        amount=payload.amount,
        followed_suggestion=payload.followed_suggestion,
        status="pending",
    )
    db.add(bet)
    db.commit()
    db.refresh(bet)
    return bet


@router.get("/{session_id}/bets", response_model=list[BetResponse])
def list_bets(session_id: UUID, db: DbSession, user: CurrentUser) -> list[Bet]:
    """Apuestas de la sesion, de la mas antigua a la mas reciente."""
    session = get_owned_session(db, user.id, session_id)
    return list(
        db.scalars(
            select(Bet).where(Bet.session_id == session.id).order_by(Bet.created_at)
        )
    )


@router.delete(
    "/{session_id}/bets/{bet_id}", status_code=status.HTTP_204_NO_CONTENT
)
def cancel_bet(
    session_id: UUID, bet_id: UUID, db: DbSession, user: CurrentUser
) -> None:
    """Cancela una apuesta que todavia no se resolvio (se registro por error).

    Una apuesta ya resuelta no se toca: cambiaria la banca y la auto-evaluacion
    sobre hechos que ya ocurrieron.
    """
    session = require_active(get_owned_session(db, user.id, session_id))
    bet = db.scalar(select(Bet).where(Bet.id == bet_id, Bet.session_id == session.id))
    if bet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Apuesta no encontrada"
        )
    if bet.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se puede cancelar una apuesta pendiente",
        )
    bet.status = "cancelled"
    db.commit()
