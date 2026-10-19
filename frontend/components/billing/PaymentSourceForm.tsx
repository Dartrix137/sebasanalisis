"use client";

/**
 * Guardar un medio de pago para la renovación automática (§3.4, §3.6 y §3.16 de la Fase 4).
 *
 * Lo usan la pantalla de pago (alta con renovación automática) y `/cuenta`
 * (cambiar el medio de pago, o pasar de pago manual a renovación automática).
 * Es el único lugar del frontend donde se guarda un medio de pago.
 *
 * Muestra los dos contratos de Wompi, que hay que aceptar antes, y pide el
 * token a Wompi desde el navegador (`lib/tokenize.ts`):
 *
 * - **Tarjeta**: se escribe aquí, se cifra con la llave de Wompi y va directo a
 *   su API. Los datos de la tarjeta no pasan por nuestro servidor y se borran
 *   del formulario al terminar, salga bien o mal.
 * - **Nequi**: el cliente escribe su celular, acepta la solicitud en su app y
 *   aquí se espera la aprobación, con un tiempo límite.
 *
 * El token se entrega a `onSource` junto con los tokens de aceptación. Qué se
 * hace con él lo decide quien lo usa.
 */

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { Button, Checkbox, ErrorBox, Field } from "@/components/ui";
import { ApiError, billingApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import {
  TokenizeError,
  cardProblem,
  nequiPhoneValid,
  nequiStatus,
  onlyDigits,
  startNequi,
  tokenizeCard,
} from "@/lib/tokenize";
import type { CardInput, NequiStatus, TokenizedSource, TokenizerTarget } from "@/lib/tokenize";
import type { AcceptanceResponse, BillingAvailabilityResponse } from "@/lib/types/billing";

const LINK = "font-bold text-gold hover:text-gold-soft";

/** Los "medios de pago" de la pasarela simulada (solo desarrollo y pruebas). */
const FAKE_SOURCES: [string, string][] = [
  ["fake-token-ok", "Tarjeta simulada: cobros aprobados"],
  ["fake-token-declined", "Tarjeta simulada: cobros rechazados"],
  ["fake-token-rejected", "Tarjeta simulada: no se puede guardar"],
];

/** Cuánto se espera a que el cliente apruebe en su app de Nequi, y cada cuánto se consulta. */
export const NEQUI_TIMEOUT_MS = 3 * 60_000;
export const NEQUI_POLL_MS = 3_000;

const EMPTY_CARD: CardInput = { number: "", cvc: "", expMonth: "", expYear: "", holder: "" };

const UNEXPECTED = "No se pudo guardar el medio de pago. Intenta de nuevo.";

type Method = "CARD" | "NEQUI";

/**
 * - `idle`: el formulario, listo para enviar.
 * - `tokenizing`: la tarjeta o el celular van camino a Wompi.
 * - `nequi_waiting`: Wompi envió la solicitud; se espera la aprobación en la app.
 * - `nequi_failed`: Nequi la rechazó o se acabó el tiempo; se puede reintentar.
 */
type Stage = "idle" | "tokenizing" | "nequi_waiting" | "nequi_failed";

/** El mes con dos dígitos y el año con los dos últimos, como los pide Wompi. */
function normalizeExpiry(card: CardInput): CardInput {
  const month = onlyDigits(card.expMonth);
  const year = onlyDigits(card.expYear);
  return {
    ...card,
    expMonth: month.length === 1 ? `0${month}` : month,
    // El autocompletado del navegador puede llenar el año con cuatro dígitos.
    expYear: year.length === 4 ? year.slice(2) : year,
  };
}

function messageOf(err: unknown): string {
  return err instanceof TokenizeError || err instanceof ApiError ? err.message : UNEXPECTED;
}

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
  const [method, setMethod] = useState<Method>("CARD");
  const [card, setCard] = useState<CardInput>(EMPTY_CARD);
  const [phone, setPhone] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [nequiToken, setNequiToken] = useState<string | null>(null);
  const [nequiDeadline, setNequiDeadline] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // La espera de Nequi no se reinicia porque quien lo usa vuelva a pintar.
  const onSourceRef = useRef(onSource);
  useEffect(() => {
    onSourceRef.current = onSource;
  });

  const { public_key: publicKey, api_base_url: apiBaseUrl } = availability;

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

  // Espera la aprobación de Nequi. Un error de red no corta la espera: se
  // sigue consultando hasta el tiempo límite.
  useEffect(() => {
    if (stage !== "nequi_waiting" || !nequiToken || !acceptance) return;
    if (!publicKey || !apiBaseUrl) return;
    const target: TokenizerTarget = { publicKey, apiBaseUrl };
    const token = nequiToken;
    const accepted = acceptance;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      let status: NequiStatus = "pending";
      try {
        status = await nequiStatus(target, token);
      } catch {
        // Transitorio: se vuelve a consultar.
      }
      if (cancelled) return;
      if (status === "approved") {
        setStage("idle");
        setNequiToken(null);
        onSourceRef.current({ token, type: "NEQUI" }, accepted);
      } else if (status === "rejected") {
        setStage("nequi_failed");
        setNequiToken(null);
        setError("Nequi no aprobó la solicitud. Puedes volver a intentarlo o usar una tarjeta.");
      } else if (Date.now() >= nequiDeadline) {
        setStage("nequi_failed");
        setNequiToken(null);
        setError("No recibimos la aprobación de Nequi a tiempo. Puedes volver a intentarlo.");
      } else {
        timer = setTimeout(poll, NEQUI_POLL_MS);
      }
    }

    timer = setTimeout(poll, NEQUI_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [stage, nequiToken, nequiDeadline, acceptance, publicKey, apiBaseUrl]);

  const fake = availability.tokenizer === "fake";
  const target: TokenizerTarget | null =
    publicKey && apiBaseUrl ? { publicKey, apiBaseUrl } : null;
  const ready = !!acceptance && termsAccepted && dataAccepted;
  const locked = disabled || busy || stage === "tokenizing" || stage === "nequi_waiting";

  function chooseMethod(next: Method) {
    setMethod(next);
    setError(null);
    if (stage === "nequi_failed") setStage("idle");
  }

  function saveFake() {
    if (!acceptance) return;
    setError(null);
    onSource({ token: fakeToken, type: "CARD" }, acceptance);
  }

  async function saveCard(e: FormEvent) {
    e.preventDefault();
    if (!acceptance || !target || locked || !ready) return;
    const input = normalizeExpiry(card);
    const problem = cardProblem(input);
    if (problem) {
      // Aquí no salió nada: se deja corregir sin volver a escribir todo.
      setError(problem);
      return;
    }
    setError(null);
    setStage("tokenizing");
    try {
      const { encryption_key } = await withToken((t) => billingApi.cardEncryptionKey(t));
      const source = await tokenizeCard(target, encryption_key, input);
      onSource(source, acceptance);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      // Salga bien o mal, la tarjeta no se queda en el formulario.
      setCard(EMPTY_CARD);
      setStage("idle");
    }
  }

  async function saveNequi(e: FormEvent) {
    e.preventDefault();
    if (!acceptance || !target || locked || !ready) return;
    const number = onlyDigits(phone);
    if (!nequiPhoneValid(number)) {
      setError("Escribe el celular de tu cuenta Nequi: diez dígitos, empezando por 3.");
      return;
    }
    setError(null);
    setStage("tokenizing");
    try {
      const started = await startNequi(target, number);
      if (started.status === "approved") {
        setStage("idle");
        onSource({ token: started.token, type: "NEQUI" }, acceptance);
        return;
      }
      if (started.status === "rejected") {
        setStage("nequi_failed");
        setError("Nequi no aprobó la solicitud. Puedes volver a intentarlo o usar una tarjeta.");
        return;
      }
      setNequiToken(started.token);
      setNequiDeadline(Date.now() + NEQUI_TIMEOUT_MS);
      setStage("nequi_waiting");
    } catch (err) {
      setStage("idle");
      setError(messageOf(err));
    }
  }

  function stopWaiting() {
    setNequiToken(null);
    setStage("idle");
  }

  const submitText = busy
    ? busyLabel
    : stage === "tokenizing"
      ? method === "CARD"
        ? "Enviando la tarjeta a Wompi…"
        : "Enviando la solicitud a Nequi…"
      : stage === "nequi_failed"
        ? "Volver a intentar"
        : submitLabel;

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
      ) : (
        <>
          <fieldset disabled={locked}>
            <legend className="mb-2 text-sm font-bold text-white">Medio de pago</legend>
            <div className="flex flex-wrap gap-4">
              {(
                [
                  ["CARD", "Tarjeta de crédito o débito"],
                  ["NEQUI", "Nequi"],
                ] as const
              ).map(([value, text]) => (
                <label key={value} className="flex items-center gap-2 text-sm text-white">
                  <input
                    type="radio"
                    name="payment-source-method"
                    value={value}
                    checked={method === value}
                    onChange={() => chooseMethod(value)}
                    className="h-4 w-4 accent-gold"
                  />
                  {text}
                </label>
              ))}
            </div>
          </fieldset>

          {method === "CARD" ? (
            <form onSubmit={saveCard} noValidate className="space-y-3" aria-label="Datos de la tarjeta">
              <fieldset disabled={locked} className="space-y-3">
                <Field
                  label="Número de la tarjeta"
                  inputMode="numeric"
                  autoComplete="cc-number"
                  maxLength={23}
                  value={card.number}
                  onChange={(e) => setCard({ ...card, number: e.target.value })}
                />
                <div className="grid grid-cols-3 gap-3">
                  <Field
                    label="Mes"
                    placeholder="MM"
                    inputMode="numeric"
                    autoComplete="cc-exp-month"
                    maxLength={2}
                    value={card.expMonth}
                    onChange={(e) => setCard({ ...card, expMonth: e.target.value })}
                  />
                  <Field
                    label="Año"
                    placeholder="AA"
                    inputMode="numeric"
                    autoComplete="cc-exp-year"
                    maxLength={4}
                    value={card.expYear}
                    onChange={(e) => setCard({ ...card, expYear: e.target.value })}
                  />
                  <Field
                    label="CVC"
                    inputMode="numeric"
                    autoComplete="cc-csc"
                    maxLength={4}
                    value={card.cvc}
                    onChange={(e) => setCard({ ...card, cvc: e.target.value })}
                  />
                </div>
                <Field
                  label="Nombre del titular"
                  hint="Como aparece en la tarjeta."
                  autoComplete="cc-name"
                  maxLength={100}
                  value={card.holder}
                  onChange={(e) => setCard({ ...card, holder: e.target.value })}
                />
              </fieldset>
              {error ? <ErrorBox message={error} /> : null}
              <Button type="submit" disabled={locked || !ready || !target}>
                {submitText}
              </Button>
            </form>
          ) : (
            <form onSubmit={saveNequi} noValidate className="space-y-3" aria-label="Cuenta Nequi">
              <fieldset disabled={locked}>
                <Field
                  label="Celular de tu cuenta Nequi"
                  type="tel"
                  inputMode="numeric"
                  autoComplete="tel-national"
                  maxLength={13}
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </fieldset>
              {stage === "nequi_waiting" ? (
                <div role="status" className="space-y-3 rounded-lg border border-gold/40 p-3.5">
                  <p className="text-sm leading-relaxed text-white">
                    Wompi envió una solicitud a tu app Nequi. Ábrela y acéptala para autorizar los
                    cobros de la renovación automática. Te esperamos hasta 3 minutos.
                  </p>
                  <p className="text-sm text-muted">Esperando tu aprobación…</p>
                  <Button type="button" variant="ghost" onClick={stopWaiting}>
                    Cancelar
                  </Button>
                </div>
              ) : null}
              {error ? <ErrorBox message={error} /> : null}
              {stage === "nequi_waiting" ? null : (
                <Button type="submit" disabled={locked || !ready || !target}>
                  {submitText}
                </Button>
              )}
            </form>
          )}
        </>
      )}

      <p className="text-xs leading-relaxed text-muted">
        Los datos de tu tarjeta van cifrados directo a Wompi. Sebasanálisis no recibe ni guarda los
        datos de tu tarjeta ni de tu cuenta: solo la referencia que entrega Wompi y, si es una
        tarjeta, la marca y los últimos cuatro dígitos.
      </p>
    </div>
  );
}
