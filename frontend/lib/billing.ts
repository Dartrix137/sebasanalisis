/**
 * Textos compartidos de suscripción y pagos, para `/cuenta` y para el admin.
 * Aquí no se decide nada: los estados vienen del servidor.
 */

import type { PaymentStatus, SubscriptionResponse } from "./types/billing";

/** El estado de un pago, como lo lee quien pagó. */
export const PAYMENT_STATUS_LABEL: Record<PaymentStatus, string> = {
  pending: "Sin completar",
  approved: "Aprobado",
  declined: "Rechazado",
  voided: "Anulado",
  error: "Con error",
};

/** El tono del distintivo de cada estado (`Badge` de `components/ui`). */
export const PAYMENT_STATUS_TONE: Record<PaymentStatus, "neutral" | "ok" | "off"> = {
  pending: "neutral",
  approved: "ok",
  declined: "off",
  voided: "off",
  error: "off",
};

/** Cómo se paga cada período. */
export const RENEWAL_MODE_LABEL: Record<SubscriptionResponse["renewal_mode"], string> = {
  manual: "Pago manual: no se renueva solo",
  automatic: "Renovación automática",
};
