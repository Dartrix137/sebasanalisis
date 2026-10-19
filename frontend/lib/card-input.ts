/**
 * Formato y validación de lo que se escribe en el formulario de tarjeta y de
 * Nequi (`PaymentSourceForm`, §3.16 de la Fase 4). Funciones puras: no llaman a
 * nadie ni guardan nada.
 *
 * Los campos se formatean mientras se escribe (solo dígitos, el número en
 * grupos, el vencimiento como MM/AA) y se validan antes de que nada salga del
 * navegador. Lo que Wompi espera (`exp_month` y `exp_year` de dos dígitos, CVC
 * de 3 o 4) está en "Tokeniza una tarjeta", citado en `lib/tokenize.ts`.
 */

export function onlyDigits(value: string): string {
  return value.replace(/\D/g, "");
}

// ---------- Número ----------

export type CardBrand = "visa" | "mastercard" | "amex" | "diners";

export const BRAND_LABEL: Record<CardBrand, string> = {
  visa: "Visa",
  mastercard: "Mastercard",
  amex: "American Express",
  diners: "Diners Club",
};

/** Cuántos dígitos puede tener el número de cada marca. */
const BRAND_LENGTHS: Record<CardBrand, number[]> = {
  visa: [13, 16, 19],
  mastercard: [16],
  amex: [15],
  diners: [14, 15, 16, 17, 18, 19],
};

/** La marca por los primeros dígitos, o null si no se reconoce (se acepta igual). */
export function cardBrand(number: string): CardBrand | null {
  const d = onlyDigits(number);
  if (/^4/.test(d)) return "visa";
  if (/^3[47]/.test(d)) return "amex";
  if (/^3(0[0-5]|[689])/.test(d)) return "diners";
  if (/^5[1-5]/.test(d) || /^2(2[2-9]|[3-6]\d|7[01]|720)/.test(d)) return "mastercard";
  return null;
}

function maxDigits(brand: CardBrand | null): number {
  return brand ? Math.max(...BRAND_LENGTHS[brand]) : 19;
}

/** Solo dígitos, hasta el largo de la marca, en grupos: 4-4-4-4, o 4-6-5 en American Express. */
export function formatCardNumber(value: string): string {
  const brand = cardBrand(value);
  const digits = onlyDigits(value).slice(0, maxDigits(brand));
  const groups =
    brand === "amex"
      ? [digits.slice(0, 4), digits.slice(4, 10), digits.slice(10)]
      : digits.match(/.{1,4}/g) ?? [];
  return groups.filter(Boolean).join(" ");
}

/** Algoritmo de Luhn. */
export function luhnValid(digits: string): boolean {
  let sum = 0;
  for (let i = 0; i < digits.length; i++) {
    let d = Number(digits[digits.length - 1 - i]);
    if (i % 2 === 1) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
  }
  return digits.length > 0 && sum % 10 === 0;
}

/** El largo que corresponde a su marca (13 a 19 si no se reconoce) y Luhn. */
export function cardNumberValid(value: string): boolean {
  const digits = onlyDigits(value);
  const brand = cardBrand(digits);
  const lengthOk = brand
    ? BRAND_LENGTHS[brand].includes(digits.length)
    : digits.length >= 13 && digits.length <= 19;
  return lengthOk && luhnValid(digits);
}

// ---------- Vencimiento ----------

/**
 * El vencimiento como MM/AA mientras se escribe. Un primer dígito mayor que 1
 * ya es el mes (4 → 04); un mes 00 o mayor que 12 no se deja escribir. Acepta
 * lo que llena el autocompletado del navegador: 08/2030, 0830 u 082030.
 */
export function formatExpiry(value: string): string {
  let month: string;
  let year: string;
  const [left, right] = value.split("/", 2);
  if (right !== undefined) {
    month = onlyDigits(left).slice(-2);
    year = onlyDigits(right);
    if (month.length === 1) month = `0${month}`;
  } else {
    const digits = onlyDigits(value);
    // MMAAAA, del autocompletado.
    const full = digits.length === 6 ? `${digits.slice(0, 2)}${digits.slice(4)}` : digits;
    month = full.slice(0, 2);
    year = full.slice(2);
  }
  if (year.length === 4) year = year.slice(2);
  year = year.slice(0, 2);

  if (right === undefined && month.length >= 1 && Number(month[0]) > 1) {
    year = `${month.slice(1)}${year}`.slice(0, 2);
    month = `0${month[0]}`;
  }
  if (month.length === 2 && (month === "00" || Number(month) > 12)) {
    // El segundo dígito no forma un mes: se descarta, con lo que venía después.
    return month[0];
  }
  return year ? `${month}/${year}` : month;
}

