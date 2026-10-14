"""Router publico de juegos y variantes (§3.4) y menu de juegos (§7 de la Fase 4).

Solo lectura: crear y editar vive en `admin.py`.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, RequireAccess
from app.api.v1.admin_users import Limit, Offset
from app.core.access import has_access
from app.models import Game, GameVariant
from app.schemas.games import (
    GameAccess,
    GameMenuItem,
    GameMenuResponse,
    GameResponse,
    GameVariantResponse,
)

router = APIRouter(tags=["games"], dependencies=[RequireAccess])

# Lo que ve un cliente en el menu: los juegos activos y los "proximamente". Un
# administrador ve tambien los ocultos, para probarlos antes de publicarlos.
_CLIENT_STATUSES = ("active", "coming_soon")


@router.get("/games", response_model=GameMenuResponse)
def list_games(
    db: DbSession, user: CurrentUser, limit: Limit = 50, offset: Offset = 0
) -> GameMenuResponse:
    """El menu de juegos, en su orden, con las variantes activas de cada uno.

    Cada juego trae la decision de acceso de `has_access` con ese juego: uno que
    el plan de la cuenta no incluye llega con `game_not_in_plan`, para que el
    menu lo muestre como "disponible en otro plan" en vez de esconderlo.
    """
    filtro = [] if user.role == "admin" else [Game.status.in_(_CLIENT_STATUSES)]
    total = db.scalar(select(func.count()).select_from(Game).where(*filtro)) or 0
    games = db.scalars(
        select(Game)
        .options(selectinload(Game.variants))
        .where(*filtro)
        .order_by(Game.sort_order, Game.name)
        .limit(limit)
        .offset(offset)
    )
    now = datetime.now(UTC)
    items = []
    for game in games:
        decision = has_access(db, user, now, game)
        base = GameResponse.model_validate(game)
        items.append(
            GameMenuItem(
                **base.model_dump(exclude={"variants"}),
                variants=[v for v in base.variants if v.active],
                access=GameAccess(granted=decision.granted, reason=decision.reason),
            )
        )
    return GameMenuResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/games/variants/{variant_id}", response_model=GameVariantResponse)
def get_variant(variant_id: UUID, db: DbSession, user: CurrentUser) -> GameVariant:
    """Una variante por su id, para cualquier usuario autenticado.

    Devuelve la variante aunque este desactivada: desactivarla impide abrir
    sesiones nuevas (ver `create_session`), pero las que ya estaban abiertas
    necesitan su `categories_json` para seguir mostrando el analisis. Sin esto,
    desactivar una variante dejaria en blanco la vista de sus sesiones vivas.
    """
    variant = db.get(GameVariant, variant_id)
    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Variante no encontrada"
        )
    return variant


@router.get("/games/{game_id}/variants", response_model=list[GameVariantResponse])
def list_variants(game_id: UUID, db: DbSession, user: CurrentUser) -> list[GameVariant]:
    game = db.get(Game, game_id)
    if game is None or (game.status == "hidden" and user.role != "admin"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Juego no encontrado")
    stmt = (
        select(GameVariant)
        .where(GameVariant.game_id == game_id)
        .order_by(GameVariant.sort_order, GameVariant.name)
    )
    if user.role != "admin":
        stmt = stmt.where(GameVariant.active.is_(True))
    return list(db.scalars(stmt))
