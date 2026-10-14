/**
 * Registro de módulos del frontend (§7.3 de la Fase 4): qué pantalla juega una
 * mesa según el `module` de su juego. Es el par de `backend/app/api/game_modules.py`.
 *
 * `sports` está reservado (§8.2) y no tiene pantalla. Un juego nuevo de
 * resultados discretos no necesita nada aquí: lo juega `DiscreteOutcomeSession`
 * con su `categories_json`.
 */

import type { ComponentType } from "react";

import { DiscreteOutcomeSession } from "@/components/mesa/DiscreteOutcomeSession";
import type { GameModule } from "@/lib/types/games";

export type SessionScreen = ComponentType<{ sessionId: string }>;

export const SESSION_SCREENS: Record<GameModule, SessionScreen | null> = {
  discrete_outcome: DiscreteOutcomeSession,
  sports: null,
};
