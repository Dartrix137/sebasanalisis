/**
 * Espejo manual de `backend/app/schemas/games.py`.
 * Cambios en el schema Pydantic se replican aquí en el mismo commit
 * (skill `api-schema-sync` — no hay generador automático en el MVP).
 */

import type { UUID } from "./auth";

export interface CategoryGroup {
  label: string | null;
  outcomes: string[];
  payout: number;
  /**
   * Si el grupo entra al catálogo de mercados del motor de recomendación
   * (§2.10). El verde de la ruleta lo pone en false: cubre el 0/00 y no es una
   * zona que el producto recomiende, pero se conserva como grupo para que las
   * frecuencias de color sumen 1 y el χ² tenga todas sus celdas.
   */
  market: boolean;
}

/**
 * Una apuesta a varios grupos de la misma categoría a la vez (dos docenas, dos
 * columnas). Vive en los datos porque es una regla de la mesa, no del motor.
 */
export interface AllowedCombination {
  id: string;
  label: string;
  category_id: string;
  group_ids: string[];
}

export interface GameCategory {
  id: string;
  label: string;
  /** Fuerza del shrinkage bayesiano de esta categoría (§2.2). */
  shrinkage_alpha: number;
  groups: Record<string, CategoryGroup>;
}

export interface GameVariantConfig {
  possible_outcomes: string[];
  categories: GameCategory[];
  /** Orden significativo: es el orden de catálogo del desempate (§2.10). */
  allowed_combinations: AllowedCombination[];
  /** Umbral medio: `signal_score` desde el que la señal es MEDIA. 50 por defecto. */
  recommendation_threshold: number;
  /**
   * Umbral débil: desde aquí hay recomendación (SEÑAL DÉBIL, solo apuesta base).
   * 35 por defecto; nunca mayor que el medio. Igualarlo al medio apaga la débil.
   */
  weak_threshold: number;
}

export interface CreateGameRequest {
  name: string;
  type: string;
  active: boolean;
}

export interface UpdateGameRequest {
  name?: string | null;
  active?: boolean | null;
}

export interface CreateGameVariantRequest {
  name: string;
  house_edge: number;
  config: GameVariantConfig;
  active: boolean;
}

export interface UpdateGameVariantRequest {
  name?: string | null;
  house_edge?: number | null;
  config?: GameVariantConfig | null;
  active?: boolean | null;
}

export interface GameVariantResponse {
  id: UUID;
  game_id: UUID;
  name: string;
  house_edge: number;
  config: GameVariantConfig;
  active: boolean;
}

export interface GameResponse {
  id: UUID;
  name: string;
  type: string;
  active: boolean;
  variants: GameVariantResponse[];
}

/** Detalle de un 422 del validador de configuración del admin. */
export interface ConfigValidationError {
  message: string;
  errors: string[];
}
