"use client";

/**
 * Guardar un medio de pago para la renovación automática (§3.4 y §3.6 de la Fase 4).
 *
 * Lo usan la pantalla de pago (alta con renovación automática) y `/cuenta`
 * (cambiar el medio de pago, o pasar de pago manual a renovación automática).
 *
 * Muestra los dos contratos de Wompi, que hay que aceptar antes, y abre su
 * ventana. Aquí no se escribe ningún dato de pago: eso ocurre en la ventana de
 * Wompi, y a esta página solo vuelve un token, que se entrega a `onSource`
 * junto con los tokens de aceptación. Qué se hace con él lo decide quien lo usa.
 */

import { useEffect, useState } from "react";

import { Button, Checkbox, ErrorBox } from "@/components/ui";
import { ApiError, billingApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import { openTokenizer } from "@/lib/tokenize";
import type { TokenizedSource } from "@/lib/tokenize";
import type { AcceptanceResponse, BillingAvailabilityResponse } from "@/lib/types/billing";

const LINK = "font-bold text-gold hover:text-gold-soft";

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

  async function open() {
    if (!acceptance) return;
    setError(null);
    if (availability.tokenizer === "fake") {
      onSource({ token: fakeToken, type: "CARD" }, acceptance);
      return;
    }
    if (!availability.public_key) return;
    try {
      await openTokenizer(
        availability.public_key,
        (source) => onSource(source, acceptance),
        () => setError("Ese medio de pago no se puede guardar para la renovación automática."),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo abrir el formulario de pago");
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-muted">
        Para guardar tu medio de pago, Wompi (el procesador de pagos) pide que aceptes sus dos
        documentos:
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
              términos de uso de Wompi
            </a>
            .
          </Checkbox>
          <Checkbox checked={dataAccepted} onChange={(e) => setDataAccepted(e.target.checked)}>
            Autorizo a Wompi el{" "}
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
        <p className="text-sm text-muted">Consultando a Wompi…</p>
      )}
      {availability.tokenizer === "fake" ? (
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
      ) : null}
      {error ? <ErrorBox message={error} /> : null}
      <Button
        onClick={open}
        disabled={disabled || busy || !acceptance || !termsAccepted || !dataAccepted}
      >
        {busy ? busyLabel : submitLabel}
      </Button>
      <p className="text-xs leading-relaxed text-muted">
        Al continuar se abre la ventana de Wompi para guardar tu tarjeta o tu Nequi. Sebasanálisis
        no recibe ni guarda los datos de tu tarjeta ni de tu cuenta: solo la referencia que
        entrega Wompi y, si es una tarjeta, la marca y los últimos cuatro dígitos.
      </p>
    </div>
  );
}
