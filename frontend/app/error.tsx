"use client";

import * as Sentry from "@sentry/nextjs";
import Link from "next/link";
import { useEffect } from "react";

import { BrandMark, Button } from "@/components/ui";

/**
 * Un error de render en cualquier pantalla. Queda dentro del layout raíz (con
 * el pie), lo reporta al monitoreo y deja reintentar. Es uno solo para toda la
 * aplicación: ninguna pantalla necesita un mensaje distinto. Si falla el propio
 * layout, responde `global-error.tsx`.
 */
export default function Error({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <main className="flex flex-1 flex-col items-center justify-center px-4 py-12 text-center">
      <BrandMark size={64} />
      <h1 className="mt-6 font-display text-3xl font-semibold leading-tight tracking-tight">
        Algo salió mal
      </h1>
      <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted">
        La página tuvo un error inesperado. Tus números y tu banca están guardados: vuelve a
        intentarlo.
      </p>
      <div className="mt-7 flex flex-wrap justify-center gap-2">
        <Button onClick={() => retry()}>Reintentar</Button>
        <Link
          href="/"
          className="inline-flex rounded-lg border border-edge bg-ink-sunken px-4 py-2.5 text-sm font-bold text-white hover:border-gold/50"
        >
          Ir al inicio
        </Link>
      </div>
    </main>
  );
}
