/**
 * Tipos de `backend/app/schemas/legal.py`, reexportados desde los generados.
 *
 * No se escriben a mano: salen de `lib/api/schema.d.ts` (`npm run gen:types`,
 * skill `api-schema-sync`).
 */

import type { components } from "../api/schema";

type S = components["schemas"];

export type LegalKind = S["LegalKind"];
export type LegalDocumentResponse = S["LegalDocumentResponse"];
export type PendingConsentResponse = S["PendingConsentResponse"];
export type AcceptLegalRequest = S["AcceptLegalRequest"];
export type ConsentResponse = S["ConsentResponse"];
export type AdminLegalDocumentResponse = S["AdminLegalDocumentResponse"];
export type CreateLegalDocumentRequest = S["CreateLegalDocumentRequest"];
export type UpdateLegalDocumentRequest = S["UpdateLegalDocumentRequest"];
