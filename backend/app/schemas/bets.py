"""
Schemas: Bets
"""
from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class BetStatus(str, Enum):
    pending = "pending"
    resolved = "resolved"
    # Destino de una apuesta que sigue pending cuando se cierra la sesión,
    # para que no quede huérfana sin estado.
    cancelled = "cancelled"


# ---------- Requests ----------

class CreateBetRequest(BaseModel):
    category: str          # debe existir en game_variant.categories_json
    option_label: str      # debe existir dentro de esa categoría
    amount: float = Field(gt=0)
    followed_suggestion: bool = False


# ---------- Responses ----------

class BetResponse(BaseModel):
    id: UUID
    session_id: UUID
    spin_id: Optional[UUID] = None
    category: str
    option_label: str
    amount: float
    followed_suggestion: bool
    status: BetStatus
    won: Optional[bool] = None
    payout: Optional[float] = None
    net_change: Optional[float] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BetResolution(BaseModel):
    """Sub-objeto embebido en la respuesta de POST /spins cuando resuelve una apuesta pendiente."""
    bet_id: UUID
    category: str
    option_label: str
    won: bool
    amount: float
    payout: float
    net_change: float
    followed_suggestion: bool
