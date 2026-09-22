"""
Schemas: Spins (resultados genéricos de cualquier juego de resultados discretos)
"""
from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, ConfigDict


class SpinSource(str, Enum):
    """Ambos son ingreso manual: el proyecto no lee pantallazos (§3.5)."""
    manual = "manual"                # ingresado giro a giro
    initial_batch = "initial_batch"  # cargado de una vez al abrir la sesión


# ---------- Requests ----------

class CreateSpinRequest(BaseModel):
    result_value: str  # valor crudo, ej '17', '00', '7' (dados)
    source: SpinSource = SpinSource.manual


class EntryOrder(str, Enum):
    """Cómo escribió el usuario la lista de la carga inicial.

    Es obligatorio y explícito: el motor pondera por recencia (§2.3), así que
    invertir el orden en silencio produce un análisis equivocado sin que nada
    falle de forma visible.
    """
    most_recent_first = "most_recent_first"
    most_recent_last = "most_recent_last"


class BulkSpinsRequest(BaseModel):
    """Carga inicial de los números ya observados en la mesa (§3.5)."""
    values: list[str]
    order: EntryOrder


# ---------- Responses ----------

class SpinResponse(BaseModel):
    id: UUID
    session_id: UUID
    spin_index: int
    result_value: str
    source: SpinSource
    # Escalones de las progresiones antes de resolver este giro. La UI arma con
    # ellos el aviso "la progresión sube del escalón 2 al 3", y deshacer el giro
    # los restaura. Son dos porque las tres progresiones corren a la vez (§2.10);
    # la plana no tiene escalón, siempre está en 0.
    stage_martingale_before: Optional[int] = None
    stage_two_sector_before: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BulkSpinsResponse(BaseModel):
    """Los giros efectivamente creados, ya en orden cronológico ascendente."""
    created: int
    spins: list[SpinResponse]


class CategoryDerivedResult(BaseModel):
    """Categoría/grupo derivados en tiempo real para un result_value dado,
    calculados contra game_variant.categories_json (no se persisten como columnas)."""
    category: str
    option_label: str


class SpinWithDerivedCategories(SpinResponse):
    derived_categories: list[CategoryDerivedResult] = []
