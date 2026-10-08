/**
 * Tipos de `backend/app/schemas/admin.py`, reexportados desde los generados.
 *
 * No se escriben a mano: salen de `lib/api/schema.d.ts` (`npm run gen:types`,
 * skill `api-schema-sync`).
 */

import type { components } from "../api/schema";

type S = components["schemas"];

export type AdminUserListResponse = S["AdminUserListResponse"];
export type AdminUserDetailResponse = S["AdminUserDetailResponse"];
export type UpdateUserAccessRequest = S["UpdateUserAccessRequest"];
export type UpdateUserStatusRequest = S["UpdateUserStatusRequest"];
export type AuditLogEntry = S["AuditLogEntry"];
export type AuditLogListResponse = S["AuditLogListResponse"];
