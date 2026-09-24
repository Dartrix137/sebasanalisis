"""
Schemas: Statistical suggestions & Bankroll suggestions
"""
from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.schemas.sessions import BankrollStrategy


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


# ============================================================================
# Motor de recomendación (Fase 3, §2.10)
# ============================================================================
#
# Lo que la pantalla principal muestra es esto: un mercado, un `signal_score` y
# su banda. Las frecuencias y probabilidades siguen viajando en la respuesta
# —regla anti-falacia del jugador, §2— pero se pintan en la sección desplegable
# "¿Por qué recomienda esto?", no en la tarjeta principal.


class RecommendationDecision(str, Enum):
    """Qué hacer en el giro siguiente."""
    recommend = "RECOMMEND"
    no_bet = "NO_BET"


class NoBetReason(str, Enum):
    """Por qué el motor no recomienda apostar. null cuando sí recomienda."""
    # Menos giros que la ventana más corta: todavía no hay con qué medir.
    insufficient_data = "insufficient_data"
    # Hay datos, pero ningún mercado llega al umbral.
    below_threshold = "below_threshold"


class SignalBand(str, Enum):
    """Estado de salida del motor según los dos umbrales de §2.10:

    - `weak`: SIN SEÑAL — por debajo del umbral mínimo (`threshold`). No apostar.
    - `medium`: SEÑAL MEDIA — del umbral mínimo al alto (`strong_threshold`).
    - `strong`: SEÑAL FUERTE — desde el umbral alto.

    Describe la fuerza del criterio interno sobre la muestra ya ocurrida. No es
    la probabilidad de acertar el próximo giro — esa sigue siendo la teórica.
    """
    weak = "weak"
    medium = "medium"
    strong = "strong"


class RecommendationOutcome(str, Enum):
    """Cómo cerró una recomendación contra el giro siguiente.

    Un NO APOSTAR se queda en `PENDING`: no hubo nada que acertar ni que fallar.
    """
    pending = "PENDING"
    hit = "HIT"
    miss = "MISS"


class WindowStatResponse(BaseModel):
    """Lo que el mercado hizo dentro de una ventana (10, 20, 50, 100 giros)."""
    window: int
    spins_used: int
    # Regla anti-falacia del jugador (§2): estos dos nunca viajan por separado.
    theoretical_probability: float
    observed_frequency_shrunk: float
    raw_count: int
    # Intervalo de Wilson al 95% sobre los conteos crudos (§2.2): la escala del
    # ruido. Se muestra, no se interpreta.
    observed_ci_low: float
    observed_ci_high: float
    deviation: float
    # Desviación estandarizada con signo. Positiva = salió más de lo esperado.
    z: float


class ScoreComponentsResponse(BaseModel):
    """De dónde sale cada punto del `signal_score`.

    Se expone entero para que "¿Por qué recomienda esto?" pueda mostrar el
    desglose en vez de un número sin origen.
    """
    deviation: float            # D: z de la ventana más larga, normalizado a [0,1]
    recency: float              # R: z de la ventana más corta
    # C: coherencia entre tramos disjuntos del historial. null cuando hay un solo
    # tramo — un tramo no tiene con qué ser consistente, y entonces su peso se
    # reparte entre D y R.
    consistency: Optional[float] = None
    weight_deviation: float
    weight_recency: float
    weight_consistency: float
    # Puntos que suma el respaldo del χ². Solo con ≥200 giros y p corregido por
    # Benjamini-Hochberg < 0.05 (§2.4).
    chi_square_bonus: float


class MarketResponse(BaseModel):
    """Una alternativa del catálogo de mercados de la variante."""
    key: str
    label: str
    category_id: str
    group_ids: list[str]
    # Cuántas zonas cubre a la vez: 1 (negro) o 2 (dos docenas).
    sectors: int
    # Cuántos resultados cubre. Cambia con la variante: 24/37 europea, 24/38
    # americana para dos docenas.
    coverage: int
    payout: float


class ScoredMarketResponse(BaseModel):
    market: MarketResponse
    signal_score: float
    signal_band: SignalBand
    components: ScoreComponentsResponse
    windows: list[WindowStatResponse]
    chi_square_pvalue_adjusted: Optional[float] = None


