/**
 * Pide a Wompi el token de un medio de pago, desde el navegador (§3.16 de la Fase 4).
 *
 * La tarjeta se escribe en nuestro formulario (`PaymentSourceForm`) y de aquí
 * va directo a la API de Wompi: nunca pasa por nuestro servidor, ni por un log,
 * ni por el monitoreo, ni por `localStorage`. A nuestro servidor solo llega el
 * token que devuelve Wompi, y él crea la fuente de pago con la llave privada.
 *
 * Documentación oficial de Wompi, consultada el 2026-10-19:
 *
 * - "Fuentes de pago": https://docs.wompi.co/docs/colombia/fuentes-de-pago/
 * - "Tokeniza una tarjeta":
 *   https://docs.wompi.co/docs/colombia/metodos-de-pago/#tokeniza-una-tarjeta
 * - Datos de prueba: https://docs.wompi.co/docs/colombia/datos-de-prueba-en-sandbox/
 *
 * Tarjeta, flujo cifrado (el que recomienda la documentación): la llave RSA de
 * `GET /v1/tokens/keys/tokenization` cifra un JWE (RSA-OAEP-256, A256GCM) con
 * `number`, `cvc`, `exp_month` y `exp_year` (dos dígitos cada uno) y
 * `card_holder`, que va en `payload` a `POST /v1/tokens/cards` con la llave
 * pública del comercio como Bearer. El token viene en `data.id`. Un token no se
 * usa más de dos veces: cada intento de guardar pide uno nuevo.
 *
 * La llave RSA la pide nuestro servidor (`GET /billing/card-encryption-key`):
 * el 2026-10-19 ese endpoint de Wompi no admitía llamadas desde el navegador
 * (su respuesta no trae `Access-Control-Allow-Origin`). `POST /v1/tokens/cards`
 * y los de Nequi sí las admiten. La llave no es un secreto.
 *
 * Nequi: `POST /v1/tokens/nequi` con `phone_number` devuelve un token `PENDING`;
 * el cliente acepta la suscripción en su app y `GET /v1/tokens/nequi/{id}` pasa
 * a `APPROVED`. Solo entonces sirve para crear la fuente de pago.
 *
 * El JWE lo arma `jose` (6.2.12), la misma librería del ejemplo de la
 * documentación. Probado contra el sandbox el 2026-10-19.
 */

import { EncryptJWT, importSPKI } from "jose";

import type { PaymentSourceKind } from "./types/billing";

export interface TokenizedSource {
  token: string;
  type: PaymentSourceKind;
}

/** Lo que el cliente escribe en el formulario. Nunca sale de este archivo salvo cifrado. */
export interface CardInput {
  number: string;
  cvc: string;
  /** Dos dígitos: "01" a "12". */
  expMonth: string;
  /** Dos dígitos: "30" es 2030. */
  expYear: string;
  holder: string;
}

/** A quién y con qué llave se le piden los tokens. */
export interface TokenizerTarget {
  /** La API de Wompi del ambiente de las llaves (`GET /billing/availability`). */
  apiBaseUrl: string;
  /** La llave PÚBLICA del comercio. */
  publicKey: string;
}

/**
 * Un error al tokenizar, ya en palabras para el cliente. Nunca lleva el cuerpo
 * de la respuesta de Wompi: trae datos de la tarjeta (titular, primeros dígitos).
 */
export class TokenizeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TokenizeError";
  }
}

const WOMPI_UNREACHABLE = "No pudimos comunicarnos con Wompi. Intenta de nuevo en unos minutos.";
const CARD_REJECTED =
  "Wompi no aceptó los datos de la tarjeta. Revísalos y vuelve a escribirlos.";
const NEQUI_REJECTED = "Wompi no aceptó ese número de Nequi. Revísalo e intenta de nuevo.";

// ---------- Validación en el navegador ----------

export function onlyDigits(value: string): string {
  return value.replace(/\D/g, "");
}

/** Algoritmo de Luhn, sobre 13 a 19 dígitos. */
export function luhnValid(number: string): boolean {
  const digits = onlyDigits(number);
  if (digits !== number.replace(/[\s-]/g, "")) return false;
  if (digits.length < 13 || digits.length > 19) return false;
  let sum = 0;
  for (let i = 0; i < digits.length; i++) {
    let d = Number(digits[digits.length - 1 - i]);
    if (i % 2 === 1) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
  }
  return sum % 10 === 0;
}

/** Mes y año de dos dígitos, sin vencer: la tarjeta vale hasta el último día de su mes. */
export function expiryValid(expMonth: string, expYear: string, now: Date = new Date()): boolean {
  if (!/^\d{2}$/.test(expMonth) || !/^\d{2}$/.test(expYear)) return false;
  const month = Number(expMonth);
  if (month < 1 || month > 12) return false;
  const year = 2000 + Number(expYear);
  const current = now.getFullYear() * 12 + now.getMonth();
  return year * 12 + (month - 1) >= current;
}

export function cvcValid(cvc: string): boolean {
  return /^\d{3,4}$/.test(cvc);
}

/** Celular colombiano: diez dígitos que empiezan por 3. */
export function nequiPhoneValid(phone: string): boolean {
  return /^3\d{9}$/.test(phone);
}

