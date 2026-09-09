"""Router publico de juegos y variantes (§3.4).

Solo lectura: crear y editar vive en `admin.py`.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import Game, GameVariant
from app.schemas.games import GameResponse, GameVariantResponse

router = APIRouter(tags=["games"])


@router.get("/games", response_model=list[GameResponse])
def list_games(
    db: DbSession,
    user: CurrentUser,
    include_inactive: bool = Query(
        default=False,
        description="Incluye juegos y variantes desactivados. Solo para administradores.",
    ),
) -> list[Game]:
    if include_inactive and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere permisos de administrador",
        )
    stmt = select(Game).options(selectinload(Game.variants)).order_by(Game.name)
    if not include_inactive:
        stmt = stmt.where(Game.active.is_(True))
    games = list(db.scalars(stmt))
    if not include_inactive:
        for game in games:
            game.variants = [v for v in game.variants if v.active]
    return games


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
    if game is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Juego no encontrado")
    stmt = select(GameVariant).where(GameVariant.game_id == game_id).order_by(GameVariant.name)
    if user.role != "admin":
        stmt = stmt.where(GameVariant.active.is_(True))
    return list(db.scalars(stmt))
