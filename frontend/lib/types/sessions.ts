/**
 * Espejo manual de `backend/app/schemas/sessions.py`.
 * Cambios en el schema Pydantic se replican aquí en el mismo commit
 * (skill `api-schema-sync`).
 */

import type { UUID } from "./auth";

export type SessionStatus = "active" | "closed" | "abandoned";

export type BankrollStrategy =
  | "martingale"
  | "dalembert"
  | "fibonacci"
  | "flat"
  | "two_sector_recovery";

export type StrategyMode = "single" | "two_sector";

export interface CreateSessionRequest {
  game_variant_id: UUID;
  name?: string | null;
  window_size: number;
  bankroll_start: number;
  base_bet: number;
  table_limit: number;
  strategy: BankrollStrategy;
  strategy_mode: StrategyMode;
}

export interface UpdateSessionRequest {
  name?: string | null;
  window_size?: number | null;
  strategy?: BankrollStrategy | null;
  strategy_mode?: StrategyMode | null;
  table_limit?: number | null;
}

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
  strategy_selected: BankrollStrategy;
  strategy_mode: StrategyMode;
  strategy_stage: number;
  started_at: string; // ISO 8601
  closed_at: string | null;
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
  strategy_used: BankrollStrategy;
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
