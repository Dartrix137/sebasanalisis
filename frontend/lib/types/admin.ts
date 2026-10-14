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
export type UpdateUserRoleRequest = S["UpdateUserRoleRequest"];
export type AuditLogEntry = S["AuditLogEntry"];
export type SubscriptionFilter = S["SubscriptionFilter"];
export type AuditLogListResponse = S["AuditLogListResponse"];
export type AdminSubscriptionResponse = S["AdminSubscriptionResponse"];
export type AdminSubscriptionListResponse = S["AdminSubscriptionListResponse"];
export type AdminSubscriptionDetailResponse = S["AdminSubscriptionDetailResponse"];
export type SubscriptionAdminAction = S["SubscriptionAdminAction"];
export type UpdateSubscriptionRequest = S["UpdateSubscriptionRequest"];
export type PaymentEventResponse = S["PaymentEventResponse"];
export type PaymentRefundResponse = S["PaymentRefundResponse"];
export type AdminPaymentListResponse = S["AdminPaymentListResponse"];
export type AdminPaymentDetailResponse = S["AdminPaymentDetailResponse"];
export type RequeryPaymentRequest = S["RequeryPaymentRequest"];
export type RecordRefundRequest = S["RecordRefundRequest"];
export type ForcePasswordResetRequest = S["ForcePasswordResetRequest"];
export type AdminOverviewResponse = S["AdminOverviewResponse"];
export type Comparison = S["Comparison"];
export type MoneyComparison = S["MoneyComparison"];
