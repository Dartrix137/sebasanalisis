"use client";

/**
 * Tablero de señales: el elemento principal de la vista de ruleta (§2.6).
 *
 * Cada señal se dibuja como una pista de comparación en vez de una rejilla de
 * cifras. La probabilidad teórica es una marca fija que siempre cae en el mismo
 * punto de la pista, y lo observado es una barra que la cruza o se queda corta.
 * Dos motivos:
 *
 * 1. Se lee de un vistazo. Quien está de pie en una mesa tiene segundos, no
 *    tiempo para restar dos porcentajes.
 * 2. Refuerza la regla anti-falacia del jugador (§2) mejor que dos números
 *    juntos: la referencia que gobierna el próximo giro está dibujada como una
 *    marca inmóvil, y la barra que se mueve es solo el pasado.
 *
 * La barra se escala por razón (observado ÷ teórico), no sobre 0-100 %: así una
 * apuesta de 2.7 % y una de 48.6 % se comparan con el mismo gesto visual.
 */

import { Card, InfoTip } from "@/components/ui";
import type {
  SignalStrength,
  StatisticalSuggestionItem,
  StatisticalSuggestionsPanel,
  StreakAlert,
} from "@/lib/types/suggestions";

const PCT = (n: number) => `${(n * 100).toFixed(1)} %`;

const STRENGTH_LABEL: Record<SignalStrength, string> = {
  strong: "Fuerte",
  medium: "Media",
  weak: "Débil",
};

const STRENGTH_TEXT: Record<SignalStrength, string> = {
  strong: "text-signal-strong",
  medium: "text-signal-medium",
  weak: "text-muted",
};

const STRENGTH_BAR: Record<SignalStrength, string> = {
  strong: "bg-signal-strong",
  medium: "bg-signal-medium",
  weak: "bg-muted",
};

/** Dónde cae la marca de lo esperado dentro de la pista. */
const TICK = 50;

export function SignalBoard({
  panel,
  streak,
  categoryLabels,
}: {
  panel: StatisticalSuggestionsPanel | null;
  streak: StreakAlert | null;
  categoryLabels: Record<string, string>;
}) {
  const teoricaDeLaRacha =
    streak && panel
      ? panel.all_categories[streak.category]?.find(
          (i) => i.option_label === streak.option_label,
        )?.theoretical_probability
      : undefined;

  return (
    <Card>
      <header className="mb-4">
        <h2 className="text-base font-bold text-white">
          Señales
          <InfoTip label="cómo leer las señales">
            La marca blanca es lo que la mesa da de por sí y no se mueve nunca: es la
            que gobierna el próximo giro. La barra es lo que ya salió, moderado cuando
            hay pocos giros. Que la barra pase la marca describe el pasado — no
            significa que vaya a seguir, ni que a lo otro «ya le toque».
          </InfoTip>
        </h2>
        <p className="mt-1 text-sm text-muted">
          Lo que ya salió, comparado con lo que la mesa da de por sí.
        </p>
      </header>

      {/* La racha es una alerta: solo aparece cuando hay una. */}
      {streak ? (
        <p className="mb-4 rounded-lg border border-signal-medium/40 bg-signal-medium/10 px-3.5 py-2.5 text-xs leading-relaxed text-white">
          <span className="font-bold">
            {categoryLabels[streak.category] ?? streak.category}: {streak.option_label}
          </span>{" "}
          se repitió {streak.consecutive_count} veces seguidas. Que se diera esa racha
          tenía un {PCT(streak.probability_of_streak)} de probabilidad
          {teoricaDeLaRacha !== undefined ? (
            <>
              , y el próximo giro sigue en {PCT(teoricaDeLaRacha)}: no cambia por la
              racha
            </>
          ) : null}
          .
        </p>
      ) : null}

      {!panel || panel.top.length === 0 ? (
        <p className="rounded-lg border border-dashed border-edge py-8 text-center text-sm text-muted">
          Registra números y aquí verás cómo se está separando la mesa de lo esperado.
        </p>
      ) : (
        <ol className="space-y-4">
          {panel.top.map((item) => (
            <SignalTrack
              key={`${item.category}-${item.option_label}`}
              item={item}
              categoryLabel={categoryLabels[item.category] ?? item.category}
            />
          ))}
        </ol>
      )}
    </Card>
  );
}

function SignalTrack({
  item,
  categoryLabel,
}: {
  item: StatisticalSuggestionItem;
  categoryLabel: string;
}) {
  const razon =
    item.theoretical_probability > 0
      ? item.observed_frequency_shrunk / item.theoretical_probability
      : 0;
  const ancho = Math.min(razon * TICK, 100);
  const porEncima = item.observed_frequency_shrunk > item.theoretical_probability;
  const rendimiento = item.ev * 1000;

  return (
    <li>
      <div className="flex items-baseline justify-between gap-3">
        <h4 className="text-base font-bold text-white">
          {item.option_label}
          <span className="ml-2 text-xs font-normal text-muted">{categoryLabel}</span>
        </h4>
        <span className={`text-xs font-bold ${STRENGTH_TEXT[item.strength]}`}>
          {STRENGTH_LABEL[item.strength]}
        </span>
      </div>

      {/* Pista: la marca de lo esperado no se mueve nunca. */}
      <div
        className="relative mt-2 h-2.5 rounded-full bg-ink"
        role="img"
        aria-label={`Observada ${PCT(item.observed_frequency_shrunk)}, esperada ${PCT(
          item.theoretical_probability,
        )}`}
      >
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${STRENGTH_BAR[item.strength]} ${
            porEncima ? "" : "opacity-60"
          }`}
          style={{ width: `${ancho}%` }}
        />
        <div
          className="absolute inset-y-[-3px] w-px bg-white/70"
          style={{ left: `${TICK}%` }}
        />
      </div>

      <div className="mt-1.5 flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
        <span className="text-muted">
          <span className="font-bold text-white">
            {PCT(item.observed_frequency_shrunk)}
          </span>{" "}
          salió · {PCT(item.theoretical_probability)} da la mesa
        </span>
        <span
          className={`tabular-nums ${
            rendimiento >= 0 ? "text-signal-strong" : "text-muted"
          }`}
        >
          {rendimiento >= 0 ? "+" : "−"}$ {Math.abs(rendimiento).toFixed(0)} por $1.000
        </span>
      </div>
    </li>
  );
}
