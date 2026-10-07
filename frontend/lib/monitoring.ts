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

// Campos de una miga (breadcrumb) que traen una URL: `url` en las de fetch y
// `to`/`from` en las de navegación.
const BREADCRUMB_URL_FIELDS = ["url", "to", "from"];

/**
 * Una URL sin sus parámetros ni su fragmento. Los enlaces de los correos traen
 * el token de un solo uso en la URL (`/verificar-correo?token=…`,
 * `/restablecer-contrasena?token=…`): un error en esas páginas lo enviaría tal
 * cual. Se quitan en todas las URL, no solo en esas dos rutas, para que una
 * página nueva con un token en la URL no dependa de acordarse de este archivo.
 */
export function stripQuery(url: string): string {
  return url.split(/[?#]/, 1)[0];
}

/**
 * `beforeSend`: quita lo que no debe salir de la aplicación. Ni cabeceras de
 * autenticación, ni cuerpos de petición, ni cookies, ni los parámetros de
 * ninguna URL llegan al monitoreo.
 */
export function scrubEvent(event: ErrorEvent): ErrorEvent {
  for (const breadcrumb of event.breadcrumbs ?? []) {
    const data = breadcrumb.data;
    if (!data) continue;
    for (const field of BREADCRUMB_URL_FIELDS) {
      const value: unknown = data[field];
      if (typeof value === "string") data[field] = stripQuery(value);
    }
  }

  const request = event.request;
  if (!request) return event;

  if (request.url) request.url = stripQuery(request.url);
  delete request.query_string;

  if (request.headers) {
    request.headers = Object.fromEntries(
      Object.entries(request.headers).map(([name, value]) => {
        const lower = name.toLowerCase();
        if (SENSITIVE_HEADERS.has(lower)) return [name, FILTERED];
        // La página anterior, con sus parámetros.
        return [name, lower === "referer" ? stripQuery(value) : value];
      }),
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
