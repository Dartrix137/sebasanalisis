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
