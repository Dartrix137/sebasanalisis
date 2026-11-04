"use client";

/**
 * Guardar un medio de pago para la renovación automática (§3.4 y §3.6 de la Fase 4).
 *
 * Lo usan la pantalla de pago (alta con renovación automática) y `/cuenta`
 * (cambiar el medio de pago, o pasar de pago manual a renovación automática).
 * Es el único lugar del frontend donde se guarda un medio de pago.
 *
 * Hoy solo existe el selector de la pasarela simulada. Tipster Page no tiene
 * cobros recurrentes (2026-11-03): con ella `availability.tokenizer` es null y
 * quien usa este formulario no lo muestra. Los dos contratos de aceptación eran
 * de Wompi y salieron en el paso 5.3 de la Fase 5.
 *
 * El token se entrega a `onSource`. Qué se hace con él lo decide quien lo usa.
 */

import { useState } from "react";

import { Button } from "@/components/ui";
import type { BillingAvailabilityResponse } from "@/lib/types/billing";

/** Lo que la pasarela le entrega al navegador por un medio de pago. No son datos de tarjeta. */
export interface TokenizedSource {
  token: string;
  /** El tipo de medio, en el vocabulario de la pasarela. */
  type: string;
}

/** Los "medios de pago" de la pasarela simulada (solo desarrollo y pruebas). */
const FAKE_SOURCES: [string, string][] = [
  ["fake-token-ok", "Tarjeta simulada: cobros aprobados"],
  ["fake-token-declined", "Tarjeta simulada: cobros rechazados"],
  ["fake-token-rejected", "Tarjeta simulada: no se puede guardar"],
];

export function PaymentSourceForm({
  availability,
  submitLabel,
  busyLabel,
  busy,
  disabled = false,
  onSource,
}: {
  availability: BillingAvailabilityResponse;
  submitLabel: string;
  busyLabel: string;
  /** Quien lo usa está enviando el medio al servidor. */
  busy: boolean;
  disabled?: boolean;
  onSource: (source: TokenizedSource) => void;
}) {
  const [fakeToken, setFakeToken] = useState(FAKE_SOURCES[0][0]);

  if (availability.tokenizer !== "fake") return null;

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="mb-1.5 block text-sm font-bold text-white">
          Medio de pago simulado (solo pruebas)
        </span>
        <select
          value={fakeToken}
          onChange={(e) => setFakeToken(e.target.value)}
          className="w-full rounded-lg border border-edge bg-ink-sunken px-3 py-2.5 text-sm text-white outline-none focus:border-gold/60"
        >
          {FAKE_SOURCES.map(([value, text]) => (
            <option key={value} value={value}>
              {text}
            </option>
          ))}
        </select>
      </label>
      <Button
        onClick={() => onSource({ token: fakeToken, type: "CARD" })}
        disabled={disabled || busy}
      >
        {busy ? busyLabel : submitLabel}
      </Button>

      <p className="text-xs leading-relaxed text-muted">
        Sebasanálisis no recibe ni guarda los datos de tu tarjeta ni de tu cuenta: solo la
        referencia que entrega la pasarela y, si es una tarjeta, la marca y los últimos cuatro
        dígitos.
      </p>
    </div>
  );
}
