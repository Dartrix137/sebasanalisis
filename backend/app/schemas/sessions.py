"""
Schemas: Game Sessions
"""
from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SessionStatus(str, Enum):
    active = "active"
    closed = "closed"
    abandoned = "abandoned"


class BankrollStrategy(str, Enum):
    martingale = "martingale"
    dalembert = "dalembert"
    fibonacci = "fibonacci"
    flat = "flat"
    # Progresión de recuperación para dos docenas/columnas (§2.8). No es una
    # martingala clásica: el beneficio neto al acertar es solo una fracción de
    # lo apostado, así que la progresión es 1-1, 2-2, 6-6, 18-18, 54-54.
    two_sector_recovery = "two_sector_recovery"


class StrategyMode(str, Enum):
    single = "single"          # apuestas de pago 1:1 (color, paridad, alto/bajo)
    two_sector = "two_sector"  # dos docenas o dos columnas simultáneas


def _validate_mode_strategy(mode: "StrategyMode", strategy: BankrollStrategy) -> None:
    """Regla cruzada de `docs/ARQUITECTURA_Y_ESTADISTICA.md` §2.8.

    El modo dos-sectores solo admite la progresión de recuperación, y esa
    progresión no tiene sentido en modo 1:1. La misma regla se replica en el
    endpoint y en un CHECK de base de datos: el schema es la primera barrera,
    no la única.
    """
    if mode is StrategyMode.single and strategy is BankrollStrategy.two_sector_recovery:
        raise ValueError(
            "La estrategia 'two_sector_recovery' requiere strategy_mode='two_sector' "
            "(§2.8: su progresión asume apostar a dos sectores a la vez)"
        )
    if mode is StrategyMode.two_sector and strategy is not BankrollStrategy.two_sector_recovery:
        raise ValueError(
            "strategy_mode='two_sector' solo admite la estrategia 'two_sector_recovery' "
            "(§2.8: la martingala clásica no aplica a pagos 2:1 sobre dos sectores)"
        )


# ---------- Requests ----------

class CreateSessionRequest(BaseModel):
    game_variant_id: UUID
    name: Optional[str] = Field(default=None, max_length=100)
    window_size: int = Field(default=50, ge=5, le=500)
    bankroll_start: float = Field(gt=0)
    base_bet: float = Field(gt=0)
    table_limit: float = Field(gt=0)
    strategy: BankrollStrategy = BankrollStrategy.flat
    strategy_mode: StrategyMode = StrategyMode.single

    def validate_bet_within_bankroll(self):
        if self.base_bet > self.bankroll_start:
            raise ValueError("La apuesta base no puede superar el bankroll inicial")

    @model_validator(mode="after")
    def check_mode_matches_strategy(self) -> "CreateSessionRequest":
        _validate_mode_strategy(self.strategy_mode, self.strategy)
        return self


class UpdateSessionRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    window_size: Optional[int] = Field(default=None, ge=5, le=500)
    strategy: Optional[BankrollStrategy] = None
    strategy_mode: Optional[StrategyMode] = None
    table_limit: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def check_mode_matches_strategy(self) -> "UpdateSessionRequest":
        # Solo valida si el request trae ambos. Si viene uno solo, el endpoint
        # debe combinarlo con el valor ya persistido antes de aceptar el cambio.
        if self.strategy_mode is not None and self.strategy is not None:
            _validate_mode_strategy(self.strategy_mode, self.strategy)
        return self


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
    strategy_selected: BankrollStrategy
    strategy_mode: StrategyMode
    strategy_stage: int
    started_at: datetime
    closed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SessionSummaryResponse(BaseModel):
    session_id: UUID
    duration_minutes: float
    total_spins: int
    total_bets: int
    win_rate: float
    bankroll_start: float
    bankroll_final: float
    net_change: float
    strategy_used: BankrollStrategy
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
