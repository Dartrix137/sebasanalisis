"use client";

/**
 * Piezas de presentación de una variante que comparten el inicio
 * (`/dashboard`) y la página de un juego (`/juegos/[slug]`): su nombre, una
 * ficha de número con el tono de la mesa y la tarjeta para abrir una mesa.
 */

import { Button } from "@/components/ui";
import { TONE_CLASSES, toneOf } from "@/lib/outcomes";
import type { GameVariantResponse } from "@/lib/types/games";

/** Nombres de las variantes precargadas; cualquier otra usa el suyo tal cual. */
const VARIANT_LABEL: Record<string, string> = {
  european: "Europea",
  american: "Americana",
};

export function variantLabel(v: GameVariantResponse | undefined): string {
  if (!v) return "Variante";
  return VARIANT_LABEL[v.name] ?? v.name.charAt(0).toUpperCase() + v.name.slice(1);
}

export function NumberChip({
  value,
  variant,
  large = false,
  index = 0,
}: {
  value: string;
  variant: GameVariantResponse | undefined;
  large?: boolean;
  index?: number;
}) {
  const tone = variant ? toneOf(variant.config, value) : "neutral";
  return (
    <li
      style={large ? { animationDelay: `${index * 45}ms` } : undefined}
      className={`flex shrink-0 items-center justify-center rounded-full font-display font-semibold tabular-nums ${
        TONE_CLASSES[tone]
      } ${large ? "h-10 w-10 text-lg motion-safe:animate-chip-in sm:h-11 sm:w-11" : "h-6 w-6 text-xs"}`}
    >
      {value}
    </li>
  );
}

/**
 * Cada variante se distingue por lo que de verdad la separa. En la ruleta son
 * los ceros, que la pista de presentación pinta de verde: el doble cero es
 * exactamente lo que sube la ventaja de la casa de la americana. Un juego sin
 * resultados en verde no muestra fichas.
 */
export function VariantChoice({
  variant,
  lowestEdge,
  selected,
  primary,
  onStart,
}: {
  variant: GameVariantResponse;
  lowestEdge: boolean;
  selected: boolean;
  /** Dorado solo si abrir mesa es la acción principal (no hay otra abierta). */
  primary: boolean;
  onStart: () => void;
}) {
  const destacados = variant.config.possible_outcomes.filter(
    (o) => toneOf(variant.config, o) === "green",
  );

  return (
    <li
      className={`flex flex-col rounded-card border bg-ink-raised p-5 transition-colors ${
        selected ? "border-gold/60" : "border-edge"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-display text-3xl font-semibold leading-none">
            {variantLabel(variant)}
          </h3>
          <p className="mt-2 text-sm text-muted">
            {variant.description ||
              `${variant.config.possible_outcomes.length} resultados posibles`}
          </p>
        </div>
        {destacados.length > 0 ? (
          <ul className="flex gap-1" aria-hidden="true">
            {destacados.map((c) => (
              <NumberChip key={c} value={c} variant={variant} large />
            ))}
          </ul>
        ) : null}
      </div>

      <div className="mt-5 flex items-baseline gap-2">
        <span className="font-display text-2xl font-semibold tabular-nums">
          {(variant.house_edge * 100).toFixed(2).replace(".", ",")} %
        </span>
        <span className="text-sm text-muted">de ventaja para la casa</span>
      </div>
      <p className="mt-1 min-h-[1.25rem] text-xs text-muted">
        {lowestEdge ? "La ventaja más baja de las disponibles." : ""}
      </p>

      <Button
        className="mt-4"
        variant={primary ? "primary" : "ghost"}
        onClick={onStart}
        disabled={selected}
      >
        {selected ? "Configurando abajo" : `Abrir mesa ${variantLabel(variant).toLowerCase()}`}
      </Button>
    </li>
  );
}
