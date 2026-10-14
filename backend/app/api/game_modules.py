"""Registro de modulos de juego (docs/PLATAFORMA_COMPLETA.md §7.3).

Un modulo es una familia de juego: decide que routers lo juegan y con que se
valida la configuracion de sus variantes. Hoy solo esta implementado
`discrete_outcome` (ruleta, y todo juego que se describa con `categories_json`),
que agrupa los routers de la mesa.

`sports` esta reservado para las apuestas deportivas (§8.2): figura aqui sin
implementacion, asi que el admin rechaza crear un juego con el. Cuando exista,
su entrada trae sus routers y `main.py` los monta sin mas cambios.
"""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter

from app.api.v1 import bankroll, bets, recommendations, sessions, suggestions
from app.core.game_config_validation import ConfigValidationResult, validate_game_config
from app.models.game import GAME_MODULES
from app.schemas.games import GameVariantConfig


@dataclass(frozen=True)
class GameModule:
    # Los routers que juegan este modulo. Todos llevan `RequireAccess`.
    routers: tuple[APIRouter, ...]
    # Valida el `categories_json` de una variante antes de guardarla.
    validate_config: Callable[[GameVariantConfig], ConfigValidationResult]


# None = reservado, sin implementacion.
MODULES: dict[str, GameModule | None] = {
    "discrete_outcome": GameModule(
        routers=(
            sessions.router,
            suggestions.router,
            recommendations.router,
            bankroll.router,
            bets.router,
        ),
        validate_config=validate_game_config,
    ),
    "sports": None,
}

# El enum de la base y el registro no pueden separarse: un modulo que existe en
# uno y no en el otro seria un juego sin pantalla o una pantalla sin juego.
assert set(MODULES) == set(GAME_MODULES), "games.module y el registro no coinciden"


def implemented(module: str) -> GameModule | None:
    """El modulo, si existe y esta implementado; None si no."""
    return MODULES.get(module)


def game_routers() -> list[APIRouter]:
    """Los routers de todos los modulos implementados, sin repetir."""
    vistos: list[APIRouter] = []
    for modulo in MODULES.values():
        if modulo is None:
            continue
        for router in modulo.routers:
            if router not in vistos:
                vistos.append(router)
    return vistos
