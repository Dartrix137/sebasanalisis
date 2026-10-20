import type { Metadata } from "next";
import Link from "next/link";

import { BrandMark } from "@/components/ui";

export const metadata: Metadata = { title: "Página no encontrada" };

/**
 * La 404 de toda la aplicación: una ruta que no existe y cualquier `notFound()`
 * (por ejemplo, un documento legal que no existe). Se dibuja dentro del layout
 * raíz, así que conserva el pie con los documentos legales.
 *
 * El enlace va a `/`, que lleva a la mesa si hay sesión y al ingreso si no.
 */
export default function NotFound() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center px-4 py-12 text-center">
      <Link href="/" aria-label="Sebasanálisis, ir al inicio">
        <BrandMark size={64} />
      </Link>
      <p className="mt-6 font-display text-6xl font-semibold leading-none text-gold">404</p>
      <h1 className="mt-3 font-display text-3xl font-semibold leading-tight tracking-tight">
        No encontramos esta página
      </h1>
      <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted">
        La dirección no existe o cambió. Tus mesas y tus números siguen guardados en tu cuenta.
      </p>
      <Link
        href="/"
        className="mt-7 inline-flex rounded-lg bg-gold px-4 py-2.5 text-sm font-bold text-gold-ink hover:bg-gold-soft"
      >
        Ir al inicio
      </Link>
    </main>
  );
}
