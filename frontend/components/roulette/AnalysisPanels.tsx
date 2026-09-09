"use client";

/**
 * Paneles de análisis de la sesión (§2.4 a §2.7).
 *
 * Reglas de producto que este archivo hace cumplir visualmente:
 * - Toda frecuencia observada se muestra junto a su probabilidad teórica.
 * - El valor esperado se muestra siempre junto a la señal, en pesos por cada
 *   $1.000 apostados: "EV = -0.234" no le dice nada a quien no es estadístico.
 * - Cada métrica lleva su explicación en un InfoTip: la jerga sin explicar
 *   invita a interpretaciones equivocadas, que es justo lo que §0 quiere evitar.
 * - Las señales débiles se etiquetan como débiles, nunca se ocultan.
 * - La racha recuerda explícitamente que el próximo giro no cambia.
 */

import type { ReactNode } from "react";

import { Badge, Card, CardHeader, InfoTip } from "@/components/ui";
import type { SessionPerformanceResponse } from "@/lib/types/sessions";
import type {
  SignalStrength,
  StatisticalSuggestionItem,
  StatisticalSuggestionsPanel,
  StreakAlert,
} from "@/lib/types/suggestions";

const PCT = (n: number) => `${(n * 100).toFixed(1)} %`;
const SIGNED = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(3)}`;

const STRENGTH_LABEL: Record<SignalStrength, string> = {
  strong: "FUERTE",
  medium: "MEDIA",
  weak: "DÉBIL",
};

const STRENGTH_CLASS: Record<SignalStrength, string> = {
  strong: "border-signal-strong/60 text-signal-strong",
  medium: "border-signal-medium/60 text-signal-medium",
  weak: "border-muted/40 text-muted",
};

export function AllCategoriesPanel({
  panel,
  categoryLabels,
}: {
  panel: StatisticalSuggestionsPanel | null;
  categoryLabels: Record<string, string>;
}) {
  if (!panel || Object.keys(panel.all_categories).length === 0) {
    return (
      <Card>
        <p className="py-6 text-center text-sm text-muted">
          Todavía no hay giros que describir.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <p className="mb-4 text-sm leading-relaxed text-muted">
        La vista completa, señales débiles incluidas. No se ocultan: una señal débil
        es información —dice que ahí no hay nada que destacar— y esconderla dejaría
        ver solo lo que parece llamativo.
      </p>

      <div className="space-y-4">
        {Object.entries(panel.all_categories).map(([categoryId, items]) => (
          <div key={categoryId}>
            <h4 className="mb-1.5 text-sm font-bold text-white">
              {categoryLabels[categoryId] ?? categoryId}
            </h4>
            <ul className="space-y-1.5">
              {items.map((item) => (
                <SignalRow
                  key={`${item.category}-${item.option_label}`}
                  item={item}
                  categoryLabel={categoryLabels[categoryId] ?? categoryId}
                  compact
                />
              ))}
            </ul>
          </div>
        ))}
      </div>

      <p className="mt-4 text-xs leading-relaxed text-muted">
        Motor en versión núcleo — más señales estadísticas próximamente. El rendimiento
        de cualquier apuesta en una mesa sin sesgo real es negativo: lo que se muestra
        es una lectura sobre esta muestra, no una garantía.
      </p>
    </Card>
  );
}

function SignalRow({
  item,
  categoryLabel,
  compact = false,
}: {
  item: StatisticalSuggestionItem;
  categoryLabel: string;
  compact?: boolean;
}) {
  return (
    <li className="rounded-lg border border-edge bg-ink px-3.5 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-bold">
          {categoryLabel}: {item.option_label}
        </span>
        <span
          className={`rounded-md border px-2 py-0.5 text-xs font-bold ${
            STRENGTH_CLASS[item.strength]
          }`}
        >
          {STRENGTH_LABEL[item.strength]}
        </span>
      </div>

      {/* Observada y teórica, siempre juntas. */}
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <Metric
          label="Observada (ajustada)"
          value={PCT(item.observed_frequency_shrunk)}
          explicacion={
            <>
              Cuántas veces salió en la secuencia que ya ocurrió, moderado hacia la
              probabilidad teórica cuando hay pocos giros. Con poca muestra, 3 de 4
              no significa 75 %.
            </>
          }
        />
        <Metric
          label="Teórica (constante)"
          value={PCT(item.theoretical_probability)}
          explicacion={
            <>
              La probabilidad real de esta opción en cada giro. No cambia nunca, pase
              lo que pase en la mesa. Es la que gobierna el próximo giro.
            </>
          }
        />
        <Metric
          label="Diferencia"
          value={SIGNED(item.deviation * 100) + " pp"}
          explicacion={
            <>
              Cuánto se separa lo observado de lo teórico, en puntos porcentuales.
              Positivo: salió más de lo esperado. Negativo: menos. Describe el pasado,
              no anuncia una corrección.
            </>
          }
        />
        <Metric
          label="Rendimiento por $1.000"
          value={`${item.ev >= 0 ? "+" : "−"}$ ${Math.abs(item.ev * 1000).toFixed(0)}`}
          explicacion={
            <>
              Lo que habrían rendido $1.000 apostados aquí, si la frecuencia de esta
              muestra fuera la real. Casi siempre es negativo: es la ventaja de la
              casa. No es una ganancia que puedas esperar.
            </>
          }
        />
      </div>

      {!compact && item.chi_square_pvalue !== null ? (
        <p className="mt-2 text-xs text-muted">
          Respaldo de sesgo global: χ² p = {item.chi_square_pvalue.toFixed(3)}
        </p>
      ) : null}
    </li>
  );
}

function Metric({
  label,
  value,
  explicacion,
}: {
  label: string;
  value: string;
  explicacion?: ReactNode;
}) {
  return (
    <div>
      <span className="block text-muted">
        {label}
        {explicacion ? <InfoTip label={label}>{explicacion}</InfoTip> : null}
      </span>
      <span className="font-bold">{value}</span>
    </div>
  );
}

export function PerformancePanel({
  performance,
}: {
  performance: SessionPerformanceResponse | null;
}) {
  return (
    <Card>
      <CardHeader
        title="Auto-evaluación"
        subtitle="Compara el motor con una línea base ingenua que se limita a repetir la última categoría ganadora."
      />
      {!performance || performance.total_suggestions === 0 ? (
        <p className="rounded-lg border border-dashed border-edge py-6 text-center text-xs text-muted">
          Aún no hay giros suficientes para comparar.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3">
            <RateBox
              label="Tasa de coincidencia del motor"
              rate={performance.match_rate}
              detail={`${performance.matched_suggestions} de ${performance.total_suggestions}`}
            />
            <RateBox
              label="Línea base ingenua"
              rate={performance.baseline_match_rate}
              detail={`${performance.baseline_matched} coincidencias`}
            />
          </div>
          <p className="mt-3 rounded-lg border border-edge bg-ink px-3 py-2.5 text-xs leading-relaxed text-muted">
            {performance.verdict}
          </p>
        </>
      )}
    </Card>
  );
}

function RateBox({
  label,
  rate,
  detail,
}: {
  label: string;
  rate: number;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-edge bg-ink px-3 py-2.5">
      <span className="block text-xs text-muted">{label}</span>
      <span className="mt-0.5 block text-lg font-extrabold">{PCT(rate)}</span>
      <span className="block text-xs text-muted">{detail}</span>
    </div>
  );
}
