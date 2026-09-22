"use client";

/**
 * Tarjeta de recomendación: la pieza central de la vista de ruleta (§2.10).
 *
 * Es lo primero y lo más grande de la pantalla, y responde la pregunta que el
 * analizador dejaba abierta: *¿entonces qué apuesto en el próximo giro?*. Tiene
 * dos estados y nada más — APOSTAR con su mercado, su fuerza y su monto, o NO
 * APOSTAR. Las estadísticas que sostienen la decisión están abajo, plegadas.
 *
 * Dos cosas que el copy no puede perder, y que están aquí por diseño y no por
 * decoración:
 *
 * 1. Bajo el score, la aclaración de que 81/100 es la fuerza del criterio
 *    interno y no la probabilidad de acertar. Sin ella el número se lee como un
 *    porcentaje de éxito, que es exactamente lo que no es.
 * 2. Al pie, la línea fija que recuerda de dónde sale la recomendación. Desde la
 *    Fase 3 es el único recordatorio que queda en la pantalla (el banner fijo de
 *    §0 se retiró), así que se muestra siempre, no solo cuando hay señal.
 */

import { useState } from "react";

import { Card } from "@/components/ui";
import type { BankrollStrategy } from "@/lib/types/sessions";
import type {
  MarketStakeResponse,
  RecommendationResponse,
  ScoredMarketResponse,
  SignalBand,
  WindowStatResponse,
} from "@/lib/types/suggestions";

const CURRENCY = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

const PCT = (n: number) => `${(n * 100).toFixed(1)} %`;

const BAND_LABEL: Record<SignalBand, string> = {
  weak: "DÉBIL",
  medium: "MEDIA",
  strong: "FUERTE",
  very_strong: "MUY FUERTE",
};

const BAND_TEXT: Record<SignalBand, string> = {
  weak: "text-muted",
  medium: "text-signal-medium",
  strong: "text-signal-strong",
  very_strong: "text-signal-strong",
};

const BAND_BAR: Record<SignalBand, string> = {
  weak: "bg-muted",
  medium: "bg-signal-medium",
  strong: "bg-signal-strong",
  very_strong: "bg-signal-strong",
};

export const STRATEGY_LABEL: Record<BankrollStrategy, string> = {
  flat: "Plana",
  martingale: "Martingala",
  two_sector_recovery: "Recuperación de 2 sectores",
};

export function RecommendationCard({
  recommendation,
}: {
  recommendation: RecommendationResponse | null;
}) {
  if (recommendation === null) return null;

  const recomienda = recommendation.decision === "RECOMMEND";

  return (
    <Card className="border-gold/30">
      {recomienda && recommendation.market ? (
        <BetState recommendation={recommendation} />
      ) : (
        <NoBetState recommendation={recommendation} />
      )}

      <Why recommendation={recommendation} />

      {/* Línea fija: va siempre, haya o no señal. */}
      <p className="mt-4 border-t border-edge pt-3 text-xs leading-relaxed text-muted">
        {recommendation.disclaimer}
      </p>
    </Card>
  );
}

function BetState({ recommendation }: { recommendation: RecommendationResponse }) {
  const market = recommendation.market!;
  const banda = recommendation.signal_band;

  return (
    <>
      <p className="text-xs font-bold uppercase tracking-wider text-muted">
        Recomendación para el siguiente giro
      </p>
      <h2 className="mt-1 text-3xl font-bold leading-tight text-white sm:text-4xl">
        APOSTAR: <span className="text-gold">{market.label.toUpperCase()}</span>
      </h2>

      {/* Fuerza de señal */}
      <div className="mt-4">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-sm text-muted">Fuerza de señal</span>
          <span className={`text-sm font-bold ${BAND_TEXT[banda]}`}>
            <span className="tabular-nums">
              {Math.round(recommendation.signal_score)}/100
            </span>{" "}
            — {BAND_LABEL[banda]}
          </span>
        </div>
        <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-ink">
          <div
            className={`h-full rounded-full ${BAND_BAR[banda]}`}
            style={{ width: `${Math.min(recommendation.signal_score, 100)}%` }}
          />
        </div>
        <p className="mt-1.5 text-xs leading-relaxed text-muted">
          {Math.round(recommendation.signal_score)}/100 es la fuerza del criterio
          interno, no la probabilidad de acertar.
        </p>
      </div>

      <StakeList stakes={recommendation.stakes} sectors={market.sectors} />
    </>
  );
}

