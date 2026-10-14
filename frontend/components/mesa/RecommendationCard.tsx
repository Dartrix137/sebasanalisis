"use client";

/**
 * Tarjeta de recomendación: la pieza central de la vista de ruleta (§2.10).
 *
 * Es lo primero y lo más grande de la pantalla, y responde la pregunta que el
 * analizador dejaba abierta: *¿entonces qué apuesto en el próximo giro?*. Tiene
 * cuatro estados y nada más (§2.10):
 *
 * - SEÑAL FUERTE: el score llega al umbral alto. APOSTAR, con su fuerza y monto.
 * - SEÑAL MEDIA: pasa el umbral medio sin llegar al alto. Igual, marcada media.
 * - SEÑAL DÉBIL: pasa el umbral débil sin llegar al medio. APOSTAR solo con la
 *   apuesta base, con un aviso de que la señal es débil.
 * - SIN SEÑAL: nada pasa el débil. NO APOSTAR ESTE GIRO.
 *
 * Siempre una sola jugada: la mejor alternativa. Aunque otro mercado también
 * pase el umbral, no se muestra como segunda apuesta. Las estadísticas que
 * sostienen la decisión están abajo, plegadas, y solo cuando hay recomendación.
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
import type { BetResponse, CreateBetRequest } from "@/lib/types/bets";
import type { GameVariantConfig } from "@/lib/types/games";
import type { BankrollStrategy } from "@/lib/types/sessions";
import type {
  MarketResponse,
  MarketStakeResponse,
  RecommendationResponse,
  ScoredMarketResponse,
  SignalBand,
  WindowStatResponse,
} from "@/lib/types/suggestions";

/**
 * Lo necesario para anotar desde la tarjeta la apuesta que el usuario hizo
 * siguiendo una gestión. Sin esto (sesión cerrada) la tarjeta solo informa.
 */
export interface StakeRegistration {
  config: GameVariantConfig;
  /** Banca actual menos lo ya comprometido en apuestas sin resolver. */
  available: number;
  pendingBets: BetResponse[];
  busy: boolean;
  onRegister: (bets: CreateBetRequest[]) => void;
}

const CURRENCY = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

const PCT = (n: number) => `${(n * 100).toFixed(1)} %`;

const BAND_LABEL: Record<SignalBand, string> = {
  none: "SIN SEÑAL",
  weak: "DÉBIL",
  medium: "MEDIA",
  strong: "FUERTE",
};

/** El estado de salida, tal como encabeza la tarjeta. */
const STATE_LABEL: Record<SignalBand, string> = {
  none: "SIN SEÑAL",
  weak: "SEÑAL DÉBIL",
  medium: "SEÑAL MEDIA",
  strong: "SEÑAL FUERTE",
};

const BAND_TEXT: Record<SignalBand, string> = {
  none: "text-muted",
  weak: "text-signal-weak",
  medium: "text-signal-medium",
  strong: "text-signal-strong",
};

const BAND_BAR: Record<SignalBand, string> = {
  none: "bg-muted",
  weak: "bg-signal-weak",
  medium: "bg-signal-medium",
  strong: "bg-signal-strong",
};

const BAND_PILL: Record<SignalBand, string> = {
  none: "border-edge text-muted",
  weak: "border-signal-weak/50 bg-signal-weak/10 text-signal-weak",
  medium: "border-signal-medium/50 bg-signal-medium/10 text-signal-medium",
  strong: "border-signal-strong/50 bg-signal-strong/10 text-signal-strong",
};

