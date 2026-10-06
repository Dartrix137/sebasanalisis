"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

/**
 * Última barrera: un error de render que nadie atrapó. Lo reporta al monitoreo
 * y deja al usuario una salida, en vez de una pantalla en blanco.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="es">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          padding: "1.5rem",
          background: "#0b1220",
          color: "#ffffff",
          fontFamily: "system-ui, sans-serif",
          textAlign: "center",
        }}
      >
        <h1 style={{ fontSize: "1.5rem", margin: 0 }}>Algo salió mal</h1>
        <p style={{ margin: 0, maxWidth: "28rem", color: "#9aa7bd" }}>
          La página tuvo un error inesperado. Tus números y tu banca están guardados: vuelve a
          intentarlo.
        </p>
        <button
          type="button"
          onClick={reset}
          style={{
            border: 0,
            borderRadius: "0.5rem",
            padding: "0.65rem 1.25rem",
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          Reintentar
        </button>
      </body>
    </html>
  );
}
