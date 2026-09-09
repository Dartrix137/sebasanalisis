/**
 * Derivación de categorías a partir de `categories_json`, solo para presentación.
 *
 * El backend no devuelve las categorías derivadas de un giro en el paso 5: el
 * frontend ya tiene la configuración completa de la variante, así que pintar un
 * número de rojo o verde es una lectura local, no una llamada de red.
 *
 * Nada de esto es lógica estadística: eso vive en `backend/app/engine/` y nunca
 * se duplica aquí.
 */

import type { GameVariantConfig } from "./types/games";

/** Devuelve el grupo al que pertenece un resultado dentro de una categoría. */
export function groupOf(
  config: GameVariantConfig,
  categoryId: string,
  outcome: string,
): string | null {
  const category = config.categories.find((c) => c.id === categoryId);
  if (!category) return null;
  for (const [groupId, group] of Object.entries(category.groups)) {
    if (group.outcomes.includes(outcome)) return groupId;
  }
  return null;
}

export type OutcomeTone = "red" | "black" | "green" | "neutral";

/**
 * Color de mesa de un resultado, leído de la categoría `color` si la variante
 * la define. Un juego sin categoría `color` (dados, por ejemplo) cae en
 * "neutral" sin romperse.
 */
export function toneOf(config: GameVariantConfig, outcome: string): OutcomeTone {
  const group = groupOf(config, "color", outcome);
  if (group === "red" || group === "black" || group === "green") return group;
  return "neutral";
}

export const TONE_CLASSES: Record<OutcomeTone, string> = {
  red: "bg-table-red text-white",
  black: "bg-table-black text-white border border-edge",
  green: "bg-table-green text-white",
  neutral: "bg-ink-sunken text-white border border-edge",
};

/** Etiqueta legible de cada categoría para un resultado, ej. "Color: Rojo". */
export function describeOutcome(
  config: GameVariantConfig,
  outcome: string,
): { category: string; option: string }[] {
  return config.categories.flatMap((cat) => {
    const groupId = groupOf(config, cat.id, outcome);
    if (!groupId) return [];
    const group = cat.groups[groupId];
    return [{ category: cat.label, option: group.label ?? groupId }];
  });
}
