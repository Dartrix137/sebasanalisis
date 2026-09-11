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

export interface BankrollUpdate {
  bankroll_current: number;
  strategy_stage: number;
  next_suggested_bet: number;
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