function NoBetState({ recommendation }: { recommendation: RecommendationResponse }) {
  return (
    <>
      <p className="text-xs font-bold uppercase tracking-wider text-muted">
        Recomendación para el siguiente giro
      </p>
      <h2 className="mt-1 text-3xl font-bold leading-tight text-white sm:text-4xl">
        NO APOSTAR ESTE GIRO
      </h2>
      <p className="mt-2 text-sm text-muted">
        Esperar el siguiente resultado y volver a analizar.
      </p>
      {recommendation.best ? (
        <p className="mt-3 text-xs leading-relaxed text-muted">
          La alternativa más marcada,{" "}
          <span className="font-bold text-white">
            {recommendation.best.market.label}
          </span>
          , llega a {Math.round(recommendation.best.signal_score)}/100 y no alcanza
          el umbral de {Math.round(recommendation.threshold)}.
        </p>
      ) : null}
    </>
  );
}

/**
 * Las tres progresiones, juntas. La mesa no pide elegir una: muestra lo que
 * pediría cada una para el mercado recomendado y el usuario sigue la suya.
 */
function StakeList({
  stakes,
  sectors,
}: {
  stakes: MarketStakeResponse[];
  sectors: number;
}) {
  if (stakes.length === 0) return null;

  return (
    <div className="mt-5 border-t border-edge pt-4">
      <h3 className="text-sm font-bold text-white">Apuesta indicada</h3>
      <p className="mt-0.5 text-xs text-muted">
        Según cada gestión. Sigue la que estés usando.
      </p>

      <ul className="mt-3 space-y-1.5">
        {stakes.map((s) => (
          <li
            key={s.strategy}
            className={`flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 rounded-lg border px-3 py-2.5 ${
              s.applicable
                ? "border-edge bg-ink-sunken"
                : "border-edge/50 bg-ink-sunken/40"
            }`}
          >
            <span
              className={`text-sm font-bold ${s.applicable ? "text-white" : "text-muted"}`}
            >
              {STRATEGY_LABEL[s.strategy]}
              {s.applicable && s.strategy !== "flat" ? (
                <span className="ml-2 text-xs font-normal text-muted">
                  escalón {s.stage + 1}
                </span>
              ) : null}
            </span>

            {s.applicable ? (
              <span className="text-right">
                <span className="text-sm font-bold tabular-nums text-white">
                  {CURRENCY.format(s.total_bet)}
                </span>
                {sectors > 1 ? (
                  <span className="ml-2 text-xs text-muted">
                    ({CURRENCY.format(s.bet_per_sector)} en cada una)
                  </span>
                ) : null}
                {s.exceeds_bankroll || s.exceeds_table_limit ? (
                  <span className="mt-0.5 block text-xs text-table-red">
                    {s.exceeds_bankroll
                      ? "La banca no lo cubre"
                      : "Supera el límite de la mesa"}
                  </span>
                ) : null}
              </span>
            ) : (
              <span className="max-w-xs text-right text-xs leading-relaxed text-muted">
                {s.reason}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * "¿Por qué recomienda esto?" — plegada por defecto (§2.10).
 *
 * Aquí es donde viven las frecuencias y las probabilidades teóricas, que siguen
 * viajando siempre juntas (regla anti-falacia del jugador, §2). Lo que cambió en
 * la Fase 3 es dónde se pintan, no que existan.
 */
function Why({ recommendation }: { recommendation: RecommendationResponse }) {
  const [abierto, setAbierto] = useState(false);
  const mejor = recommendation.best;
  if (!mejor) return null;

  return (
    <div className="mt-4 border-t border-edge pt-3">
      <button
        type="button"
        onClick={() => setAbierto((v) => !v)}
        aria-expanded={abierto}
        className="flex w-full items-center justify-between text-sm font-bold text-muted transition-colors hover:text-white"
      >
        ¿Por qué recomienda esto?
        <span aria-hidden className="text-xs">
          {abierto ? "▲" : "▼"}
        </span>
      </button>

      {abierto ? (
        <div className="mt-3 space-y-4">
          <WindowTable scored={mejor} />
          <Components scored={mejor} threshold={recommendation.threshold} />
          <OtherMarkets recommendation={recommendation} />
        </div>
      ) : null}
    </div>
  );
}

function WindowTable({ scored }: { scored: ScoredMarketResponse }) {
  return (
    <div>
      <h4 className="text-xs font-bold uppercase tracking-wider text-muted">
        {scored.market.label} · por ventana
      </h4>
      <p className="mt-1 text-xs leading-relaxed text-muted">
        Cubre {scored.market.coverage} resultados. La teórica es lo que la mesa da
        de por sí y no cambia nunca; la observada es lo que ya salió, moderado
        cuando hay pocos giros.
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[26rem] text-xs">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-1 font-normal">Ventana</th>
              <th className="py-1 font-normal">Observada</th>
              <th className="py-1 font-normal">Teórica</th>
              <th className="py-1 font-normal">Desviación</th>
              <th className="py-1 font-normal">Rango del azar</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {scored.windows.map((w) => (
              <WindowRow key={w.spins_used} w={w} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function WindowRow({ w }: { w: WindowStatResponse }) {
  return (
    <tr className="border-t border-edge/60">
      <td className="py-1.5 text-muted">{w.spins_used} giros</td>
      <td className="py-1.5 font-bold text-white">
        {PCT(w.observed_frequency_shrunk)}
      </td>
      <td className="py-1.5 text-muted">{PCT(w.theoretical_probability)}</td>
      <td
        className={`py-1.5 ${w.deviation >= 0 ? "text-signal-strong" : "text-muted"}`}
      >
        {w.deviation >= 0 ? "+" : "−"}
        {PCT(Math.abs(w.deviation))}
      </td>
      {/* El intervalo de Wilson describe incertidumbre; no afirma nada (§2.2). */}
      <td className="py-1.5 text-muted">
        {PCT(w.observed_ci_low)} – {PCT(w.observed_ci_high)}
      </td>
    </tr>
  );
}

function Components({
  scored,
  threshold,
}: {
  scored: ScoredMarketResponse;
  threshold: number;
}) {
  const c = scored.components;
  const filas: { label: string; valor: number | null; peso: number; nota: string }[] = [
    {
      label: "Desviación",
      valor: c.deviation,
      peso: c.weight_deviation,
      nota: "cuánto se separó con la muestra más grande",
    },
    {
      label: "Recencia",
      valor: c.recency,
      peso: c.weight_recency,
      nota: "cuánto se está separando ahora",
    },
    {
      label: "Consistencia",
      valor: c.consistency,
      peso: c.weight_consistency,
      nota:
        c.consistency === null
          ? "sin medir: hace falta más de un tramo de historial"
          : "si la inclinación aguanta en tramos distintos",
    },
  ];

  return (
    <div>
      <h4 className="text-xs font-bold uppercase tracking-wider text-muted">
        De dónde salen los {Math.round(scored.signal_score)} puntos
      </h4>
      <ul className="mt-2 space-y-1.5">
        {filas.map((f) => (
          <li key={f.label} className="text-xs">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-white">
                {f.label}
                <span className="ml-1.5 text-muted">
                  (peso {Math.round(f.peso * 100)} %)
                </span>
              </span>
              <span className="tabular-nums text-muted">
                {f.valor === null ? "—" : `${Math.round(f.valor * 100)} / 100`}
              </span>
            </div>
            <p className="text-muted">{f.nota}</p>
          </li>
        ))}
      </ul>

      <p className="mt-2 text-xs leading-relaxed text-muted">
        {c.chi_square_bonus > 0 ? (
          <>
            La prueba χ² suma {Math.round(c.chi_square_bonus)} puntos: la sesión
            tiene volumen suficiente y la desviación sobrevive a la corrección por
            comparaciones múltiples
            {scored.chi_square_pvalue_adjusted !== null
              ? ` (p corregido ${scored.chi_square_pvalue_adjusted.toFixed(3)})`
              : ""}
            .
          </>
        ) : (
          <>
            La prueba χ² no suma puntos aquí: exige al menos 200 giros en la sesión
            y que la desviación sobreviva a la corrección por comparaciones
            múltiples.
          </>
        )}{" "}
        Se recomienda apostar a partir de {Math.round(threshold)} puntos.
      </p>
    </div>
  );
}

function OtherMarkets({
  recommendation,
}: {
  recommendation: RecommendationResponse;
}) {
  const otros = recommendation.candidates.slice(0, 6);
  if (otros.length === 0) return null;

  return (
    <div>
      <h4 className="text-xs font-bold uppercase tracking-wider text-muted">
        Los demás mercados
      </h4>
      <ul className="mt-2 space-y-1">
        {otros.map((c) => (
          <li
            key={c.market.key}
            className="flex items-baseline justify-between gap-3 text-xs"
          >
            <span className="text-white">{c.market.label}</span>
            <span className={`tabular-nums ${BAND_TEXT[c.signal_band]}`}>
              {Math.round(c.signal_score)}/100 · {BAND_LABEL[c.signal_band]}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
