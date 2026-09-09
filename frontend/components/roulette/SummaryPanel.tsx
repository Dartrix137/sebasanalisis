"use client";

/**
 * Resumen de la sesión (§4). Aparece cuando la sesión se cierra.
 *
 * Todo lo que muestra describe lo que ya ocurrió. En particular `win_rate` es la
 * proporción de apuestas ganadas en ESTA sesión: no es una tasa de acierto del
 * motor ni dice nada sobre las próximas — la ventaja de la casa no cambió.
 */

import { Card, CardHeader } from "@/components/ui";
import { STRATEGY_LABEL } from "@/components/roulette/BankrollPanel";
import type { SessionSummaryResponse } from "@/lib/types/sessions";

const MONEY = (n: number) =>
  new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency: "COP",
    maximumFractionDigits: 0,
  }).format(n);

const PCT = (n: number) => `${(n * 100).toFixed(1)} %`;

/** Una sesión puede quedar abierta horas o días: "1284 min" no se lee. */
function duracion(minutos: number): string {
  if (minutos < 60) return `${Math.round(minutos)} min`;
  const horas = minutos / 60;
  if (horas < 24) {
    const h = Math.floor(horas);
    const m = Math.round(minutos - h * 60);
    return m === 0 ? `${h} h` : `${h} h ${m} min`;
  }
  const dias = Math.floor(horas / 24);
  const h = Math.round(horas - dias * 24);
  return h === 0
    ? `${dias} ${dias === 1 ? "día" : "días"}`
    : `${dias} ${dias === 1 ? "día" : "días"} ${h} h`;
}

export function SummaryPanel({ summary }: { summary: SessionSummaryResponse | null }) {
  if (!summary) return null;

  const gano = summary.net_change > 0;
  const plano = summary.net_change === 0;

  return (
    <Card className="border-gold/40">
      <CardHeader
        title="Resumen de la sesión"
        subtitle="Lo que ocurrió en esta mesa, de principio a fin."
      />

      <div
        className={`mb-4 rounded-lg border px-4 py-3 ${
          plano
            ? "border-edge bg-ink"
            : gano
              ? "border-signal-strong/40 bg-signal-strong/10"
              : "border-table-red/40 bg-table-red/10"
        }`}
      >
        <p className="text-xs text-muted">Resultado neto</p>
        <p
          className={`text-2xl font-bold tabular-nums ${
            plano ? "text-white" : gano ? "text-signal-strong" : "text-table-red"
          }`}
        >
          {summary.net_change >= 0 ? "+" : "−"}
          {MONEY(Math.abs(summary.net_change))}
        </p>
        <p className="mt-1 text-xs text-muted">
          De {MONEY(summary.bankroll_start)} a {MONEY(summary.bankroll_final)}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Dato label="Números registrados" valor={String(summary.total_spins)} />
        <Dato label="Apuestas resueltas" valor={String(summary.total_bets)} />
        <Dato label="Apuestas ganadas" valor={PCT(summary.win_rate)} />
        <Dato
          label="Peor caída"
          valor={MONEY(summary.max_drawdown)}
          tono={summary.max_drawdown > 0 ? "alerta" : undefined}
        />
        <Dato
          label="Progresión usada"
          valor={STRATEGY_LABEL[summary.strategy_used] ?? summary.strategy_used}
        />
        <Dato label="Duración" valor={duracion(summary.duration_minutes)} />
      </dl>

      {summary.total_bets > 0 ? (
        <p className="mt-3 text-xs leading-relaxed text-muted">
          Registraste una señal como motivo en el{" "}
          <span className="font-bold text-white">
            {PCT(summary.followed_suggestion_rate)}
          </span>{" "}
          de tus apuestas.
        </p>
      ) : null}

      {summary.max_drawdown > 0 ? (
        <p className="mt-3 rounded-lg border border-edge bg-ink px-3.5 py-3 text-xs leading-relaxed text-muted">
          La <span className="font-bold text-white">peor caída</span> es lo máximo que
          llegaste a estar por debajo de tu mejor momento de la sesión. Un resultado
          final parejo puede esconder un bajón grande por el camino, y es ese bajón el
          que agota una banca.
        </p>
      ) : null}

      <p className="mt-3 text-xs leading-relaxed text-muted">
        Esto describe una sesión que ya terminó. Ni un buen resultado ni uno malo dicen
        nada sobre la próxima: cada giro es independiente y la ventaja de la casa no
        cambia.
      </p>
    </Card>
  );
}

function Dato({
  label,
  valor,
  tono,
}: {
  label: string;
  valor: string;
  tono?: "alerta";
}) {
  return (
    <div className="rounded-lg border border-edge bg-ink px-3 py-2.5">
      <dt className="text-xs text-muted">{label}</dt>
      <dd
        className={`mt-0.5 text-sm font-bold tabular-nums ${
          tono === "alerta" ? "text-table-red" : "text-white"
        }`}
      >
        {valor}
      </dd>
    </div>
  );
}
