/** Textos y formato compartidos por las páginas de administración. */

import type { AuditLogEntry } from "./types/admin";
import type { AccessReason, AccessType } from "./types/auth";
import type { GameIcon, GameModule, GameStatus } from "./types/games";

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
  game_not_in_plan: "Juego fuera del plan",
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
  "payment.requery": "Reconsultó un pago en la pasarela",
  "payment.refund.record": "Registró un reembolso",
  "user.password.force_reset": "Forzó el restablecimiento de la contraseña",
  "user.verification.resend": "Reenvió el correo de confirmación",
  "plan.price.transfer": "Trasladó el precio a las suscripciones vigentes",
  "plan.price.transfer.cancel": "Canceló un traslado de precio",
  "plan.games.update": "Cambió los juegos del plan",
  "game.create": "Creó un juego",
  "game.status.update": "Cambió el estado de un juego",
};

export function actionLabel(entry: AuditLogEntry): string {
  return ACTION_LABEL[entry.action] ?? entry.action;
}

/**
 * La pasarela de un pago o una suscripción (`provider`). Wompi salió del
 * proyecto el 2026-10-22 sin cobrar dinero real: sus filas son del sandbox
 * (paso 5.1 de la Fase 5).
 */
const PROVIDER_LABEL: Record<string, string> = {
  wompi: "Wompi (sandbox)",
  fake: "Pasarela simulada",
};

export function providerLabel(provider: string): string {
  return PROVIDER_LABEL[provider] ?? provider;
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

/** Estado de un juego (§7.2), como lo lee el admin. */
export const GAME_STATUS_LABEL: Record<GameStatus, string> = {
  active: "Activo",
  coming_soon: "Próximamente",
  hidden: "Oculto",
};

export const GAME_MODULE_LABEL: Record<GameModule, string> = {
  discrete_outcome: "Resultados discretos",
  sports: "Deportes (reservado)",
};

export const GAME_ICON_LABEL: Record<GameIcon, string> = {
  ruleta: "Ruleta",
  dados: "Dados",
  cartas: "Cartas",
  deportes: "Deportes",
  generico: "Genérico",
};
