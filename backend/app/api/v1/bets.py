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
from app.engine.bankroll import StopReason, stop_reason
from app.engine.probability import GameConfig
from app.engine.settlement import settle
from app.models import Bet, GameSession, GameVariant, Spin
from app.schemas.bets import BetResponse, CreateBetRequest

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
) -> list[Bet]:
    """Resuelve todas las apuestas pendientes contra el giro que acaba de entrar.

    Mueve `bankroll_current` y nada mas. **Los escalones no se tocan aqui**: los
    mueve `recommendations.resolve_pending_recommendation`, con el cierre de la
    recomendacion y solo para las gestiones con las que se aposto (`strategy`).
    Una apuesta manual por fuera de las progresiones mueve la banca, no un
    escalon.

    No hace commit: lo hace quien la llama, para que el giro y sus resoluciones
    entren o no entren juntos.
    """
    apuestas = pending_bets(db, session.id)
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

    session.bankroll_current = float(session.bankroll_current) + neto_del_giro
    return apuestas


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

    motivo = stop_reason(
        float(session.bankroll_current),
        float(session.bankroll_start),
        float(session.base_bet),
        float(session.loss_limit) if session.loss_limit is not None else None,
    )
    if motivo is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "La banca ya no cubre la apuesta base: esta mesa no acepta más apuestas"
                if motivo is StopReason.bankroll_exhausted
                else "Alcanzaste tu límite de pérdida: esta mesa no acepta más apuestas"
            ),
        )

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
        strategy=payload.strategy.value if payload.strategy is not None else None,
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