function StatePill({ band }: { band: SignalBand }) {
  return (
    <span
      className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider ${BAND_PILL[band]}`}
    >
      {STATE_LABEL[band]}
    </span>
  );
}

export const STRATEGY_LABEL: Record<BankrollStrategy, string> = {
  flat: "Plana",
  martingale: "Martingala",
  two_sector_recovery: "Recuperación de 2 sectores",
};

export function RecommendationCard({
  recommendation,
  registration,
}: {
  recommendation: RecommendationResponse | null;
  registration?: StakeRegistration;
}) {
  if (recommendation === null) return null;

  const recomienda = recommendation.decision === "RECOMMEND";

  return (
    <Card className="border-gold/30">
      {recomienda && recommendation.market ? (
        <BetState recommendation={recommendation} registration={registration} />
      ) : (
        <NoBetState recommendation={recommendation} />
      )}

      {/* El respaldo solo acompaña a una jugada: sin señal no hay nada que explicar. */}
      {recomienda && recommendation.market ? <Why recommendation={recommendation} /> : null}

      {/* Línea fija: va siempre, haya o no señal. */}
      <p className="mt-4 border-t border-edge pt-3 text-xs leading-relaxed text-muted">
        {recommendation.disclaimer}
      </p>
    </Card>
  );
}

function BetState({
  recommendation,
  registration,
}: {
  recommendation: RecommendationResponse;
  registration?: StakeRegistration;
}) {
  const market = recommendation.market!;
  const banda = recommendation.signal_band;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatePill band={banda} />
        <p className="text-xs text-muted">Recomendación para el siguiente giro</p>
      </div>
      <h2 className="mt-2 text-3xl font-bold leading-tight text-white sm:text-4xl">
        APOSTAR: <span className="text-gold">{market.label.toUpperCase()}</span>
      </h2>

      {/* Fuerza interna */}
      <div className="mt-4">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-sm text-muted">Fuerza interna</span>
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

      {banda === "weak" ? <WeakNotice /> : null}

      <StakeList
        stakes={recommendation.stakes}
        market={market}
        registration={registration}
      />
    </>
  );
}

function NoBetState({ recommendation }: { recommendation: RecommendationResponse }) {
  const faltanDatos = recommendation.no_bet_reason === "insufficient_data";

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatePill band="none" />
        <p className="text-xs text-muted">Recomendación para el siguiente giro</p>
      </div>
      <h2 className="mt-2 text-3xl font-bold leading-tight text-white sm:text-4xl">
        {faltanDatos ? "FALTA INFORMACIÓN" : "NO APOSTAR ESTE GIRO"}
      </h2>

      {faltanDatos ? (
        <p className="mt-2 text-sm text-muted">
          Llevas{" "}
          <span className="font-bold text-white">
            {recommendation.total_spins} de {recommendation.min_spins_for_signal}
          </span>{" "}
          números. Hasta tenerlos no hay con qué medir una señal: registra los que
          vayan saliendo.
        </p>
      ) : (
        // Sin señal no se nombra ninguna alternativa: mostrar la "mejor de las
        // que no llegan" se lee como una segunda jugada.
        <p className="mt-2 text-sm text-muted">
          Esperar el siguiente resultado y volver a analizar.
        </p>
      )}

      {/*
        Hay mesas (sobre todo virtuales) que exigen apostar en cada giro. Sin
        señal, la salida honesta es el mínimo: ninguna opción se distingue de
        otra, y cualquier monto mayor solo agranda la exposición a la ventaja de
        la casa.
      */}
      <div className="mt-4 rounded-lg border border-edge bg-ink px-3.5 py-3 text-xs leading-relaxed text-muted">
        <p>
          <span className="font-bold text-white">No apuestes este giro.</span> Si la
          mesa te obliga a apostar en cada giro, apuesta el{" "}
          <span className="font-bold text-white">mínimo que acepte la mesa</span>,
          fuera de tus progresiones: sin señal, ninguna opción se distingue de otra.
        </p>
        <p className="mt-1.5">
          Las progresiones no avanzan con un giro sin recomendación.
        </p>
      </div>
    </>
  );
}

/**
 * "en cada docena", "en cada columna": el nombre de la zona sale de la etiqueta
 * de la categoría en `categories_json`, no de un texto fijo de ruleta.
 */
function perSectorLabel(config: GameVariantConfig | undefined, market: MarketResponse): string {
  const categoria = config?.categories.find((c) => c.id === market.category_id);
  return categoria ? `en cada ${categoria.label.toLowerCase()}` : "en cada una";
}

/**
 * El anuncio de la SEÑAL DÉBIL. Explica por qué igual se muestra una jugada
 * —es la opción que más se ha destacado en los números de esta mesa— sin
 * disfrazarla de algo más firme, y fija el monto en la apuesta base.
 */
function WeakNotice() {
  return (
    <div className="mt-4 rounded-lg border border-signal-weak/40 bg-signal-weak/10 px-3.5 py-3 text-xs leading-relaxed text-white">
      <p className="font-bold uppercase tracking-wider text-signal-weak">Señal débil</p>
      <p className="mt-1">
        La desviación observada es pequeña. Aun así, es la opción que más se ha
        destacado según cómo han ido saliendo los números en esta mesa, y por eso
        se muestra como recomendación.
      </p>
      <p className="mt-1.5 text-muted">
        Si decides jugar, hazlo solo con la apuesta base: con una señal débil las
        progresiones no se ofrecen y ninguna avanza de escalón.
      </p>
    </div>
  );
}

/** Una apuesta por zona del mercado, con el monto por sector de la gestión. */
function betsFor(
  config: GameVariantConfig,
  market: MarketResponse,
  stake: MarketStakeResponse,
): CreateBetRequest[] {
  const categoria = config.categories.find((c) => c.id === market.category_id);
  return market.group_ids.map((gid) => ({
    category: market.category_id,
    option_label: categoria?.groups[gid]?.label ?? gid,
    amount: stake.bet_per_sector,
    followed_suggestion: true,
    strategy: stake.strategy,
  }));
}

/**
 * Las tres progresiones, juntas. La mesa no pide elegir una: muestra lo que
 * pediría cada una para el mercado recomendado, y el usuario anota con un toque
 * la que siguió.
 */
function StakeList({
  stakes,
  market,
  registration,
}: {
  stakes: MarketStakeResponse[];
  market: MarketResponse;
  registration?: StakeRegistration;
}) {
  if (stakes.length === 0) return null;
  const sectors = market.sectors;
  const enCada = perSectorLabel(registration?.config, market);
  const anotada = registration?.pendingBets.some((b) => b.followed_suggestion) ?? false;

  return (
    <div className="mt-5 border-t border-edge pt-4">
      <h3 className="text-sm font-bold text-white">Apuesta indicada, por gestión</h3>
      <p className="mt-0.5 text-xs text-muted">
        {registration && !anotada
          ? "Sigue la gestión que estés usando. Si apostaste, toca la que usaste: queda anotada y solo esa avanza de escalón."
          : "Sigue la gestión que estés usando."}
      </p>

      {anotada ? (
        <p className="mt-3 rounded-lg border border-gold/40 bg-gold/10 px-3 py-2 text-xs text-white">
          Ya anotaste tu apuesta de este giro. Se resuelve con el próximo número; si
          te equivocaste, quítala en la mesa.
        </p>
      ) : null}

      <ul className="mt-3 space-y-1.5">
        {stakes.map((s) => (
          <li
            key={s.strategy}
            className={`flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg border px-3 py-2.5 ${
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
              <span className="flex items-center gap-3">
                <span className="text-right">
                  <span className="text-sm font-bold tabular-nums text-white">
                    {CURRENCY.format(s.bet_per_sector)}
                  </span>
                  {sectors > 1 ? (
                    <>
                      <span className="ml-1.5 text-xs text-white">{enCada}</span>
                      <span className="block text-xs text-muted">
                        {CURRENCY.format(s.total_bet)} en total
                      </span>
                    </>
                  ) : null}
                  {s.exceeds_bankroll || s.exceeds_table_limit ? (
                    <span className="mt-0.5 block text-xs text-table-red">
                      {s.exceeds_bankroll
                        ? "La banca no lo cubre"
                        : "Supera el límite de la mesa"}
                    </span>
                  ) : null}
                </span>
                {registration && !anotada ? (
                  <button
                    type="button"
                    disabled={
                      registration.busy ||
                      s.exceeds_table_limit ||
                      s.total_bet > registration.available
                    }
                    onClick={() =>
                      registration.onRegister(betsFor(registration.config, market, s))
                    }
                    className="rounded-md border border-gold/50 px-2.5 py-1.5 text-xs font-bold text-gold transition-colors enabled:hover:bg-gold enabled:hover:text-gold-ink disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Aposté esto
                  </button>
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
          <Components
            scored={mejor}
            weakThreshold={recommendation.weak_threshold}
            threshold={recommendation.threshold}
            strongThreshold={recommendation.strong_threshold}
          />
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
  weakThreshold,
  threshold,
  strongThreshold,
}: {
  scored: ScoredMarketResponse;
  weakThreshold: number;
  threshold: number;
  strongThreshold: number;
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
        Se recomienda apostar desde {Math.round(weakThreshold)} puntos (SEÑAL
        DÉBIL, solo con la apuesta base); desde {Math.round(threshold)}, la señal es
        MEDIA, y desde {Math.round(strongThreshold)}, FUERTE.
      </p>
    </div>
  );
}
