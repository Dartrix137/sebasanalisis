"""
Schemas: Games & Variants
Modelo genérico: cualquier juego de resultados discretos con probabilidad fija
(ruleta, dados, y futuros) se describe con el mismo esquema de configuración.
"""
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from app.models.game import SLUG_PATTERN
from app.schemas.auth import AccessReason
from app.schemas.base import ApiModel, Reason
from app.schemas.game_types import GameIcon, GameModule, GameStatus

# ---------- Config genérica (categories_json) ----------

class CategoryGroup(ApiModel):
    """Un grupo dentro de una categoría, ej: 'red' dentro de 'color'."""
    label: str | None = None  # nombre legible del grupo, ej 'Rojo'; lo trae el seed
    outcomes: list[str] = Field(min_length=1)
    payout: float = Field(gt=0, description="Multiplicador de pago, ej 1 para rojo/negro, 35 para pleno")
    market: bool = Field(
        default=True,
        description=(
            "Si el grupo entra al catálogo de mercados del motor de recomendación "
            "(§2.10). El verde de la ruleta lo pone en false: cubre el 0/00 y no es "
            "una zona que el producto recomiende, pero se conserva como grupo para "
            "que las frecuencias de color sumen 1 y el χ² tenga todas sus celdas."
        ),
    )


class GameCategory(ApiModel):
    """Una categoría de agrupación, ej: 'color', 'dozen', 'sum_range'."""
    id: str
    label: str
    shrinkage_alpha: float = Field(
        default=8,
        gt=0,
        description="Fuerza de shrinkage bayesiano para esta categoría (ver ARQUITECTURA_Y_ESTADISTICA.md §2.2). "
                    "Configuración del juego, no constante del motor — depende de cuántos grupos tiene la categoría."
    )
    groups: dict[str, CategoryGroup]

    @field_validator("groups")
    @classmethod
    def groups_not_empty(cls, v):
        if not v:
            raise ValueError("Una categoría debe tener al menos un grupo")
        return v


class AllowedCombination(ApiModel):
    """Una apuesta a varios grupos de la misma categoría a la vez (dos docenas).

    Vive en los datos y no en el motor porque "dos docenas" es una regla de la
    mesa, no una verdad matemática: un juego nuevo declara las suyas y
    `engine/recommendation.py` no cambia (§2.10).
    """
    id: str
    label: str
    category_id: str
    group_ids: list[str] = Field(min_length=2)


OutcomeTone = Literal["red", "black", "green", "neutral"]


class OutcomeDisplay(ApiModel):
    """Pista de presentación del teclado de resultados (§7.3).

    Solo dice cómo se ve: el motor la ignora. Sin ella, el teclado sale en una
    grilla con todos los resultados en tono neutro.
    """
    # Categoría cuyos grupos dan el tono de cada resultado, ej. 'color'.
    outcome_tone_category: str | None = None
    # Tono de cada grupo de esa categoría. Un grupo sin tono va en neutro.
    tones: dict[str, OutcomeTone] = {}
    layout: Literal["grid"] = "grid"
    # Columnas de la grilla. Sin ellas, el frontend elige según el ancho.
    columns: int | None = Field(default=None, ge=1, le=12)


class GameVariantConfig(ApiModel):
    """El contenido completo de game_variants.categories_json + metadata."""
    possible_outcomes: list[str] = Field(min_length=1)
    categories: list[GameCategory] = Field(min_length=1)
    # Lista y no diccionario a propósito: JSONB no conserva el orden de las
    # claves de un objeto, y el desempate del motor necesita un orden de
    # catálogo estable (§2.10).
    allowed_combinations: list[AllowedCombination] = []
    # Umbral medio: `signal_score` desde el que la señal es MEDIA y se ofrecen
    # las progresiones. Configurable por variante desde el admin.
    recommendation_threshold: float = Field(default=50, ge=0, le=100)
    # Umbral débil: desde aquí hay recomendación (SEÑAL DÉBIL, solo apuesta
    # base); por debajo la decisión es NO APOSTAR. Igualarlo al medio apaga la
    # señal débil.
    weak_threshold: float = Field(default=35, ge=0, le=100)
    # Solo presentación (§7.3); el motor no la lee.
    display: OutcomeDisplay | None = None

    @model_validator(mode="after")
    def weak_not_above_medium(self):
        if self.weak_threshold > self.recommendation_threshold:
            raise ValueError(
                "El umbral de señal débil no puede ser mayor que el de señal media"
            )
        return self

    @field_validator("categories")
    @classmethod
    def outcomes_within_possible(cls, categories, info):
        possible = set(info.data.get("possible_outcomes", []))
        if not possible:
            return categories
        for cat in categories:
            for group_name, group in cat.groups.items():
                unknown = set(group.outcomes) - possible
                if unknown:
                    raise ValueError(
                        f"Categoría '{cat.id}', grupo '{group_name}': "
                        f"valores {unknown} no están en possible_outcomes"
                    )
        return categories


