"""
Schemas: Bets
"""
from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sessions import BankrollStrategy


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
    # Gestión con la que se apostó. Solo esa progresión avanza de escalón al
    # resolverse el giro; null en una apuesta manual por fuera de ellas.
    strategy: Optional[BankrollStrategy] = None


# ---------- Responses ----------

class BetResponse(BaseModel):
    id: UUID
    session_id: UUID
    spin_id: Optional[UUID] = None
    category: str
    option_label: str
    amount: float
    followed_suggestion: bool
    strategy: Optional[BankrollStrategy] = None
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
