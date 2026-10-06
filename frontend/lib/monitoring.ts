/**
 * Monitoreo de errores del frontend (docs/PLATAFORMA_COMPLETA.md §13.6).
 *
 * `@sentry/nextjs` apunta a GlitchTip, que habla el mismo protocolo y corre en
 * el VPS: no se envía nada a un tercero. Sin `NEXT_PUBLIC_SENTRY_DSN` queda
 * desactivado (desarrollo, tests y CI). Como todo `NEXT_PUBLIC_*`, el DSN se
 * incrusta durante el build: va como build argument, no como variable de entorno.
 */

import type { ErrorEvent } from "@sentry/nextjs";

const DSN = process.env.NEXT_PUBLIC_SENTRY_DSN ?? "";

const SENSITIVE_HEADERS = new Set(["authorization", "cookie", "set-cookie", "x-api-key"]);
const FILTERED = "[filtrado]";

/**
 * `beforeSend`: quita lo que no debe salir de la aplicación. Ni cabeceras de
 * autenticación, ni cuerpos de petición, ni cookies llegan al monitoreo.
 */
export function scrubEvent(event: ErrorEvent): ErrorEvent {
  const request = event.request;
  if (!request) return event;

  if (request.headers) {
    request.headers = Object.fromEntries(
      Object.entries(request.headers).map(([name, value]) => [
        name,
        SENSITIVE_HEADERS.has(name.toLowerCase()) ? FILTERED : value,
      ]),
    );
  }
  delete request.cookies;
  // El frontend solo envía cuerpos a la API: credenciales, apuestas, pagos.
  if (request.data !== undefined) request.data = FILTERED;

  return event;
}

/** Opciones comunes al navegador y al servidor de Next. */
export const monitoringOptions = {
  dsn: DSN,
  enabled: DSN !== "",
  sendDefaultPii: false,
  beforeSend: scrubEvent,
  // Solo errores: sin trazas de rendimiento ni grabación de sesiones.
  tracesSampleRate: 0,
};
