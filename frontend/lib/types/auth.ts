/**
 * Tipos de `backend/app/schemas/auth.py`, reexportados desde los generados.
 *
 * No se escriben a mano: salen de `lib/api/schema.d.ts`, que genera
 * `npm run gen:types` desde el OpenAPI de la API. Si cambia un schema Pydantic,
 * se regenera y se commitea en el mismo commit (skill `api-schema-sync`).
 * Aquí solo se les da el nombre que usan los componentes.
 */

import type { components } from "../api/schema";

type S = components["schemas"];

/** Los ids viajan como texto; el OpenAPI no les da un tipo propio. */
export type UUID = string;

export type AccessType = S["AccessType"];
export type AccessReason = S["AccessReason"];
export type AccessInfo = S["AccessInfo"];
export type UserRole = S["UserRole"];
export type RegisterRequest = S["RegisterRequest"];
export type LoginRequest = S["LoginRequest"];
export type RefreshRequest = S["RefreshRequest"];
export type UserResponse = S["UserResponse"];
export type TokenResponse = S["TokenResponse"];
export type MessageResponse = S["MessageResponse"];
export type TokenRequest = S["TokenRequest"];
export type ForgotPasswordRequest = S["ForgotPasswordRequest"];
export type ResetPasswordRequest = S["ResetPasswordRequest"];
export type ChangePasswordRequest = S["ChangePasswordRequest"];
export type UpdateProfileRequest = S["UpdateProfileRequest"];
export type ChangeEmailRequest = S["ChangeEmailRequest"];
export type DeleteAccountRequest = S["DeleteAccountRequest"];
export type ExportResponse = S["ExportResponse"];
