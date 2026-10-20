/**
 * La Content Security Policy del sitio (paso 9, decidida el 2026-10-20: con
 * nonce). La arma `proxy.ts` en cada petición con un nonce nuevo.
 *
 * Forma tomada de la guía de Next 16.3 (`node_modules/next/dist/docs/01-app/
 * 02-guides/content-security-policy.md`):
 *
 * - Scripts: solo los que llevan el nonce de esta respuesta (los de Next y los
 *   nuestros) y los que esos insertan (`strict-dynamic`), como el de Turnstile.
 *   Un script inyectado en la página no corre, y con él no se lee el token de la
 *   sesión de `localStorage` ni lo que se escribe en el formulario de tarjeta.
 * - Estilos: `unsafe-inline`. React y `next/image` escriben atributos `style`,
 *   que un nonce no cubre; inyectar estilos es mucho menos grave que inyectar
 *   scripts.
 * - Conexiones: la API, Wompi (el formulario de tarjeta tokeniza directo contra
 *   su API, §3.16) y el monitoreo (GlitchTip).
 * - Marcos: solo el widget de Turnstile. Nadie puede meter el sitio en un marco.
 */

/** Las dos API de Wompi: cuál se usa lo dice el backend (`/billing/availability`). */
const WOMPI_ORIGINS = ["https://production.wompi.co", "https://sandbox.wompi.co"];
const TURNSTILE_ORIGIN = "https://challenges.cloudflare.com";

function originOf(url: string | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

export function buildCsp({
  nonce,
  apiBaseUrl,
  sentryDsn,
  isDev,
}: {
  nonce: string;
  apiBaseUrl: string | undefined;
  sentryDsn: string | undefined;
  isDev: boolean;
}): string {
  const api = originOf(apiBaseUrl);
  const monitoring = originOf(sentryDsn);
  const connect = ["'self'", api, ...WOMPI_ORIGINS, monitoring].filter(Boolean);
  const directives = [
    "default-src 'self'",
    // En desarrollo React usa eval para reconstruir los errores del servidor.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    `connect-src ${connect.join(" ")}`,
    `frame-src ${TURNSTILE_ORIGIN}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  // Solo con la API en https: en local y en los tests la API va por http y el
  // navegador la subiría a https, que ahí no existe.
  if (api?.startsWith("https://")) directives.push("upgrade-insecure-requests");
  return directives.join("; ");
}
