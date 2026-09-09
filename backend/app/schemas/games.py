"""
Schemas: Games & Variants
Modelo genérico: cualquier juego de resultados discretos con probabilidad fija
(ruleta, dados, y futuros) se describe con el mismo esquema de configuración.
"""
from uuid import UUID
from typing import Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


# ---------- Config genérica (categories_json) ----------

class CategoryGroup(BaseModel):
    """Un grupo dentro de una categoría, ej: 'red' dentro de 'color'."""
    label: Optional[str] = None  # nombre legible del grupo, ej 'Rojo'; lo trae el seed
    outcomes: list[str] = Field(min_length=1)
    payout: float = Field(gt=0, description="Multiplicador de pago, ej 1 para rojo/negro, 35 para pleno")


class GameCategory(BaseModel):
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


class GameVariantConfig(BaseModel):
    """El contenido completo de game_variants.categories_json + metadata."""
    possible_outcomes: list[str] = Field(min_length=1)
    categories: list[GameCategory] = Field(min_length=1)

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


# ---------- Requests (admin) ----------

class CreateGameRequest(BaseModel):
    name: str
    type: str  # 'roulette' | 'dice' | futuro
    active: bool = True


class UpdateGameRequest(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None


class CreateGameVariantRequest(BaseModel):
    name: str  # 'american' | 'european' | 'two_d6'
    house_edge: float = Field(ge=0, le=1)
    config: GameVariantConfig
    active: bool = True


class UpdateGameVariantRequest(BaseModel):
    name: Optional[str] = None
    house_edge: Optional[float] = Field(default=None, ge=0, le=1)
    config: Optional[GameVariantConfig] = None
    active: Optional[bool] = None


# ---------- Responses ----------

class GameVariantResponse(BaseModel):
    id: UUID
    game_id: UUID
    name: str
    house_edge: float
    # La columna del modelo se llama `categories_json`; el alias permite poblar
    # este campo tanto desde el ORM como desde un cuerpo JSON con clave `config`.
    config: GameVariantConfig = Field(
        validation_alias=AliasChoices("config", "categories_json")
    )
    active: bool

    model_config = ConfigDict(from_attributes=True)


class GameResponse(BaseModel):
    id: UUID
    name: str
    type: str
    active: bool
    variants: list[GameVariantResponse] = []

    model_config = ConfigDict(from_attributes=True)