# ---------- Metadatos del juego (§7.2) ----------

_SLUG = Field(min_length=1, max_length=60, pattern=SLUG_PATTERN)


# ---------- Requests (admin) ----------

class CreateGameRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    # Identificador interno estable, ej. 'roulette'. No se repite.
    type: str = Field(min_length=1, max_length=60)
    # Va en la URL (`/juegos/<slug>`) y no cambia después de creado.
    slug: str = _SLUG
    module: GameModule
    description: str = Field(default="", max_length=2000)
    icon: GameIcon = "generico"
    sort_order: int = Field(default=0, ge=0, le=10_000)
    # Un juego nuevo nace oculto: se publica cuando tenga sus variantes.
    status: GameStatus = "hidden"
    reason: str = Reason


class UpdateGameRequest(ApiModel):
    """PATCH /admin/games/:id. El tipo, el slug y el módulo no cambian.

    El motivo es obligatorio si cambia el estado: ocultar un juego, o pasarlo a
    "próximamente", le quita la mesa nueva a los clientes, y eso queda en la
    bitácora.
    """
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    icon: GameIcon | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    status: GameStatus | None = None
    reason: str | None = Field(default=None, min_length=3, max_length=500)


class CreateGameVariantRequest(ApiModel):
    name: str  # 'american' | 'european' | 'd6'
    description: str = Field(default="", max_length=2000)
    sort_order: int = Field(default=0, ge=0, le=10_000)
    house_edge: float = Field(ge=0, le=1)
    config: GameVariantConfig
    active: bool = True


class UpdateGameVariantRequest(ApiModel):
    name: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    house_edge: float | None = Field(default=None, ge=0, le=1)
    config: GameVariantConfig | None = None
    active: bool | None = None


# ---------- Responses ----------

class GameVariantResponse(ApiModel):
    id: UUID
    game_id: UUID
    name: str
    description: str
    sort_order: int
    house_edge: float
    # La columna del modelo se llama `categories_json`; el alias permite poblar
    # este campo tanto desde el ORM como desde un cuerpo JSON con clave `config`.
    config: GameVariantConfig = Field(
        validation_alias=AliasChoices("config", "categories_json")
    )
    active: bool

    model_config = ConfigDict(from_attributes=True)


class GameResponse(ApiModel):
    id: UUID
    name: str
    type: str
    slug: str
    module: GameModule
    description: str
    icon: GameIcon
    sort_order: int
    status: GameStatus
    variants: list[GameVariantResponse] = []

    model_config = ConfigDict(from_attributes=True)


class GameAccess(ApiModel):
    """Si la cuenta puede jugar este juego, y si no, por qué (§7.4).

    Es la decisión de `core/access.has_access` con el juego. El motivo que
    importa en el menú es `game_not_in_plan`: el juego se muestra como
    "disponible en otro plan".
    """
    granted: bool
    reason: AccessReason


class GameMenuItem(GameResponse):
    """Un juego del menú. Solo trae las variantes activas."""
    access: GameAccess


class GameMenuResponse(ApiModel):
    items: list[GameMenuItem]
    total: int
    limit: int
    offset: int


class AdminGameListResponse(ApiModel):
    """Lista del admin: todos los juegos y todas sus variantes."""
    items: list[GameResponse]
    total: int
    limit: int
    offset: int
