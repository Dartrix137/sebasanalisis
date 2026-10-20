import type { NextConfig } from "next";

/**
 * Cabeceras de seguridad de todas las respuestas (paso 9). La CSP no va aquí:
 * lleva un nonce por petición y la pone `proxy.ts`. HSTS sin subdominios ni
 * preload, igual que la API: un subdominio sin HTTPS quedaría inalcanzable.
 */
const SECURITY_HEADERS = [
  { key: "Strict-Transport-Security", value: "max-age=31536000" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Sin `X-Powered-By: Next.js`: no hace falta anunciar con qué está hecho.
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  // Empaqueta el servidor con solo las dependencias que realmente usa, en vez
  // de copiar node_modules completo a la imagen. Sin esto la imagen de
  // produccion pesa cientos de MB de mas.
  output: "standalone",
  // Solo afecta a `next dev`. Wompi rechaza una direccion de regreso con
  // `localhost` o `127.0.0.1`, asi que para probar pagos en local el frontend
  // se abre por `localtest.me`, un nombre publico que apunta a este equipo
  // (docs/DESPLIEGUE.md, "Pagos con Wompi"). Sin esto, Next bloquea sus
  // recursos de desarrollo desde ese nombre y la pagina queda en blanco.
  allowedDevOrigins: ["localtest.me"],
  // La mesa se mudó de `/games/roulette/<id>` a `/juegos/<slug>/mesa/<id>`
  // (§7.3 de la Fase 4). Todos los enlaces viejos son de ruleta, así que la
  // redirección no necesita consultar nada. Permanente (308).
  async redirects() {
    return [
      {
        source: "/games/roulette/:sessionId",
        destination: "/juegos/ruleta/mesa/:sessionId",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
