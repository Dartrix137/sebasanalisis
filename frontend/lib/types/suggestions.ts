/**
 * Espejo manual de `backend/app/schemas/suggestions.py`.
 * Cambios en el schema Pydantic se replican aquí en el mismo commit
 * (skill `api-schema-sync`).
 */

import type { UUID } from "./auth";
import type { BankrollStrategy } from "./sessions";

/** Fuerza de la señal (§2.6). Describe evidencia pasada, nunca certeza futura. */
export type SignalStrength = "strong" | "medium" | "weak";

export interface StatisticalSuggestionItem {
  category: string;
  option_label: string;
  /** Estos dos se muestran SIEMPRE juntos (regla anti-falacia del jugador, §2). */
  theoretical_probability: number;
  observed_frequency_shrunk: number;
  /** Intervalo de Wilson al 95% sobre los conteos crudos (§2.2). */
  observed_ci_low: number;
  observed_ci_high: number;
  deviation: number;
  significance_score: number;
  strength: SignalStrength;
  ev: number;
  /** χ² ya corregido por comparaciones múltiples (§2.4). null si no está activo. */
  chi_square_pvalue_adjusted: number | null;
}

export interface StatisticalSuggestionsPanel {
  window_size_used: number;
  top: StatisticalSuggestionItem[];
  all_categories: Record<string, StatisticalSuggestionItem[]>;
}

export interface StreakAlert {
  category: string;
  option_label: string;
  consecutive_count: number;
  probability_of_streak: number;
}

export type BankrollAlertLevel = "info" | "caution" | "critical";

/** Alerta de gestión de banca: habla del dinero, nunca del próximo resultado. */
export interface BankrollAlertResponse {
  code: string;
  level: BankrollAlertLevel;
  message: string;
}

/** Dónde queda la progresión si el giro cierra en contra o a favor. Condicional. */
export interface NextStepResponse {
  stage: number;
  bet_per_sector: number;
  suggested_bet: number;
  /** Suponiendo que se apostó lo que pide la progresión. */
  bankroll_after: number;
  exceeds_table_limit: boolean;
  exceeds_bankroll: boolean;
  /** false si la sesión no tiene límite de pérdida. */
  reaches_loss_limit: boolean;
}

/**
 * Tamaño de apuesta que exige el escalón actual de la progresión.
 * Sugiere *cuánto* arriesgar, nunca a qué apostar ni qué resultado esperar.
 */
export interface BankrollSuggestionResponse {
  strategy: BankrollStrategy;
  /** Total del giro, sumando todos los sectores. */
  suggested_bet: number;
  /** En modo dos-sectores, la apuesta por docena/columna. */
  bet_per_sector: number;
  /** 1 en modo 1:1, 2 en modo dos-sectores. */
  sectors: number;
  stage: number;
  /** Perdido si fallaron todos los escalones hasta aquí. */
  cumulative_risked: number;
  /**
   * Con cuánto queda la serie completa si este giro se gana. En la progresión
   * de dos sectores es 0 del escalón 2 en adelante: recupera, no deja ganancia.
   */
  net_result_if_won: number;
  recovers_only_to_break_even: boolean;
  exceeds_table_limit: boolean;
  exceeds_bankroll: boolean;
  risk_warning: string | null;
  ruin_probability_estimate: number | null;
  /** Recordatorio fijo: ninguna progresión altera la ventaja de la casa (§2.8). */
  disclaimer: string;
  next_if_lost: NextStepResponse;
  next_if_won: NextStepResponse;
  /** Escalones seguidos, contando el actual, que la banca actual puede pagar. */
  stages_supported: number;
  /** Ordenadas de la más grave a la menos grave. */
  alerts: BankrollAlertResponse[];
}

/**
 * Una apuesta compatible con el modo de la estrategia de la sesión, con su
 * probabilidad teórica ya calculada por el motor: el frontend nunca la deriva.
 */
export interface EligibleBetResponse {
  id: string;
  label: string;
  category_id: string;
  group_ids: string[];
  theoretical_probability: number;
}

/** Una fila de la tabla de riesgo, con montos reales del usuario. */
export interface ProgressionRowResponse {
  stage: number;
  bet_per_sector: number;
  total_bet: number;
  cumulative_loss: number;
  exceeds_table_limit: boolean;
  exceeds_bankroll: boolean;
}

