"use client";

/**
 * Guardar un medio de pago para la renovación automática (§3.4 y §3.6 de la Fase 4).
 *
 * Lo usan la pantalla de pago (alta con renovación automática) y `/cuenta`
 * (cambiar el medio de pago, o pasar de pago manual a renovación automática).
 * Es el único lugar del frontend donde se guarda un medio de pago.
 *
 * Muestra los dos contratos de la pasarela, que hay que aceptar antes, y pide
 * el token del medio de pago. Hoy solo existe el selector de la pasarela
 * simulada: el formulario de tarjeta y Nequi era de la pasarela anterior y
 * salió con ella (paso 5.1 de la Fase 5). La pasarela nueva trae aquí su forma
 * de tokenizar (5.3); sin pasarela, quien lo usa no lo muestra.
 *
 * El token se entrega a `onSource` junto con los tokens de aceptación. Qué se
 * hace con él lo decide quien lo usa.
 */

import { useEffect, useState } from "react";

import { Button, Checkbox, ErrorBox } from "@/components/ui";
import { ApiError, billingApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type {
  AcceptanceResponse,
  BillingAvailabilityResponse,
  PaymentSourceKind,
} from "@/lib/types/billing";

const LINK = "font-bold text-gold hover:text-gold-soft";

/** Lo que la pasarela le entrega al navegador por un medio de pago. No son datos de tarjeta. */
export interface TokenizedSource {
  token: string;
  type: PaymentSourceKind;
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
  onSource: (source: TokenizedSource, acceptance: AcceptanceResponse) => void;
}) {
  const { withToken } = useSession();
  const [acceptance, setAcceptance] = useState<AcceptanceResponse | null>(null);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [dataAccepted, setDataAccepted] = useState(false);
  const [fakeToken, setFakeToken] = useState(FAKE_SOURCES[0][0]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    withToken((t) => billingApi.acceptance(t))
      .then((found) => {
        if (!cancelled) setAcceptance(found);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof ApiError ? e.message : "No se pudo consultar al procesador de pagos",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [withToken]);

  const fake = availability.tokenizer === "fake";
  const ready = !!acceptance && termsAccepted && dataAccepted;

  function saveFake() {
    if (!acceptance) return;
    setError(null);
    onSource({ token: fakeToken, type: "CARD" }, acceptance);
  }

  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-muted">
        Para guardar tu medio de pago, la pasarela (el procesador de pagos) pide que aceptes sus
        dos documentos:
      </p>
      {acceptance ? (
        <>
          <Checkbox checked={termsAccepted} onChange={(e) => setTermsAccepted(e.target.checked)}>
            Acepto los{" "}
            <a
              href={acceptance.terms_url}
              target="_blank"
              rel="noopener noreferrer"
              className={LINK}
            >
              términos de uso de la pasarela
            </a>
            .
          </Checkbox>
          <Checkbox checked={dataAccepted} onChange={(e) => setDataAccepted(e.target.checked)}>
            Autorizo a la pasarela el{" "}
            <a
              href={acceptance.personal_data_url}
              target="_blank"
              rel="noopener noreferrer"
              className={LINK}
            >
              tratamiento de mis datos personales
            </a>
            .
          </Checkbox>
        </>
      ) : error ? null : (
        <p className="text-sm text-muted">Consultando a la pasarela…</p>
      )}

      {fake ? (
        <>
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
          {error ? <ErrorBox message={error} /> : null}
          <Button onClick={saveFake} disabled={disabled || busy || !ready}>
            {busy ? busyLabel : submitLabel}
          </Button>
        </>
      ) : error ? (
        <ErrorBox message={error} />
      ) : null}

      <p className="text-xs leading-relaxed text-muted">
        Sebasanálisis no recibe ni guarda los datos de tu tarjeta ni de tu cuenta: solo la
        referencia que entrega la pasarela y, si es una tarjeta, la marca y los últimos cuatro
        dígitos.
      </p>
    </div>
  );
}
