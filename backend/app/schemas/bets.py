"""
Schemas: Bets
"""
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel
from app.schemas.sessions import BankrollStrategy


class BetStatus(str, Enum):
    pending = "pending"
    resolved = "resolved"
    # Destino de una apuesta que sigue pending cuando se cierra la sesión,
    # para que no quede huérfana sin estado.
    cancelled = "cancelled"


# ---------- Requests ----------

class CreateBetRequest(ApiModel):
    category: str          # debe existir en game_variant.categories_json
    option_label: str      # debe existir dentro de esa categoría
    amount: float = Field(gt=0)
    followed_suggestion: bool = False
    # Gestión con la que se apostó. Solo esa progresión avanza de escalón al
    # resolverse el giro; null en una apuesta manual por fuera de ellas.
    strategy: BankrollStrategy | None = None


# ---------- Responses ----------

class BetResponse(ApiModel):
    id: UUID
    session_id: UUID
    spin_id: UUID | None = None
    category: str
    option_label: str
    amount: float
    followed_suggestion: bool
    strategy: BankrollStrategy | None = None
    status: BetStatus
    won: bool | None = None
    payout: float | None = None
    net_change: float | None = None
    created_at: datetime
    resolved_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class BetResolution(ApiModel):
    """Sub-objeto embebido en la respuesta de POST /spins cuando resuelve una apuesta pendiente."""
    bet_id: UUID
    category: str
    option_label: str
    won: bool
    amount: float
    payout: float
    net_change: float
    followed_suggestion: bool