/**
 * Tabla que se muestra ANTES de activar una estrategia (§2.8): el riesgo debe
 * ser visible en pesos, no abstracto.
 */
export interface ProgressionTableResponse {
  strategy: BankrollStrategy;
  base_bet: number;
  sectors: number;
  rows: ProgressionRowResponse[];
  max_affordable_stages: number;
  ruin_probability_estimate: number | null;
  disclaimer: string;
}

export interface SuggestionSnapshot {
  spin_id: UUID;
  spin_index: number;
  created_at: string;
  panel: StatisticalSuggestionsPanel;
  bankroll: BankrollSuggestionResponse | null;
}

// ============================================================================
// Motor de recomendación (Fase 3, §2.10)
// ============================================================================
//
// La pantalla principal muestra esto: un mercado, un `signal_score` y su banda.
// Las frecuencias y probabilidades siguen viajando en la respuesta —regla
// anti-falacia del jugador, §2— pero se pintan en "¿Por qué recomienda esto?".

/** Qué hacer en el giro siguiente. */
export type RecommendationDecision = "RECOMMEND" | "NO_BET";

/**
 * Por qué el motor no recomienda apostar: todavía no hay giros suficientes para
 * medir, o los hay y ningún mercado llega al umbral.
 */
export type NoBetReason = "insufficient_data" | "below_threshold";

/**
 * Estado de salida del motor según los tres umbrales (§2.10):
 * - `none`: SIN SEÑAL — por debajo de `weak_threshold`. No apostar.
 * - `weak`: SEÑAL DÉBIL — de `weak_threshold` a `threshold`. Solo apuesta base.
 * - `medium`: SEÑAL MEDIA — de `threshold` a `strong_threshold`.
 * - `strong`: SEÑAL FUERTE — desde `strong_threshold`.
 * Describe la fuerza del criterio interno sobre la muestra ya ocurrida, no la
 * probabilidad de acertar el próximo giro.
 */
export type SignalBand = "none" | "weak" | "medium" | "strong";

/** Un NO APOSTAR se queda en `PENDING`: no hubo nada que acertar ni que fallar. */
export type RecommendationOutcome = "PENDING" | "HIT" | "MISS";

/** Lo que el mercado hizo dentro de una ventana (10, 20, 50, 100 giros). */
export interface WindowStatResponse {
  window: number;
  spins_used: number;
  /** Regla anti-falacia del jugador (§2): estos dos nunca viajan por separado. */
  theoretical_probability: number;
  observed_frequency_shrunk: number;
  raw_count: number;
  /** Intervalo de Wilson al 95% sobre los conteos crudos (§2.2). */
  observed_ci_low: number;
  observed_ci_high: number;
  deviation: number;
  /** Desviación estandarizada con signo. Positiva = salió más de lo esperado. */
  z: number;
}

/** De dónde sale cada punto del `signal_score`. */
export interface ScoreComponentsResponse {
  /** D: z de la ventana más larga, normalizado a [0,1]. */
  deviation: number;
  /** R: z de la ventana más corta. */
  recency: number;
  /**
   * C: coherencia entre tramos disjuntos del historial. null con un solo tramo
   * — un tramo no tiene con qué ser consistente, y su peso pasa a D y R.
   */
  consistency: number | null;
  weight_deviation: number;
  weight_recency: number;
  weight_consistency: number;
  /** Puntos del respaldo del χ². Solo con ≥200 giros y p corregido < 0.05. */
  chi_square_bonus: number;
}

/** Una alternativa del catálogo de mercados de la variante. */
export interface MarketResponse {
  key: string;
  label: string;
  category_id: string;
  group_ids: string[];
  /** Cuántas zonas cubre a la vez: 1 (negro) o 2 (dos docenas). */
  sectors: number;
  /** Resultados cubiertos. Cambia con la variante: 24/37 vs. 24/38. */
  coverage: number;
  payout: number;
}

export interface ScoredMarketResponse {
  market: MarketResponse;
  signal_score: number;
  signal_band: SignalBand;
  components: ScoreComponentsResponse;
  windows: WindowStatResponse[];
  chi_square_pvalue_adjusted: number | null;
}

