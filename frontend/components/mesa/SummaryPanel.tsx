"use client";

/**
 * Resumen de la sesión (§4). Aparece cuando la sesión se cierra.
 *
 * Todo lo que muestra describe lo que ya ocurrió: no es una tasa de acierto del
 * motor ni dice nada sobre las próximas — la ventaja de la casa no cambió.
 * Desde el 2026-10-15 las apuestas se cuentan por giro (`BetStats`), con lo
 * esperable por azar al lado; antes se contaba cada casilla por separado.
 */

import { Card, CardHeader } from "@/components/ui";
import { BetStats } from "@/components/mesa/BetStats";
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

      <div className="mb-4">
        <p className="text-xs text-muted">Resultado neto</p>
        <p
          className={`font-display text-5xl font-semibold leading-none tabular-nums ${
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

      <dl className="mb-4 grid grid-cols-3 gap-x-4 gap-y-3 border-y border-edge py-3">
        <Dato label="Números registrados" valor={String(summary.total_spins)} />
        <Dato label="Giros apostados" valor={String(summary.rounds_bet)} />
        <Dato label="Duración" valor={duracion(summary.duration_minutes)} />
      </dl>

      {/* Las cifras por giro, las mismas que la mesa muestra en "Apuestas de esta sesión". */}
      <BetStats summary={summary} withNet={false} />

      {summary.total_bets > 0 ? (
        <p className="mt-3 text-xs leading-relaxed text-muted">
          Registraste una señal como motivo en el{" "}
          <span className="font-bold text-white">
            {PCT(summary.followed_suggestion_rate)}
          </span>{" "}
          de tus apuestas.
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
    <div>
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
