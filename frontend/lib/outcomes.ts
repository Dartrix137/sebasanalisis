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
 * Tono de un resultado en el teclado y en la lista de giros, leído de la pista
 * de presentación `display` de la variante (§7.3 de la Fase 4): la categoría
 * que da el tono y el tono de cada uno de sus grupos. Sin pista, o con un
 * grupo sin tono, el resultado va en neutro.
 *
 * Antes se buscaba a mano la categoría `color` y los grupos `red`, `black` y
 * `green`: era la última suposición de ruleta fuera de los datos.
 */
export function toneOf(config: GameVariantConfig, outcome: string): OutcomeTone {
  const category = config.display?.outcome_tone_category;
  if (!category) return "neutral";
  const group = groupOf(config, category, outcome);
  if (!group) return "neutral";
  return config.display?.tones[group] ?? "neutral";
}

/**
 * Columnas fijas de la grilla del teclado, si la pista las trae. Sin ellas, la
 * grilla se ajusta al ancho de la pantalla.
 */
export function keypadColumns(config: GameVariantConfig): number | null {
  return config.display?.columns ?? null;
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
