import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { buildCsp } from "@/lib/csp";

/**
 * Pone la Content Security Policy con un nonce nuevo en cada página
 * (`lib/csp.ts`). Next lee el nonce de la cabecera de la petición y se lo pone
 * a sus propios scripts; por eso el layout raíz renderiza al pedir la página
 * (`connection()`), y no en el build.
 */
export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = buildCsp({
    nonce,
    apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL,
    sentryDsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    isDev: process.env.NODE_ENV === "development",
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      // Todo menos los archivos estáticos, que no ejecutan nada, y las
      // precargas de `next/link`, que no son la página que se muestra.
      source: "/((?!_next/static|_next/image|favicon.ico|icon.png|apple-icon.png|robots.txt|sitemap.xml).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
