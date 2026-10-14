/** Textos y formato compartidos por las páginas de administración. */

import type { AuditLogEntry } from "./types/admin";
import type { AccessReason, AccessType } from "./types/auth";

/** El motivo de la decisión de acceso (`core/access.py`), como lo lee el admin. */
export const ACCESS_REASON_LABEL: Record<AccessReason, string> = {
  admin: "Administrador",
  full: "Acceso completo",
  invited: "Invitado",
  subscription: "Suscripción",
  suspended: "Suspendida",
  consent_required: "Falta aceptar documentos",
  expired: "Acceso vencido",
  no_access: "Sin acceso",
};

export const ACCESS_TYPE_LABEL: Record<AccessType, string> = {
  none: "Sin acceso manual",
  invited: "Invitado",
  full: "Completo, sin vencimiento",
};

const ACTION_LABEL: Record<string, string> = {
  "user.access.update": "Cambió el acceso",
  "user.status.update": "Suspendió o reactivó la cuenta",
  "user.role.update": "Cambió el rol",
  "legal_document.publish": "Publicó un documento legal",
  "plan.create": "Creó un plan",
  "plan.update": "Editó un plan",
  "coupon.create": "Creó un cupón",
  "coupon.update": "Editó un cupón",
  "subscription.extend": "Extendió la suscripción",
  "subscription.cancel_at_period_end": "Canceló la renovación al final del período",
  "subscription.cancel_now": "Canceló la suscripción de inmediato",
  "payment.requery": "Reconsultó un pago en Wompi",
  "payment.refund.record": "Registró un reembolso",
  "user.password.force_reset": "Forzó el restablecimiento de la contraseña",
  "user.verification.resend": "Reenvió el correo de confirmación",
};

export function actionLabel(entry: AuditLogEntry): string {
  return ACTION_LABEL[entry.action] ?? entry.action;
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("es-CO", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** `{a: 1, b: null}` → `a: 1 · b: —`, para leer un antes/después de un vistazo. */
export function describeChange(value: AuditLogEntry["before"]): string {
  if (!value) return "—";
  return Object.entries(value)
    .map(([k, v]) => `${k}: ${v === null ? "—" : String(v)}`)
    .join(" · ");
}