/** Mes y año de dos dígitos cada uno, como los pide Wompi. */
export function parseExpiry(value: string): { expMonth: string; expYear: string } {
  const [month = "", year = ""] = value.split("/", 2);
  return { expMonth: onlyDigits(month), expYear: onlyDigits(year) };
}

/** Mes válido y sin vencer: la tarjeta vale hasta el último día de su mes. */
export function expiryValid(expMonth: string, expYear: string, now: Date = new Date()): boolean {
  if (!/^\d{2}$/.test(expMonth) || !/^\d{2}$/.test(expYear)) return false;
  const month = Number(expMonth);
  if (month < 1 || month > 12) return false;
  const year = 2000 + Number(expYear);
  const current = now.getFullYear() * 12 + now.getMonth();
  return year * 12 + (month - 1) >= current;
}

// ---------- CVC y titular ----------

/** Cuántos dígitos lleva el CVC: 4 en American Express, 3 en las demás; 3 o 4 si no se sabe. */
export function cvcLengths(brand: CardBrand | null): number[] {
  if (brand === "amex") return [4];
  return brand ? [3] : [3, 4];
}

export function formatCvc(value: string, brand: CardBrand | null): string {
  return onlyDigits(value).slice(0, Math.max(...cvcLengths(brand)));
}

export function cvcValid(cvc: string, brand: CardBrand | null = null): boolean {
  return /^\d+$/.test(cvc) && cvcLengths(brand).includes(cvc.length);
}

/** Letras (con tildes), espacios, apóstrofos, puntos y guiones. */
export function formatHolder(value: string): string {
  return value.replace(/[^\p{L}\s'.-]/gu, "").replace(/\s{2,}/g, " ").slice(0, 100);
}

// ---------- El formulario completo ----------

/** Lo que muestra el formulario. */
export interface CardForm {
  number: string;
  /** MM/AA */
  expiry: string;
  cvc: string;
  holder: string;
}

export type CardField = keyof CardForm;

/** El problema de cada campo, en palabras para el cliente. Sin claves si todo está bien. */
export function cardFieldErrors(
  form: CardForm,
  now: Date = new Date(),
): Partial<Record<CardField, string>> {
  const errors: Partial<Record<CardField, string>> = {};
  const brand = cardBrand(form.number);
  if (!onlyDigits(form.number)) errors.number = "Escribe el número de la tarjeta.";
  else if (!cardNumberValid(form.number)) errors.number = "El número de la tarjeta no es válido.";

  const { expMonth, expYear } = parseExpiry(form.expiry);
  if (!form.expiry) errors.expiry = "Escribe el mes y el año de vencimiento.";
  else if (expMonth.length !== 2 || expYear.length !== 2) {
    errors.expiry = "Escribe el vencimiento como MM/AA.";
  } else if (!expiryValid(expMonth, expYear, now)) errors.expiry = "Esta tarjeta ya venció.";

  if (!cvcValid(form.cvc, brand)) {
    const lengths = cvcLengths(brand);
    errors.cvc = `El código de seguridad tiene ${lengths.join(" o ")} dígitos.`;
  }
  if (form.holder.trim().length < 2) {
    errors.holder = "Escribe el nombre del titular como aparece en la tarjeta.";
  }
  return errors;
}

// ---------- Nequi ----------

/** Celular colombiano: diez dígitos que empiezan por 3. */
export function nequiPhoneValid(phone: string): boolean {
  return /^3\d{9}$/.test(phone);
}

/** Solo dígitos, en grupos 3-3-4 como se escribe un celular: 399 111 1111. */
export function formatPhone(value: string): string {
  const digits = onlyDigits(value).slice(0, 10);
  return [digits.slice(0, 3), digits.slice(3, 6), digits.slice(6)].filter(Boolean).join(" ");
}
