"use client";

/**
 * La mesa dejó de ofrecer apuestas (decidido el 2026-09-24).
 *
 * Ocupa el lugar de la tarjeta de recomendación cuando el servidor devuelve
 * `stop_reason`: la banca ya no cubre la apuesta base, o se alcanzó el límite de
 * pérdida. La sesión no se cierra sola, a propósito: una sesión cerrada no
 * deja deshacer su último número, y si fue un error de ingreso el usuario
 * quedaría sin arreglo. Por eso la tarjeta recuerda "Deshacer último".
 */

import Link from "next/link";

import { Button, Card } from "@/components/ui";
import type { SessionResponse } from "@/lib/types/sessions";

const CURRENCY = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

export function StopCard({
  session,
  busy,
  onClose,
}: {
  session: SessionResponse;
  busy: boolean;
  onClose: () => void;
}) {
  const sinBanca = session.stop_reason === "bankroll_exhausted";
  const resultado = session.bankroll_current - session.bankroll_start;

  return (
    <Card className="border-table-red/40">
      <span className="inline-block rounded-full border border-table-red/50 bg-table-red/10 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider text-table-red">
        Dejar de apostar
      </span>
      <h2 className="mt-2 text-3xl font-bold leading-tight text-white sm:text-4xl">
        {sinBanca ? "BANCA AGOTADA" : "LÍMITE DE PÉRDIDA ALCANZADO"}
      </h2>

      <p className="mt-3 text-sm leading-relaxed text-muted">
        {sinBanca ? (
          <>
            Tu banca ({CURRENCY.format(session.bankroll_current)}) ya no cubre la
            apuesta base de {CURRENCY.format(session.base_bet)}. Lo recomendable es{" "}
            <span className="font-bold text-white">dejar de apostar en esta mesa</span>.
          </>
        ) : (
          <>
            Llevas {CURRENCY.format(session.bankroll_start - session.bankroll_current)}{" "}
            perdidos: alcanzaste el límite de{" "}
            {CURRENCY.format(session.loss_limit ?? 0)} que fijaste antes de empezar.
            Lo recomendable es{" "}
            <span className="font-bold text-white">parar aquí</span>.
          </>
        )}
      </p>
      <p className="mt-2 text-xs leading-relaxed text-muted">
        Reponer la banca o subir el límite para recuperar lo perdido no cambia la
        ventaja de la casa. Esta mesa ya no acepta apuestas.
      </p>

      <dl className="mt-4 grid grid-cols-3 gap-2 rounded-lg border border-edge bg-ink-sunken px-3.5 py-3 text-center">
        <div>
          <dt className="text-xs text-muted">Banca inicial</dt>
          <dd className="text-sm font-bold tabular-nums text-white">
            {CURRENCY.format(session.bankroll_start)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Banca actual</dt>
          <dd className="text-sm font-bold tabular-nums text-white">
            {CURRENCY.format(session.bankroll_current)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Resultado</dt>
          <dd
            className={`text-sm font-bold tabular-nums ${resultado < 0 ? "text-table-red" : "text-white"}`}
          >
            {resultado < 0 ? "−" : "+"}
            {CURRENCY.format(Math.abs(resultado))}
          </dd>
        </div>
      </dl>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button disabled={busy} onClick={onClose}>
          Cerrar mesa
        </Button>
        <Link
          href="/dashboard#abrir-mesa"
          className="rounded-lg border border-edge bg-ink-sunken px-4 py-2.5 text-sm font-bold text-white transition-colors hover:border-gold/50"
        >
          Abrir una mesa nueva
        </Link>
      </div>

      <p className="mt-4 border-t border-edge pt-3 text-xs leading-relaxed text-muted">
        ¿Un número quedó mal ingresado? Usa{" "}
        <span className="font-bold text-white">Deshacer último</span> en la mesa: si
        la banca vuelve a cubrir la apuesta base, la mesa sigue como antes.
      </p>
    </Card>
  );
}
