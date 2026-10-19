"use client";

/**
 * Las apuestas de la sesión contadas por giro (pedido del 2026-10-15).
 *
 * Va en "Apuestas de esta sesión" mientras la mesa está abierta y en el
 * resumen al cerrarla. Las cifras las calcula el servidor
 * (`engine/session_stats.py`); aquí solo se pintan.
 *
 * - Se cuenta por giro: dos docenas son dos apuestas y un solo giro, que cuenta
 *   con ganancia si cerró con neto positivo.
 * - Los giros con ganancia van siempre con lo esperable por azar con esas
 *   mismas apuestas (regla anti-falacia del jugador, §2): un 43 % solo no dice
 *   si es mucho o poco. Por eso no se llama "efectividad": describe lo que pasó,
 *   no una capacidad del motor.
 */

import type { SessionSummaryResponse } from "@/lib/types/sessions";

const MONEY = (n: number) =>
  new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency: "COP",
    maximumFractionDigits: 0,
  }).format(n);

const SIGNED = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${MONEY(Math.abs(n))}`;

const PCT = (n: number) => `${(n * 100).toFixed(1)} %`;

export function BetStats({ summary }: { summary: SessionSummaryResponse }) {
  if (summary.rounds_bet === 0) return null;

  return (
    <div data-testid="estadisticas-apuestas">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Dato
          label="Giros con ganancia"
          valor={`${summary.rounds_won} de ${summary.rounds_bet} · ${PCT(
            summary.rounds_won / summary.rounds_bet,
          )}`}
        />
        <Dato
          label="Lo esperable por azar"
          valor={PCT(summary.rounds_won_expected_rate)}
          nota="con esas mismas apuestas"
        />
        <Dato
          label="Resultado neto"
          valor={SIGNED(summary.net_change)}
          tono={summary.net_change > 0 ? "bien" : summary.net_change < 0 ? "alerta" : undefined}
        />
        <Dato label="Mejor momento" valor={SIGNED(summary.best_moment)} />
        <Dato
          label="Peor caída"
          valor={summary.max_drawdown > 0 ? SIGNED(-summary.max_drawdown) : MONEY(0)}
          tono={summary.max_drawdown > 0 ? "alerta" : undefined}
        />
      </dl>
      <p className="mt-2 text-xs leading-relaxed text-muted">
        Cuenta por giro: dos docenas en el mismo giro son un solo giro, con ganancia si
        cerró en positivo. Lo esperable por azar es lo que cabía esperar con esas mismas
        apuestas en una mesa justa. El mejor momento es lo más que la banca llegó a estar
        por encima de la inicial, y la peor caída, lo máximo que bajó desde su mejor punto.
        Describe lo que ya pasó: no dice nada de los próximos giros, y la ventaja de la
        casa no cambia.
      </p>
    </div>
  );
}

function Dato({
  label,
  valor,
  nota,
  tono,
}: {
  label: string;
  valor: string;
  nota?: string;
  tono?: "alerta" | "bien";
}) {
  return (
    <div className="rounded-lg border border-edge bg-ink px-3 py-2.5">
      <dt className="text-xs text-muted">{label}</dt>
      <dd
        className={`mt-0.5 text-sm font-bold tabular-nums ${
          tono === "alerta"
            ? "text-table-red"
            : tono === "bien"
              ? "text-signal-strong"
              : "text-white"
        }`}
      >
        {valor}
      </dd>
      {nota ? <dd className="text-[11px] text-muted">{nota}</dd> : null}
    </div>
  );
}
