"""
Schemas: Game Sessions
"""
from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.engine.bankroll import stop_reason as _stop_reason


class StopReason(str, Enum):
    """Por qué la mesa dejó de ofrecer apuestas. Debe coincidir con
    `app.engine.bankroll.StopReason`."""
    # La banca ya no cubre la apuesta base.
    bankroll_exhausted = "bankroll_exhausted"
    # Se alcanzó el límite de pérdida que el usuario fijó.
    loss_limit_reached = "loss_limit_reached"


class SessionStatus(str, Enum):
    active = "active"
    closed = "closed"
    abandoned = "abandoned"


class BankrollStrategy(str, Enum):
    """Las tres progresiones que ofrece la mesa (§2.10).

    Desde la Fase 3 la sesión no elige una al crearse: la vista de ruleta las
    muestra a la vez con lo que pide cada una, y el usuario sigue la que quiera.
    Por eso no hay `strategy_selected` ni `strategy_mode` — cada progresión
    lleva su propio escalón, que solo avanza cuando el usuario apostó con esa
    gestión (`bets.strategy`).

    D'Alembert y Fibonacci salieron del producto en la Fase 3.
    """
    flat = "flat"
    martingale = "martingale"
    # Progresión de recuperación para dos docenas/columnas (§2.8). No es una
    # martingala clásica: el beneficio neto al acertar es solo una fracción de
    # lo apostado, así que la progresión es 1-1, 2-2, 6-6, 18-18, 54-54.
    two_sector_recovery = "two_sector_recovery"


# ---------- Requests ----------

class CreateSessionRequest(BaseModel):
    game_variant_id: UUID
    name: Optional[str] = Field(default=None, max_length=100)
    window_size: int = Field(default=50, ge=5, le=500)
    bankroll_start: float = Field(gt=0)
    base_bet: float = Field(gt=0)
    table_limit: float = Field(gt=0)
    # Pérdida neta en la que el usuario decide detenerse (§2.8). Opcional.
    loss_limit: Optional[float] = Field(default=None, gt=0)

    def validate_bet_within_bankroll(self):
        if self.base_bet > self.bankroll_start:
            raise ValueError("La apuesta base no puede superar el bankroll inicial")
        if self.loss_limit is not None and self.loss_limit > self.bankroll_start:
            raise ValueError(
                "El límite de pérdida no puede superar la banca inicial: no se puede "
                "perder más de lo que se trae a la mesa"
            )


class UpdateSessionRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    window_size: Optional[int] = Field(default=None, ge=5, le=500)
    table_limit: Optional[float] = Field(default=None, gt=0)
    # Solo se puede fijar si no había uno, o bajar. Subirlo o quitarlo con la
    # sesión abierta es "aumentar el límite para recuperar" (§9 del documento
    # verificado); el endpoint lo rechaza con 422.
    loss_limit: Optional[float] = Field(default=None, gt=0)


# ---------- Responses ----------

class SessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    game_variant_id: UUID
    name: Optional[str] = None
    status: SessionStatus
    window_size: int
    bankroll_start: float
    bankroll_current: float
    base_bet: float
    table_limit: float
    loss_limit: Optional[float] = None
    # Un escalón por progresión: las tres corren a la vez y el usuario sigue la
    # que quiera (§2.10). La plana no tiene escalón porque no tiene progresión.
    stage_martingale: int
    stage_two_sector: int
    started_at: datetime
    closed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stop_reason(self) -> Optional[StopReason]:
        """null mientras se pueda apostar. Con valor, la mesa sigue abierta pero
        no acepta apuestas: la banca no cubre la apuesta base o se alcanzó el
        límite de pérdida. Se deriva de la banca, así que deshacer el giro que lo
        provocó lo levanta solo. Lo decide el servidor, no el cliente."""
        motivo = _stop_reason(
            self.bankroll_current, self.bankroll_start, self.base_bet, self.loss_limit
        )
        return StopReason(motivo.value) if motivo is not None else None


class SessionSummaryResponse(BaseModel):
    session_id: UUID
    duration_minutes: float
    total_spins: int
    total_bets: int
    win_rate: float
    bankroll_start: float
    bankroll_final: float
    net_change: float
    max_drawdown: float
    followed_suggestion_rate: float


class SessionPerformanceResponse(BaseModel):
    """Auto-evaluación de la sesión (§2.7) — GET /sessions/:id/performance.

    `matched_suggestions` cuenta coincidencias entre las señales emitidas y el
    resultado observado después. No es "precisión" ni implica que la señal
    anticipara el giro: la ruleta no tiene memoria.
    """
    session_id: UUID
    total_suggestions: int
    matched_suggestions: int
    match_rate: float           # matched / total, 0.0 si total == 0
    baseline_matched: int       # línea base ingenua: repetir la última categoría ganadora
    baseline_match_rate: float
    verdict: str                # veredicto explícito en lenguaje descriptivo
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
