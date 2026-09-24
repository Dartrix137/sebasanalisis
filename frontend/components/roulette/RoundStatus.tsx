"use client";

/**
 * Qué dejó el último número, en la mesa.
 *
 * Separa las dos cosas que un giro mueve:
 *
 * - la banca, con todas las apuestas que el usuario registró;
 * - el escalón de cada progresión, solo si se apostó con esa gestión, según
 *   cómo cerró la recomendación.
 */

import type { BankrollStrategy } from "@/lib/types/sessions";

const CON_GESTION: Record<BankrollStrategy, string> = {
  flat: "la gestión plana",
  martingale: "martingala",
  two_sector_recovery: "la recuperación de 2 sectores",
};

import type { BetResponse } from "@/lib/types/bets";
import type { SessionResponse } from "@/lib/types/sessions";
import type { SpinResponse } from "@/lib/types/spins";
import type { RecommendationRecord } from "@/lib/types/suggestions";

const MONEY = (n: number) =>
  new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency: "COP",
    maximumFractionDigits: 0,
  }).format(n);

const SIGNED = (n: number) => `${n >= 0 ? "+" : "−"}${MONEY(Math.abs(n))}`;

export function RoundStatus({
  session,
  lastSpin,
  previousSpin,
  bets,
  history,
}: {
  session: SessionResponse;
  lastSpin: SpinResponse | null;
  previousSpin: SpinResponse | null;
  bets: BetResponse[];
  history: RecommendationRecord[];
}) {
  const lostSoFar = session.bankroll_start - session.bankroll_current;

  return (
    <section aria-label="Último giro" className="space-y-2">
      {lastSpin && lastSpin.source === "manual" ? (
        <>
          <MoneyLine lastSpin={lastSpin} bets={bets} />
          <ProgressionLine
            session={session}
            lastSpin={lastSpin}
            bets={bets}
            // La recomendación que se jugó en este giro es la que se emitió tras
            // el anterior.
            record={
              previousSpin
                ? (history.find((r) => r.spin_id === previousSpin.id) ?? null)
                : null
            }
          />
        </>
      ) : null}

      <p className="text-xs text-muted">
        {session.loss_limit === null ? (
          "Sin límite de pérdida: puedes fijarlo en Ajustes de la sesión."
        ) : (
          <>
            Límite de pérdida: te quedan{" "}
            <span className="font-bold text-white">
              {/* Ir ganando no agranda el límite a la vista. */}
              {MONEY(
                Math.min(session.loss_limit, Math.max(session.loss_limit - lostSoFar, 0)),
              )}
            </span>{" "}
            de {MONEY(session.loss_limit)}.
          </>
        )}
      </p>
    </section>
  );
}

function MoneyLine({ lastSpin, bets }: { lastSpin: SpinResponse; bets: BetResponse[] }) {
  const resueltas = bets.filter((b) => b.spin_id === lastSpin.id && b.status === "resolved");
  const neto = resueltas.reduce((acc, b) => acc + (b.net_change ?? 0), 0);

  if (resueltas.length === 0) {
    return (
      <p className="rounded-lg border border-edge bg-ink px-3 py-2.5 text-sm text-muted">
        Salió el <span className="font-bold text-white">{lastSpin.result_value}</span>. No
        registraste apuesta: tu banca no cambió.
      </p>
    );
  }

  const gano = neto > 0;
  const perdio = neto < 0;
  return (
    <p
      role="status"
      className={`rounded-lg border px-3 py-2.5 text-sm font-bold text-white ${
        gano
          ? "border-signal-strong/50 bg-signal-strong/10"
          : perdio
            ? "border-table-red/40 bg-table-red/10"
            : "border-edge bg-ink"
      }`}
    >
      {gano
        ? `Ganaste ${SIGNED(neto)} con el ${lastSpin.result_value}`
        : perdio
          ? `Perdiste ${SIGNED(neto)} con el ${lastSpin.result_value}`
          : `El ${lastSpin.result_value} dejó la ronda en $ 0`}
    </p>
  );
}

function ProgressionLine({
  session,
  lastSpin,
  bets,
  record,
}: {
  session: SessionResponse;
  lastSpin: SpinResponse;
  bets: BetResponse[];
  record: RecommendationRecord | null;
}) {
  if (record === null) return null;

  if (record.decision === "NO_BET") {
    return (
      <p className="text-xs leading-relaxed text-muted">
        En ese giro el motor no recomendó apostar: las progresiones no se movieron.
      </p>
    );
  }

  // Sin resolver: el mercado ya no existe en la variante y no movió nada.
  if (record.outcome === "PENDING") return null;

  const seguidas = new Set<BankrollStrategy>();
  for (const b of bets) {
    if (b.spin_id === lastSpin.id && b.strategy !== null) seguidas.add(b.strategy);
  }
  const dentro = record.outcome === "HIT";
  const cambios = (
    [
      ["Martingala", lastSpin.stage_martingale_before, session.stage_martingale],
      ["2 sectores", lastSpin.stage_two_sector_before, session.stage_two_sector],
    ] as const
  ).filter(([, antes, ahora]) => antes !== null && antes !== ahora);

  let efecto: string;
  if (seguidas.size === 0) {
    efecto = "No anotaste apuesta con ninguna gestión: los escalones no se movieron.";
  } else if (cambios.length === 0) {
    const nombres = [...seguidas].map((s) => CON_GESTION[s]).join(" y ");
    efecto =
      seguidas.size === 1 && seguidas.has("flat")
        ? "Apostaste con la gestión plana: su monto no cambia."
        : `Apostaste con ${nombres}: el escalón sigue igual.`;
  } else {
    efecto = cambios
      .map(([nombre, antes, ahora]) => `${nombre}: escalón ${antes! + 1} → ${ahora + 1}`)
      .join(" · ")
      .concat(".");
  }

  return (
    <p className="text-xs leading-relaxed text-muted">
      La recomendación era{" "}
      <span className="font-bold text-white">{record.option_label}</span> y el{" "}
      {lastSpin.result_value} quedó {dentro ? "dentro" : "fuera"}. {efecto}
    </p>
  );
}
