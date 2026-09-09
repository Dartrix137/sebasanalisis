/**
 * Espejo manual de `backend/app/schemas/bets.py`.
 * Cambios en el schema Pydantic se replican aquí en el mismo commit
 * (skill `api-schema-sync`).
 */

import type { UUID } from "./auth";

export type BetStatus = "pending" | "resolved" | "cancelled";

export interface CreateBetRequest {
  category: string;
  option_label: string;
  amount: number;
  /**
   * Nota del usuario sobre su propia decisión: si eligió esta opción después de
   * ver una señal. No implica que la señal anticipara el resultado.
   */
  followed_suggestion: boolean;
}

export interface BetResponse {
  id: UUID;
  session_id: UUID;
  spin_id: UUID | null;
  category: string;
  option_label: string;
  amount: number;
  followed_suggestion: boolean;
  status: BetStatus;
  won: boolean | null;
  /** Total devuelto por la mesa: lo apostado más la ganancia. Cero si se perdió. */
  payout: number | null;
  net_change: number | null;
  created_at: string; // ISO 8601
  resolved_at: string | null;
}

export interface BetResolution {
  bet_id: UUID;
  category: string;
  option_label: string;
  won: boolean;
  amount: number;
  payout: number;
  net_change: number;
  followed_suggestion: boolean;
}
