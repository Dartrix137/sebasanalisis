"use client";

/**
 * Plan de banca del giro en curso (§2.8.1-2.8.2), a la vista en la mesa.
 *
 * Responde tres preguntas y nada más: cuánto apostar ahora, qué pasó en la
 * última ronda y qué viene según cómo cierre la siguiente. El detalle (tabla de
 * progresión, riesgo de ruina) vive en el panel plegado de gestión de banca.
 *
 * Todo es condicional —"si pierdes", "si ganas"—: nunca dice cuál de los dos va
 * a pasar ni sugiere a qué apostar.
 */

import { useState } from "react";

import { STRATEGY_LABEL } from "@/components/roulette/BankrollPanel";
import type {
  BankrollAlertLevel,
  BankrollSuggestionResponse,
  NextStepResponse,
  ProgressionTableResponse,
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

/** Resultado de la última ronda con apuestas, tal como quedó registrado. */
export interface LastRound {
  resultValue: string;
  net: number;
  /** Escalón antes de resolverse; null si se cambió de estrategia después. */
  stageBefore: number | null;
}

export function BankrollPlanCard({
  suggestion,
  progression,
  lastRound,
  lossLimit,
  lostSoFar,
}: {
  suggestion: BankrollSuggestionResponse | null;
  progression: ProgressionTableResponse | null;
  lastRound: LastRound | null;
  lossLimit: number | null;
  /** Banca inicial menos banca actual; negativo si se va ganando. */
  lostSoFar: number;
}) {
  const [verTodas, setVerTodas] = useState(false);
  if (!suggestion) return null;

  const plana = suggestion.strategy === "flat";
  const bloqueado = suggestion.exceeds_bankroll || suggestion.exceeds_table_limit;
  const [principal, ...resto] = suggestion.alerts;

  return (
    <section aria-label="Plan de banca" className="space-y-3">
      {lastRound ? (
        <RoundResult ronda={lastRound} suggestion={suggestion} plana={plana} />
      ) : null}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-muted">
            Próxima apuesta
          </p>
          <p className="text-2xl font-extrabold tabular-nums text-gold">
            {MONEY(suggestion.suggested_bet)}
          </p>
          {suggestion.sectors > 1 ? (
            <p className="text-xs text-muted">
              {MONEY(suggestion.bet_per_sector)} en cada uno de los {suggestion.sectors}{" "}
              sectores
            </p>
          ) : null}
        </div>
        <p className="text-right text-xs text-muted">
          {STRATEGY_LABEL[suggestion.strategy]}
          {plana ? null : (
            <>
              <br />
              <span className="font-bold text-white">escalón {suggestion.stage + 1}</span>
            </>
          )}
        </p>
      </div>

      {!plana && progression ? (
        <Ladder
          progression={progression}
          stage={suggestion.stage}
          stagesSupported={suggestion.stages_supported}
        />
      ) : null}

      {bloqueado || plana ? null : (
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <span>
            Si pierdes → <NextAmount paso={suggestion.next_if_lost} />
          </span>
          <span>
            Si ganas → <NextAmount paso={suggestion.next_if_won} />
          </span>
        </p>
      )}

      {principal ? (
        <div className="space-y-1.5">
          <Alert alerta={principal} />
          {verTodas ? resto.map((a) => <Alert key={a.code} alerta={a} />) : null}
          {resto.length > 0 ? (
            <button
              type="button"
              onClick={() => setVerTodas((v) => !v)}
              className="text-xs text-muted underline-offset-2 hover:text-white hover:underline"
            >
              {verTodas
                ? "Ver menos avisos"
                : `Ver ${resto.length} ${resto.length === 1 ? "aviso más" : "avisos más"}`}
            </button>
          ) : null}
        </div>
      ) : null}

      <p className="text-xs text-muted">
        {lossLimit === null ? (
          "Sin límite de pérdida: puedes fijarlo en Ajustes de la sesión."
        ) : (
          <>
            Límite de pérdida: te quedan{" "}
            <span className="font-bold text-white">
              {/* Ir ganando no agranda el límite a la vista: "te quedan $110.000
                  de $100.000" se lee como un error aunque la cuenta sea exacta. */}
              {MONEY(Math.min(lossLimit, Math.max(lossLimit - lostSoFar, 0)))}
            </span>{" "}
            de {MONEY(lossLimit)}.
          </>
        )}
      </p>

      <p className="text-[11px] leading-relaxed text-muted/80">{suggestion.disclaimer}</p>
    </section>
  );
}

function RoundResult({
  ronda,
  suggestion,
  plana,
}: {
  ronda: LastRound;
  suggestion: BankrollSuggestionResponse;
  plana: boolean;
}) {
  const gano = ronda.net > 0;
  const perdio = ronda.net < 0;
  const ahora = suggestion.stage;

  let progresion: string;
  if (plana) {
    progresion = "La apuesta plana no cambia.";
  } else if (ronda.stageBefore === null || ronda.stageBefore === ahora) {
    progresion =
      ahora === 0 ? "Sigues en la apuesta base." : `Sigues en el escalón ${ahora + 1}.`;
  } else if (ahora > ronda.stageBefore) {
    progresion = `La progresión sube del escalón ${ronda.stageBefore + 1} al ${ahora + 1}.`;
  } else if (ahora === 0) {
    progresion = "La serie se cerró: vuelves a la apuesta base.";
  } else {
    progresion = `La progresión baja del escalón ${ronda.stageBefore + 1} al ${ahora + 1}.`;
  }

  return (
    <div
      role="status"
      className={`rounded-lg border px-3 py-2.5 text-sm ${
        gano
          ? "border-signal-strong/50 bg-signal-strong/10"
          : perdio
            ? "border-table-red/40 bg-table-red/10"
            : "border-edge bg-ink"
      }`}
    >
      <p className="font-bold text-white">
        {gano
          ? `Ganaste ${SIGNED(ronda.net)} con el ${ronda.resultValue}`
          : perdio
            ? `Perdiste ${SIGNED(ronda.net)} con el ${ronda.resultValue}`
            : `El ${ronda.resultValue} dejó la ronda en $ 0`}
      </p>
      <p className="mt-0.5 text-xs text-muted">
        {progresion} Próxima apuesta:{" "}
        <span className="font-bold text-white">{MONEY(suggestion.suggested_bet)}</span>.
      </p>
    </div>
  );
}

/** Escalones de la progresión como una escalera: dónde estás y hasta dónde alcanza. */
function Ladder({
  progression,
  stage,
  stagesSupported,
}: {
  progression: ProgressionTableResponse;
  stage: number;
  stagesSupported: number;
}) {
  if (stage >= progression.rows.length) return null;
  const ultimoAlcanzable = stage + stagesSupported - 1;

  return (
    <div>
      <ol className="flex gap-1" aria-label="Escalones de la progresión">
        {progression.rows.map((row) => {
          const actual = row.stage === stage;
          const fuera = row.stage > ultimoAlcanzable || row.exceeds_table_limit;
          return (
            <li
              key={row.stage}
              title={`Escalón ${row.stage + 1}: ${MONEY(row.total_bet)}${
                fuera ? " · tu banca o la mesa ya no alcanzan" : ""
              }`}
              aria-current={actual ? "step" : undefined}
              className={`flex h-7 min-w-0 flex-1 items-center justify-center rounded text-[11px] font-bold ${
                actual
                  ? "bg-gold text-gold-ink"
                  : fuera
                    ? "bg-table-red/15 text-table-red"
                    : row.stage < stage
                      ? "bg-ink-sunken text-muted/60"
                      : "bg-ink-sunken text-muted"
              }`}
            >
              {row.stage + 1}
            </li>
          );
        })}
      </ol>
      <p className="mt-1 text-[11px] text-muted">
        En rojo, los escalones que tu banca o la mesa ya no alcanzan.
      </p>
    </div>
  );
}

function NextAmount({ paso }: { paso: NextStepResponse }) {
  const aviso = paso.exceeds_bankroll
    ? "tu banca no alcanza"
    : paso.exceeds_table_limit
      ? "la mesa no lo acepta"
      : paso.reaches_loss_limit
        ? "llegas a tu límite"
        : null;
  return (
    <span className={`font-bold ${aviso ? "text-table-red" : "text-white"}`}>
      {MONEY(paso.suggested_bet)}
      {aviso ? ` (${aviso})` : ""}
    </span>
  );
}

function Alert({ alerta }: { alerta: BankrollSuggestionResponse["alerts"][number] }) {
  const estilo = ALERT_STYLES[alerta.level];
  return (
    <p
      role={alerta.level === "critical" ? "alert" : undefined}
      className={`rounded-lg border px-3 py-2 text-xs leading-relaxed ${estilo.box}`}
    >
      <span className={`mr-1.5 font-bold uppercase tracking-wide ${estilo.tag}`}>
        {estilo.label}
      </span>
      {alerta.message}
    </p>
  );
}
