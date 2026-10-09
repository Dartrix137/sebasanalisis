/**
 * Tipos de `backend/app/schemas/billing.py`, reexportados desde los generados.
 *
 * No se escriben a mano: salen de `lib/api/schema.d.ts` (`npm run gen:types`,
 * skill `api-schema-sync`).
 */

import type { components } from "../api/schema";

type S = components["schemas"];

export type PlanResponse = S["PlanResponse"];
export type PlanInterval = S["PlanInterval"];
export type QuoteRequest = S["QuoteRequest"];
export type QuoteResponse = S["QuoteResponse"];
export type AdminPlanResponse = S["AdminPlanResponse"];
export type AdminPlanListResponse = S["AdminPlanListResponse"];
export type CreatePlanRequest = S["CreatePlanRequest"];
export type UpdatePlanRequest = S["UpdatePlanRequest"];
export type CouponKind = S["CouponKind"];
export type CouponDuration = S["CouponDuration"];
export type AdminCouponResponse = S["AdminCouponResponse"];
export type AdminCouponListResponse = S["AdminCouponListResponse"];
export type CreateCouponRequest = S["CreateCouponRequest"];
export type UpdateCouponRequest = S["UpdateCouponRequest"];
export type CouponRedemptionListResponse = S["CouponRedemptionListResponse"];
