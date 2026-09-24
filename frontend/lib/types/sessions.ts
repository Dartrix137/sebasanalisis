/**
 * Espejo manual de `backend/app/schemas/sessions.py`.
 * Cambios en el schema Pydantic se replican aquí en el mismo commit
 * (skill `api-schema-sync`).
 */

import type { UUID } from "./auth";

export type SessionStatus = "active" | "closed" | "abandoned";

/**
 * Las tres progresiones que ofrece la mesa (§2.10). Desde la Fase 3 la sesión
 * no elige una al crearse: la vista de ruleta las muestra a la vez con lo que
 * pide cada una. D'Alembert y Fibonacci salieron del producto.
 */
export type BankrollStrategy = "flat" | "martingale" | "two_sector_recovery";

export interface CreateSessionRequest {
  game_variant_id: UUID;
  name?: string | null;
  window_size: number;
  bankroll_start: number;
  base_bet: number;
  table_limit: number;
  /** Pérdida neta en la que el usuario decide detenerse. Opcional. */
  loss_limit?: number | null;
}

export interface UpdateSessionRequest {
  name?: string | null;
  window_size?: number | null;
  table_limit?: number | null;
  /** Se puede fijar o bajar; subirlo o quitarlo con la sesión abierta da 422. */
  loss_limit?: number | null;
}

/** Por qué la mesa dejó de ofrecer apuestas. */
export type StopReason = "bankroll_exhausted" | "loss_limit_reached";

export interface SessionResponse {
  id: UUID;
  user_id: UUID;
  game_variant_id: UUID;
  name: string | null;
  status: SessionStatus;
  window_size: number;
  bankroll_start: number;
  bankroll_current: number;
  base_bet: number;
  table_limit: number;
  loss_limit: number | null;
  /**
   * Un escalón por progresión: las tres corren a la vez y el usuario sigue la
   * que quiera (§2.10). La plana no tiene escalón porque no tiene progresión.
   */
  stage_martingale: number;
  stage_two_sector: number;
  started_at: string; // ISO 8601
  closed_at: string | null;
  /**
   * null mientras se pueda apostar. Con valor, la mesa sigue abierta pero no
   * acepta apuestas: la banca no cubre la apuesta base o se alcanzó el límite
   * de pérdida. Lo calcula el servidor; deshacer el giro que lo provocó lo
   * levanta solo.
   */
  stop_reason: StopReason | null;
}

/** Resumen de la sesión (§4). Solo describe lo que ya pasó. */
export interface SessionSummaryResponse {
  session_id: UUID;
  duration_minutes: number;
  total_spins: number;
  total_bets: number;
  /** Proporción de apuestas resueltas que se ganaron. No es una tasa del motor. */
  win_rate: number;
  bankroll_start: number;
  bankroll_final: number;
  net_change: number;
  /** Peor caída desde un pico previo: un neto final en cero puede esconderla. */
  max_drawdown: number;
  followed_suggestion_rate: number;
}

export interface SessionPerformanceResponse {
  session_id: UUID;
  total_suggestions: number;
  matched_suggestions: number;
  match_rate: number;
  baseline_matched: number;
  baseline_match_rate: number;
  verdict: string;
  updated_at: string;
}
