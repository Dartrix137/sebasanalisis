/**
 * Montos en centavos enteros, como los maneja la API. Aquí solo se les da
 * formato o se leen de un campo de texto; nunca se calcula un precio: eso es
 * del servidor (`backend/app/billing/pricing.py`).
 */

import type { PlanInterval } from "./types/billing";

/** `10000000, "COP"` → `100.000 COP`; `3050, "USD"` → `30,50 USD`. */
export function formatMoney(cents: number, currency: string): string {
  const units = Math.trunc(cents / 100);
  const rest = Math.abs(cents % 100);
  const whole = units.toLocaleString("es-CO");
  return `${rest ? `${whole},${String(rest).padStart(2, "0")}` : whole} ${currency}`;
}

/** Los centavos como se escriben en un campo: `10000000` → `100000`, `3050` → `30.50`. */
export function centsToInput(cents: number): string {
  const rest = cents % 100;
  const units = String(Math.trunc(cents / 100));
  return rest ? `${units}.${String(rest).padStart(2, "0")}` : units;
}

/**
 * Lee un monto escrito a mano y lo pasa a centavos, sin pasar por decimales
 * de coma flotante. Acepta `100000`, `100000.5` y `100000,50`. Devuelve null
 * si no es un monto positivo con dos decimales como mucho.
 */
export function parseMoneyToCents(text: string): number | null {
  const match = /^(\d{1,9})(?:[.,](\d{1,2}))?$/.exec(text.trim());
  if (!match) return null;
  const cents = Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  return cents > 0 ? cents : null;
}

/** Cada cuánto se cobra: `mes`, `año`, `3 meses`. */
export function intervalLabel(interval: PlanInterval, count: number): string {
  if (interval === "month") return count === 1 ? "mes" : `${count} meses`;
  return count === 1 ? "año" : `${count} años`;
}