class MarketStakeResponse(BaseModel):
    """Lo que una progresión pide para el mercado recomendado.

    `applicable=false` no es un error: es la respuesta honesta cuando la
    progresión no encaja con la forma del mercado (la recuperación de dos
    sectores sobre un mercado de un solo sector).
    """
    strategy: BankrollStrategy
    applicable: bool
    reason: Optional[str] = None
    stage: int
    bet_per_sector: float
    total_bet: float
    sectors: int
    cumulative_risked: float
    net_result_if_won: float
    recovers_only_to_break_even: bool
    exceeds_bankroll: bool
    exceeds_table_limit: bool


class RecommendationResponse(BaseModel):
    """La recomendación para el giro siguiente.

    `best` viaja también con `NO_BET`: siempre hay un mejor candidato, sólo que
    por debajo del umbral. Es lo que permite explicar por qué el motor calló.
    """
    session_id: UUID
    decision: RecommendationDecision
    # null con RECOMMEND.
    no_bet_reason: Optional[NoBetReason] = None
    # Giros por debajo de los cuales un NO_BET es por falta de información.
    min_spins_for_signal: int
    # Umbral mínimo: desde aquí hay recomendación (SEÑAL MEDIA).
    threshold: float
    # Umbral alto: desde aquí la señal es FUERTE.
    strong_threshold: float
    signal_score: float
    signal_band: SignalBand
    # El mercado a apostar. null con NO_BET.
    market: Optional[MarketResponse] = None
    # El mejor candidato, haya o no recomendación.
    best: Optional[ScoredMarketResponse] = None
    # Las tres progresiones sobre el mercado recomendado, en orden de menú.
    # Vacío con NO_BET: no hay monto que calcular.
    stakes: list[MarketStakeResponse] = []
    # Todos los mercados evaluados, ya ordenados por el desempate. Alimenta la
    # sección desplegable.
    candidates: list[ScoredMarketResponse] = []
    window_size_used: int
    total_spins: int
    # Recordatorio fijo al pie de la tarjeta (§2.10).
    disclaimer: str


class RecommendationRecord(BaseModel):
    """Una recomendación ya emitida y su cierre — historial y auto-evaluación."""
    id: UUID
    session_id: UUID
    spin_id: Optional[UUID] = None
    decision: RecommendationDecision
    market_key: str
    category: str
    option_label: str
    signal_score: float
    signal_band: SignalBand
    theoretical_probability: float
    observed_frequency_shrunk: float
    deviation: float
    observed_ci_low: float
    observed_ci_high: float
    ev: float
    chi_square_pvalue_adjusted: Optional[float] = None
    # Monto en centavos, nunca float. null con NO_BET.
    stake_cents: Optional[int] = None
    currency: str
    outcome: RecommendationOutcome
    resolved_spin_id: Optional[UUID] = None
    window_size_used: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- Métricas internas del motor (solo admin, §2.10) ----------
#
# No se muestran al cliente: son el control de honestidad de §9 del comparativo,
# el que dice si el motor aporta información útil o sólo describe el pasado.


class BacktestTally(BaseModel):
    """Resultado acumulado de un grupo de recomendaciones."""
    recommendations: int
    hits: int
    misses: int
    hit_rate: float
    # Resultado neto en unidades de apuesta base, con los pagos reales
    # (1:1, 2:1, y 1:2 para dos docenas).
    units: float
    # Resultado por unidad arriesgada. En una mesa sin sesgo tiende a −house_edge.
    roi: float
    # Peor caída desde un pico previo, en unidades.
    max_drawdown: float


class BacktestBandRow(BacktestTally):
    band: SignalBand
    # Cuántos NO APOSTAR salieron con esta banda en el mejor candidato.
    no_bets: int


class BacktestReport(BaseModel):
    """Informe del backtest sobre historiales fuera de calibración."""
    source: str
    sessions: int
    spins_evaluated: int
    decisions: int
    recommendations: int
    no_bets: int
    no_bet_rate: float
    threshold: float
    overall: BacktestTally
    by_band: list[BacktestBandRow]
    # EV de cualquier apuesta en esta variante: la referencia contra la que se
    # lee el ROI. Un ROI cercano a esto es el resultado esperado, no un fallo.
    house_edge_reference: float
