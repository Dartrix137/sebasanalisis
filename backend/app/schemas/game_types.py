"""Tipos de los metadatos de un juego (docs/PLATAFORMA_COMPLETA.md §7.2).

Aparte de `schemas/games.py` para que otros schemas (la sesion) los usen sin
importar todo el modulo de juegos. Los valores son los de `models/game.py`.
"""

from typing import Literal

GameModule = Literal["discrete_outcome", "sports"]
GameStatus = Literal["active", "hidden", "coming_soon"]
GameIcon = Literal["ruleta", "dados", "cartas", "deportes", "generico"]
