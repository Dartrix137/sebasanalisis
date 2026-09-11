"""
Schemas: Statistical suggestions & Bankroll suggestions
"""
from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Optional
from pydantic import BaseModel

from app.schemas.bets import BetResolution
from app.schemas.sessions import BankrollStrategy
from app.schemas.spins import SpinResponse


class SignalStrength(str, Enum):
    """Fuerza de la señal según §2.6 — nunca "confianza": describe la evidencia
    pasada de la muestra, no una certeza sobre el próximo giro."""
    strong = "strong"
    medium = "medium"
    weak = "weak"


class StatisticalSuggestionItem(BaseModel):
    category: str
    option_label: str
    # Regla anti-falacia del jugador (§2): estos dos viajan y se muestran
    # SIEMPRE juntos, nunca uno solo.
    theoretical_probability: float
    # El sufijo `_shrunk` es deliberado: aquí va la frecuencia con shrinkage
    # bayesiano (§2.2), nunca la frecuencia cruda.
    observed_frequency_shrunk: float
    # Intervalo de Wilson al 95% sobre los conteos crudos (§2.2). Es la escala
    # del ruido: 6 de 10 y 600 de 1000 son ambos 60% y no dicen lo mismo.
    # Se muestra, no se interpreta: no hay un campo "esto se distingue del azar"
    # a propósito (serían 13 pruebas simultáneas — ver §2.2 del doc).
    observed_ci_low: float
    observed_ci_high: float
    deviation: float
    significance_score: float
    strength: SignalStrength
    ev: float  # §2.1: visible siempre junto a la señal
    # p-valor del χ² YA corregido por comparaciones múltiples (Benjamini-Hochberg,
    # §2.4). Es el que sostiene la decisión de activar la señal; el crudo no viaja
    # a la UI porque leerlo como significancia sobreestima lo que la familia de
    # pruebas respalda. null si el χ² no está activo para esa categoría.
    chi_square_pvalue_adjusted: Optional[float] = None


class StatisticalSuggestionsPanel(BaseModel):
    window_size_used: int
    top: list[StatisticalSuggestionItem] = []          # top 3 por significance_score
    all_categories: dict[str, list[StatisticalSuggestionItem]] = {}  # vista completa


class StreakAlert(BaseModel):
    category: str
    option_label: str
    consecutive_count: int
    probability_of_streak: float


class BankrollUpdate(BaseModel):
    """Estado de banca tras registrar un giro."""
    bankroll_current: float
    strategy_stage: int
    next_suggested_bet: float


class BankrollAlertLevel(str, Enum):
    info = "info"
    caution = "caution"
    critical = "critical"


class BankrollAlertResponse(BaseModel):
    """Alerta de gestión de banca: habla del dinero, nunca del próximo resultado."""
    code: str
    level: BankrollAlertLevel
    message: str


class NextStepResponse(BaseModel):
    """Dónde queda la progresión si el giro cierra en contra o a favor.

    Es condicional: describe los dos casos, nunca cuál va a ocurrir.
    """
    stage: int
    bet_per_sector: float
    suggested_bet: float
    bankroll_after: float         # suponiendo que se apostó lo que pide la progresión
    exceeds_table_limit: bool
    exceeds_bankroll: bool
    reaches_loss_limit: bool      # False si la sesión no tiene límite de pérdida


class BankrollSuggestionResponse(BaseModel):
    """Tamaño de apuesta que exige el escalón actual de la progresión.

    Sugiere *cuánto* arriesgar según la progresión que el usuario eligió; nunca
    a qué apostar ni qué resultado esperar.
    """
    strategy: BankrollStrategy
    suggested_bet: float          # total del giro, sumando todos los sectores
    bet_per_sector: float         # en modo dos-sectores, la apuesta por docena/columna
    sectors: int                  # 1 en modo 1:1, 2 en modo dos-sectores
    stage: int
    cumulative_risked: float      # perdido si fallaron todos los escalones hasta aquí
    # Con cuánto queda la serie completa si este giro se gana. En la progresión
    # de dos sectores es 0 del escalón 2 en adelante: recupera, no deja ganancia.
    net_result_if_won: float
    recovers_only_to_break_even: bool
    exceeds_table_limit: bool
    exceeds_bankroll: bool
    risk_warning: Optional[str] = None
    ruin_probability_estimate: Optional[float] = None
    # Recordatorio fijo: ninguna progresión altera la ventaja de la casa (§2.8).
    disclaimer: str
    next_if_lost: NextStepResponse
    next_if_won: NextStepResponse
    # Escalones seguidos, contando el actual, que la banca actual puede pagar.
    stages_supported: int
    # Ordenadas de la más grave a la menos grave.
    alerts: list[BankrollAlertResponse] = []


class EligibleBetResponse(BaseModel):
    """Una apuesta compatible con el modo de la estrategia de la sesión.

    Existe para que la interfaz pueda preguntar "¿sobre qué apuesta calculo el
    riesgo?" sin recalcular ninguna probabilidad por su cuenta: la teórica la
    entrega el motor.
    """
    id: str
    label: str
    category_id: str
    group_ids: list[str]
    theoretical_probability: float


class ProgressionRowResponse(BaseModel):
    """Una fila de la tabla de riesgo, con montos reales del usuario."""
    stage: int
    bet_per_sector: float
    total_bet: float
    cumulative_loss: float
    exceeds_table_limit: bool
    exceeds_bankroll: bool


class ProgressionTableResponse(BaseModel):
    """Tabla que se muestra ANTES de activar una estrategia (§2.8).

    El riesgo debe ser visible y no abstracto: el usuario ve en pesos lo que
    cuesta cada escalón antes de comprometerse con la progresión.
    """
    strategy: BankrollStrategy
    base_bet: float
    sectors: int
    rows: list[ProgressionRowResponse]
    max_affordable_stages: int
    ruin_probability_estimate: Optional[float] = None
    disclaimer: str


class SuggestionSnapshot(BaseModel):
    """Para GET /sessions/:id/suggestions/history"""
    spin_id: UUID
    spin_index: int
    created_at: datetime
    panel: StatisticalSuggestionsPanel
    bankroll: Optional[BankrollSuggestionResponse] = None


# ---------- Respuesta compuesta de POST /spins ----------

class SpinCreationResponse(BaseModel):
    """Respuesta completa al ingresar un spin: spin + apuesta resuelta (si había)
    + bankroll actualizado + panel estadístico recalculado + alerta de racha."""
    spin: SpinResponse
    bet_resolution: Optional[BetResolution] = None
    bankroll_updated: Optional[BankrollUpdate] = None
    statistical_suggestions: StatisticalSuggestionsPanel
    streak_alert: Optional[StreakAlert] = None
