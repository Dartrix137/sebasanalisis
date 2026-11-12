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
 * - Imágenes: las propias y los logos de los medios de pago, que Tipster Page
 *   sirve desde su CDN (`logoUrl` del catálogo, manual V2 §5).
 * - Conexiones: la API y el monitoreo (GlitchTip). Tipster Page no tokeniza
 *   desde el navegador: el navegador no le habla a su API.
 * - Formularios: solo a este sitio. El envío al procesador de pagos (Redsys,
 *   EBANX) sale de la página de pago que sirve la API, con su propia CSP
 *   (`backend/app/core/checkout_pages.py`); al frontend no le hace falta.
 * - Marcos: el widget de Turnstile y los videos de las guías, que se incrustan
 *   desde `www.youtube-nocookie.com` (modo de privacidad mejorada de YouTube,
 *   decidido el 2026-11-12). El PDF de las guías es un enlace a Cloudinary: una
 *   navegación, que no pide directiva. Nadie puede meter el sitio en un marco.
 */

const TURNSTILE_ORIGIN = "https://challenges.cloudflare.com";
/** Los videos de las guías (`components/guides/GuideVideo.tsx`). */
export const YOUTUBE_EMBED_ORIGIN = "https://www.youtube-nocookie.com";
/** El CDN de los logos de los medios de pago de Tipster Page. */
const PAYMENT_LOGOS_ORIGIN = "https://cdntpfiles86236.tipsterpage.com";

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
  const connect = ["'self'", api, monitoring].filter(Boolean);
  const directives = [
    "default-src 'self'",
    // En desarrollo React usa eval para reconstruir los errores del servidor.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' blob: data: ${PAYMENT_LOGOS_ORIGIN}`,
    "font-src 'self'",
    `connect-src ${connect.join(" ")}`,
    `frame-src ${TURNSTILE_ORIGIN} ${YOUTUBE_EMBED_ORIGIN}`,
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
