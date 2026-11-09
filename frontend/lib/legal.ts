/**
 * Los documentos legales y sus rutas públicas (§6.1 de la Fase 4).
 *
 * La URL va en español y la API usa el `kind` en inglés: este archivo es el
 * único lugar que conoce las dos.
 */

import type { LegalKind } from "./types/legal";

export interface LegalDocumentInfo {
  kind: LegalKind;
  slug: string;
  /** Nombre corto, para el pie de página y el panel de administración. */
  label: string;
}

export const LEGAL_DOCUMENTS: LegalDocumentInfo[] = [
  { kind: "terms", slug: "terminos", label: "Términos y Condiciones" },
  { kind: "privacy", slug: "privacidad", label: "Tratamiento de datos" },
  { kind: "cookies", slug: "cookies", label: "Cookies" },
];

/**
 * Documentos retirados (paso 5.5 de la Fase 5): su contenido pasó a los
 * Términos y Condiciones. Su dirección lleva a los términos, y una aceptación
 * vieja de uno de ellos también enlaza ahí.
 */
export const RETIRED_SLUGS: Record<string, LegalKind> = { reembolsos: "refunds" };

export function legalPath(kind: LegalKind): string {
  const info = LEGAL_DOCUMENTS.find((d) => d.kind === kind);
  return `/legal/${info?.slug ?? "terminos"}`;
}

export function kindFromSlug(slug: string): LegalKind | null {
  return LEGAL_DOCUMENTS.find((d) => d.slug === slug)?.kind ?? null;
}

export function formatLegalDate(iso: string): string {
  return new Date(iso).toLocaleDateString("es-CO", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/**
 * La declaración del riesgo de pérdida (paso 5.5 de la Fase 5): obligatoria al
 * registrarse, junto con la mayoría de edad. Es la frase de la cláusula 84 de
 * los Términos y Condiciones.
 */
export const LOSS_RISK_TEXT = "Entiendo que las apuestas implican riesgo de pérdida de dinero.";
