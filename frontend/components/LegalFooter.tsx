/**
 * Pie de página con los documentos legales. Va en el layout raíz: aparece en
 * todas las pantallas, incluidas login y registro (§6.6 de la Fase 4).
 */

import Link from "next/link";

import { LEGAL_DOCUMENTS } from "@/lib/legal";

export function LegalFooter() {
  return (
    <footer className="border-t border-edge px-4 py-5">
      <nav
        aria-label="Documentos legales"
        className="mx-auto flex max-w-5xl flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-muted"
      >
        {LEGAL_DOCUMENTS.map((doc) => (
          <Link key={doc.kind} href={`/legal/${doc.slug}`} className="hover:text-gold">
            {doc.label}
          </Link>
        ))}
      </nav>
    </footer>
  );
}
