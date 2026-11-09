/**
 * Pie de página con los documentos legales. Va en el layout raíz: aparece en
 * todas las pantallas, incluidas login y registro (§6.6 de la Fase 4).
 */

import Link from "next/link";

import { LEGAL_DOCUMENTS } from "@/lib/legal";

export function LegalFooter() {
  return (
    <footer className="border-t border-edge px-4 py-3">
      <nav
        aria-label="Documentos legales"
        className="mx-auto flex max-w-5xl flex-wrap items-center justify-center gap-x-2 text-xs text-muted"
      >
        {LEGAL_DOCUMENTS.map((doc) => (
          <Link
            key={doc.kind}
            href={`/legal/${doc.slug}`}
            className="inline-flex min-h-11 items-center px-1.5 hover:text-gold"
          >
            {doc.label}
          </Link>
        ))}
        {/* Ley 1480 de 2011: enlace visible a la autoridad de protección al
            consumidor en los medios de comercio electrónico. */}
        <a
          href="https://www.sic.gov.co"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-11 items-center px-1.5 hover:text-gold"
        >
          Superintendencia de Industria y Comercio
        </a>
      </nav>
    </footer>
  );
}
