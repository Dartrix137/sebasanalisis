/**
 * Espejo manual de `backend/app/schemas/spins.py`.
 * Cambios en el schema Pydantic se replican aquí en el mismo commit
 * (skill `api-schema-sync`).
 */

import type { UUID } from "./auth";

/** Ambos son ingreso manual: el proyecto no lee pantallazos (§3.5). */
export type SpinSource = "manual" | "initial_batch";

export interface CreateSpinRequest {
  result_value: string;
  source: SpinSource;
}

/**
 * Cómo escribió el usuario la lista de la carga inicial. Es obligatorio y
 * explícito: el motor pondera por recencia (§2.3), así que invertir el orden en
 * silencio produce un análisis equivocado sin que nada falle visiblemente.
 */
export type EntryOrder = "most_recent_first" | "most_recent_last";

/** Carga inicial de los números ya observados en la mesa (§3.5). */
export interface BulkSpinsRequest {
  values: string[];
  order: EntryOrder;
}

/** Los giros creados, ya en orden cronológico ascendente. */
export interface BulkSpinsResponse {
  created: number;
  spins: SpinResponse[];
}

export interface SpinResponse {
  id: UUID;
  session_id: UUID;
  spin_index: number;
  result_value: string;
  source: SpinSource;
  /**
   * Escalón de la progresión antes de resolver este giro. null si no resolvió
   * apuestas o si después se cambió de estrategia.
   */
  strategy_stage_before: number | null;
  created_at: string; // ISO 8601
}

export interface CategoryDerivedResult {
  category: string;
  option_label: string;
}

export interface SpinWithDerivedCategories extends SpinResponse {
  derived_categories: CategoryDerivedResult[];
}
