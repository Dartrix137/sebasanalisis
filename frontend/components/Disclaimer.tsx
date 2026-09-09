/**
 * Banner fijo obligatorio. Debe aparecer en TODA pantalla que muestre
 * sugerencias estadisticas, rachas o resultados de chi-cuadrado
 * (`docs/ARQUITECTURA_Y_ESTADISTICA.md` §0). El texto es literal, no se edita.
 */
export const DISCLAIMER_TEXT =
  "La ruleta no tiene memoria. Cada giro es independiente. Este análisis es descriptivo, no predictivo.";

export function Disclaimer() {
  return (
    <p
      role="note"
      className="rounded-card border border-edge bg-ink-raised px-4 py-3 text-center text-xs text-muted"
    >
      {DISCLAIMER_TEXT}
    </p>
  );
}
