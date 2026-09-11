"use client";

/**
 * Plan de banca del giro en curso (§2.8), a la vista dentro del bucle de la mesa.
 *
 * Muestra lo que pide la progresión ahora, dónde queda en los dos casos posibles
 * y las alertas de banca. Todo es condicional —"si cierra en contra", "si cierra
 * a favor"—: nunca dice cuál de los dos va a pasar ni sugiere a qué apostar.
 */

import type { ReactNode } from "react";

import { STRATEGY_LABEL } from "@/components/roulette/BankrollPanel";
import type {
  BankrollAlertLevel,
  BankrollSuggestionResponse,
  NextStepResponse,
} from "@/lib/types/suggestions";

const MONEY = (n: number) =>
  new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency: "COP",
    maximumFractionDigits: 0,
  }).format(n);

const SIGNED = (n: number) => `${n >= 0 ? "+" : "−"}${MONEY(Math.abs(n))}`;

const ALERT_STYLES: Record<BankrollAlertLevel, { box: string; tag: string; label: string }> = {
  critical: {
    box: "border-table-red/40 bg-table-red/10 text-white",
    tag: "text-table-red",
    label: "Crítico",
  },
  caution: {
    box: "border-signal-medium/40 bg-signal-medium/10 text-white",
    tag: "text-signal-medium",
    label: "Atención",
  },
  info: {
    box: "border-edge bg-ink text-muted",
    tag: "text-muted",
    label: "Nota",
  },
};

/** Alertas que ya dicen cuánto margen de banca queda: la línea de margen sobraría. */
const MARGIN_ALERTS: ReadonlySet<string> = new Set([
  "bankroll_insufficient",
  "last_affordable_stage",
  "few_stages_left",
]);

export interface StageChange {
  from: number;
  to: number;
}

