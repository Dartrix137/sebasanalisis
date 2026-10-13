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

/** El medio de pago guardado, como se le nombra al cliente. Nunca el número completo. */
export function sourceLabel(subscription: SubscriptionResponse): string | null {
  if (subscription.payment_source_type === "NEQUI") return "Nequi";
  if (subscription.payment_source_type === "CARD") {
    const brand = subscription.card_brand
      ? subscription.card_brand.charAt(0) + subscription.card_brand.slice(1).toLowerCase()
      : "Tarjeta";
    return subscription.card_last4 ? `${brand} •••• ${subscription.card_last4}` : brand;
  }
  return null;
}

/** Cómo se paga cada período. */
export const RENEWAL_MODE_LABEL: Record<SubscriptionResponse["renewal_mode"], string> = {
  manual: "Pago manual: no se renueva solo",
  automatic: "Renovación automática",
};