/**
 * Lo que una progresión pide para el mercado recomendado. `applicable: false`
 * no es un error: es la respuesta honesta cuando la progresión no encaja con la
 * forma del mercado (recuperación de dos sectores sobre un mercado de uno).
 */
export interface MarketStakeResponse {
  strategy: BankrollStrategy;
  applicable: boolean;
  reason: string | null;
  stage: number;
  bet_per_sector: number;
  total_bet: number;
  sectors: number;
  cumulative_risked: number;
  net_result_if_won: number;
  recovers_only_to_break_even: boolean;
  exceeds_bankroll: boolean;
  exceeds_table_limit: boolean;
}

/**
 * La recomendación para el giro siguiente. `best` viaja también con `NO_BET`:
 * siempre hay un mejor candidato, sólo que por debajo del umbral.
 */
export interface RecommendationResponse {
  session_id: UUID;
  decision: RecommendationDecision;
  /** null con RECOMMEND. */
  no_bet_reason: NoBetReason | null;
  /** Giros por debajo de los cuales un NO_BET es por falta de información. */
  min_spins_for_signal: number;
  /** Umbral medio: desde aquí la señal es MEDIA. */
  threshold: number;
  /** Umbral débil: desde aquí hay recomendación (SEÑAL DÉBIL, solo apuesta base). */
  weak_threshold: number;
  /** Umbral alto: desde aquí la señal es FUERTE. */
  strong_threshold: number;
  signal_score: number;
  signal_band: SignalBand;
  /** El mercado a apostar. null con NO_BET. */
  market: MarketResponse | null;
  best: ScoredMarketResponse | null;
  /** Las tres progresiones sobre el mercado. Vacío con NO_BET. */
  stakes: MarketStakeResponse[];
  /** Todos los mercados evaluados, ya ordenados por el desempate. */
  candidates: ScoredMarketResponse[];
  window_size_used: number;
  total_spins: number;
  /** Recordatorio fijo al pie de la tarjeta (§2.10). */
  disclaimer: string;
}

/** Una recomendación ya emitida y su cierre — historial y auto-evaluación. */
export interface RecommendationRecord {
  id: UUID;
  session_id: UUID;
  spin_id: UUID | null;
  decision: RecommendationDecision;
  market_key: string;
  category: string;
  option_label: string;
  signal_score: number;
  signal_band: SignalBand;
  theoretical_probability: number;
  observed_frequency_shrunk: number;
  deviation: number;
  observed_ci_low: number;
  observed_ci_high: number;
  ev: number;
  chi_square_pvalue_adjusted: number | null;
  /** Monto en centavos, nunca float. null con NO_BET. */
  stake_cents: number | null;
  currency: string;
  outcome: RecommendationOutcome;
  resolved_spin_id: UUID | null;
  window_size_used: number;
  created_at: string; // ISO 8601
}

// ---------- Métricas internas del motor (solo admin, §2.10) ----------
//
// No se muestran al cliente: son el control de honestidad de §9 del comparativo,
// el que dice si el motor aporta información útil o sólo describe el pasado.

/** Sobre qué historiales corre el backtest. */
export type BacktestSource = "sessions" | "simulated";

export interface BacktestTally {
  recommendations: number;
  hits: number;
  misses: number;
  hit_rate: number;
  /** Resultado neto en unidades de apuesta base, con los pagos reales. */
  units: number;
  /** Resultado por unidad arriesgada. En una mesa sin sesgo tiende a −house_edge. */
  roi: number;
  /** Peor caída desde un pico previo, en unidades. */
  max_drawdown: number;
}

export interface BacktestBandRow extends BacktestTally {
  band: SignalBand;
  /** Cuántos NO APOSTAR salieron con esta banda en el mejor candidato. */
  no_bets: number;
}

export interface BacktestReport {
  source: string;
  sessions: number;
  spins_evaluated: number;
  decisions: number;
  recommendations: number;
  no_bets: number;
  no_bet_rate: number;
  /** Umbral medio (SEÑAL MEDIA) aplicado. */
  threshold: number;
  /** Umbral débil (mínimo para recomendar) aplicado. */
  weak_threshold: number;
  overall: BacktestTally;
  by_band: BacktestBandRow[];
  /** EV de cualquier apuesta en esta variante: la referencia del ROI. */
  house_edge_reference: number;
}