export function BankrollPlanCard({
  suggestion,
  lastChange,
  lossLimit,
  lostSoFar,
}: {
  suggestion: BankrollSuggestionResponse | null;
  lastChange: StageChange | null;
  lossLimit: number | null;
  /** Banca inicial menos banca actual; negativo si se va ganando. */
  lostSoFar: number;
}) {
  if (!suggestion) return null;

  const plana = suggestion.strategy === "flat";
  const { next_if_lost: siPierde, next_if_won: siGana } = suggestion;
  // Si la apuesta de este escalón no se puede colocar, los dos escenarios
  // describirían un giro imposible (con banca negativa): solo quedan las alertas.
  const bloqueado = suggestion.exceeds_bankroll || suggestion.exceeds_table_limit;
  const margenYaAvisado = suggestion.alerts.some((a) =>
    MARGIN_ALERTS.has(a.code),
  );

  return (
    <section aria-label="Plan de banca" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-bold text-white">
          Plan de banca
          <span className="ml-2 text-xs font-normal text-muted">
            {STRATEGY_LABEL[suggestion.strategy]}
            {plana ? "" : ` · escalón ${suggestion.stage + 1}`}
          </span>
        </h3>
        <p className="text-xs text-muted">
          Este giro pide{" "}
          <span className="text-base font-bold tabular-nums text-gold">
            {MONEY(suggestion.suggested_bet)}
          </span>
          {suggestion.sectors > 1 ? (
            <span className="ml-1">({MONEY(suggestion.bet_per_sector)} por sector)</span>
          ) : null}
        </p>
      </div>

      <p className="text-xs text-muted">
        {lossLimit === null ? (
          <>
            Sin límite de pérdida. Fijarlo antes de seguir es lo más útil que puedes
            hacer con tu banca: se hace en Ajustes de la sesión.
          </>
        ) : (
          <>
            Límite de pérdida {MONEY(lossLimit)} · te quedan{" "}
            <span className="font-bold text-white">
              {MONEY(Math.max(lossLimit - lostSoFar, 0))}
            </span>{" "}
            de margen
          </>
        )}
      </p>

      {lastChange ? (
        <p
          role="status"
          className="rounded-lg border border-gold/40 bg-gold/10 px-3 py-2 text-xs text-white"
        >
          {lastChange.to > lastChange.from
            ? `El último giro cerró en contra: la progresión sube del escalón ${
                lastChange.from + 1
              } al ${lastChange.to + 1}.`
            : `El último giro cerró a favor: la progresión ${
                lastChange.to === 0 ? "vuelve" : "baja"
              } del escalón ${lastChange.from + 1} al ${lastChange.to + 1}.`}
        </p>
      ) : null}

      {bloqueado ? null : plana ? (
        <p className="text-xs text-muted">
          La apuesta plana no cambia: {MONEY(suggestion.suggested_bet)} gane o pierda.
        </p>
      ) : (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            <StepBox titulo="Si este giro cierra en contra" paso={siPierde}>
              Perdido en la serie: {MONEY(suggestion.cumulative_risked)}
            </StepBox>
            <StepBox titulo="Si este giro cierra a favor" paso={siGana}>
              {suggestion.recovers_only_to_break_even
                ? "La serie vuelve a cero: recupera, no deja ganancia"
                : `La serie cierra en ${SIGNED(suggestion.net_result_if_won)}`}
            </StepBox>
          </div>
          <p className="text-xs text-muted">
            {margenYaAvisado ? null : (
              <>
                Tu banca cubre{" "}
                <span className="font-bold text-white">{suggestion.stages_supported}</span>{" "}
                {suggestion.stages_supported === 1 ? "escalón" : "escalones"} seguidos
                desde aquí, contando este.{" "}
              </>
            )}
            Los montos suponen que apuestas lo que pide la progresión.
          </p>
        </>
      )}

      {suggestion.alerts.length > 0 ? (
        <ul className="space-y-1.5">
          {suggestion.alerts.map((a) => {
            const estilo = ALERT_STYLES[a.level];
            return (
              <li
                key={a.code}
                role={a.level === "critical" ? "alert" : undefined}
                className={`rounded-lg border px-3 py-2 text-xs leading-relaxed ${estilo.box}`}
              >
                <span className={`mr-1.5 font-bold uppercase tracking-wide ${estilo.tag}`}>
                  {estilo.label}
                </span>
                {a.message}
              </li>
            );
          })}
        </ul>
      ) : null}

      <p className="text-xs leading-relaxed text-muted">{suggestion.disclaimer}</p>
    </section>
  );
}

function StepBox({
  titulo,
  paso,
  children,
}: {
  titulo: string;
  paso: NextStepResponse;
  children: ReactNode;
}) {
  const bloqueado = paso.exceeds_bankroll || paso.exceeds_table_limit;
  const enRojo = bloqueado || paso.reaches_loss_limit;
  return (
    <div
      className={`rounded-lg border px-3 py-2.5 ${
        enRojo ? "border-table-red/40 bg-table-red/10" : "border-edge bg-ink"
      }`}
    >
      <p className="text-xs text-muted">{titulo}</p>
      <p className="mt-0.5 text-sm font-bold text-white">
        Escalón {paso.stage + 1} · <span className="tabular-nums">{MONEY(paso.suggested_bet)}</span>
      </p>
      <p className="mt-0.5 text-xs text-muted">
        Banca: <span className="tabular-nums">{MONEY(paso.bankroll_after)}</span> · {children}
      </p>
      {bloqueado ? (
        <p className="mt-1 text-xs font-bold text-table-red">
          {paso.exceeds_bankroll ? "Tu banca no alcanzaría para ese escalón. " : ""}
          {paso.exceeds_table_limit ? "La mesa no aceptaría esa apuesta." : ""}
        </p>
      ) : null}
      {paso.reaches_loss_limit ? (
        <p className="mt-1 text-xs font-bold text-table-red">
          Llegarías a tu límite de pérdida.
        </p>
      ) : null}
    </div>
  );
}