/** El primer problema de la tarjeta, en palabras para el cliente, o null si está bien. */
export function cardProblem(card: CardInput, now: Date = new Date()): string | null {
  if (!luhnValid(card.number)) return "Revisa el número de la tarjeta.";
  if (!/^\d{2}$/.test(card.expMonth) || !/^\d{2}$/.test(card.expYear)) {
    return "Escribe el mes y el año de vencimiento con dos dígitos cada uno (por ejemplo, 08 y 30).";
  }
  if (!expiryValid(card.expMonth, card.expYear, now)) {
    return "La fecha de vencimiento no es válida o la tarjeta ya venció.";
  }
  if (!cvcValid(card.cvc)) return "El código de seguridad (CVC) tiene 3 o 4 dígitos.";
  if (!card.holder.trim()) return "Escribe el nombre del titular como aparece en la tarjeta.";
  return null;
}

// ---------- Llamadas a Wompi ----------

async function wompiFetch(
  target: TokenizerTarget,
  path: string,
  init: { method: "GET" | "POST"; body?: unknown },
): Promise<Response> {
  try {
    return await fetch(`${target.apiBaseUrl}${path}`, {
      method: init.method,
      headers: {
        Authorization: `Bearer ${target.publicKey}`,
        ...(init.body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      // Sin cookies ni página de origen: a Wompi no le hace falta nada nuestro.
      credentials: "omit",
      referrerPolicy: "no-referrer",
      cache: "no-store",
    });
  } catch {
    // Red caída o CORS. El error original no se propaga: no hace falta y
    // podría terminar en el monitoreo.
    throw new TokenizeError(WOMPI_UNREACHABLE);
  }
}

/** `data` del cuerpo, o null. Se lee solo lo que se usa. */
async function dataOf(response: Response): Promise<Record<string, unknown> | null> {
  try {
    const body: unknown = await response.json();
    if (typeof body !== "object" || body === null) return null;
    const data = (body as { data?: unknown }).data;
    return typeof data === "object" && data !== null ? (data as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/**
 * Cifra la tarjeta con la llave de Wompi y pide su token. `encryptionKey` es el
 * PEM de `GET /billing/card-encryption-key`. Lanza `TokenizeError`.
 */
export async function tokenizeCard(
  target: TokenizerTarget,
  encryptionKey: string,
  card: CardInput,
): Promise<TokenizedSource> {
  // WebCrypto, con la que `jose` cifra, solo existe en un contexto seguro
  // (https o `localhost`). En producción siempre lo es.
  if (!globalThis.crypto?.subtle) {
    throw new TokenizeError(
      "Tu navegador no pudo cifrar la tarjeta en esta página. Actualízalo o prueba con otro.",
    );
  }
  let payload: string;
  try {
    const key = await importSPKI(encryptionKey, "RSA-OAEP-256");
    payload = await new EncryptJWT({
      number: onlyDigits(card.number),
      cvc: card.cvc,
      exp_month: card.expMonth,
      exp_year: card.expYear,
      card_holder: card.holder.trim(),
    })
      .setProtectedHeader({ alg: "RSA-OAEP-256", enc: "A256GCM" })
      .encrypt(key);
  } catch {
    throw new TokenizeError(WOMPI_UNREACHABLE);
  }

  const response = await wompiFetch(target, "/tokens/cards", {
    method: "POST",
    body: { payload },
  });
  if (response.status >= 400 && response.status < 500) throw new TokenizeError(CARD_REJECTED);
  const data = response.ok ? await dataOf(response) : null;
  const token = data?.id;
  if (typeof token !== "string" || !token) throw new TokenizeError(WOMPI_UNREACHABLE);
  return { token, type: "CARD" };
}

export type NequiStatus = "pending" | "approved" | "rejected";

function nequiStatusOf(data: Record<string, unknown> | null): NequiStatus | null {
  const status = data?.status;
  if (status === "PENDING") return "pending";
  if (status === "APPROVED") return "approved";
  // DECLINED, ERROR o cualquier otro estado final.
  return typeof status === "string" ? "rejected" : null;
}

/**
 * Pide a Wompi que le envíe al cliente la solicitud de suscripción a su app
 * Nequi. Devuelve el token, todavía pendiente. Lanza `TokenizeError`.
 */
export async function startNequi(
  target: TokenizerTarget,
  phone: string,
): Promise<{ token: string; status: NequiStatus }> {
  const response = await wompiFetch(target, "/tokens/nequi", {
    method: "POST",
    body: { phone_number: phone },
  });
  if (response.status >= 400 && response.status < 500) throw new TokenizeError(NEQUI_REJECTED);
  const data = response.ok ? await dataOf(response) : null;
  const token = data?.id;
  const status = nequiStatusOf(data);
  if (typeof token !== "string" || !token || status === null) {
    throw new TokenizeError(WOMPI_UNREACHABLE);
  }
  return { token, status };
}

/** Cómo va la aprobación en la app de Nequi. Lanza `TokenizeError`. */
export async function nequiStatus(target: TokenizerTarget, token: string): Promise<NequiStatus> {
  const response = await wompiFetch(target, `/tokens/nequi/${encodeURIComponent(token)}`, {
    method: "GET",
  });
  const status = response.ok ? nequiStatusOf(await dataOf(response)) : null;
  if (status === null) throw new TokenizeError(WOMPI_UNREACHABLE);
  return status;
}
