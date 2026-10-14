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
export type BillingAvailabilityResponse = S["BillingAvailabilityResponse"];
export type SubscribeRequest = S["SubscribeRequest"];
export type SubscribeResponse = S["SubscribeResponse"];
export type PaymentMethodRequest = S["PaymentMethodRequest"];
export type PaymentResponse = S["PaymentResponse"];
export type PaymentStatus = S["PaymentStatus"];
export type PaymentListResponse = S["PaymentListResponse"];
export type AdminPaymentResponse = S["AdminPaymentResponse"];
export type SubscriptionResponse = S["SubscriptionResponse"];
export type AcceptanceResponse = S["AcceptanceResponse"];
export type PaymentSourceKind = S["PaymentSourceKind"];
export type RenewalMode = S["RenewalMode"];
export type SubscriptionStatus = S["SubscriptionStatus"];
export type PaymentKind = S["PaymentKind"];
export type AdminPlanResponse = S["AdminPlanResponse"];
export type AdminPlanListResponse = S["AdminPlanListResponse"];
export type CreatePlanRequest = S["CreatePlanRequest"];
export type UpdatePlanRequest = S["UpdatePlanRequest"];
export type UpdatePlanGamesRequest = S["UpdatePlanGamesRequest"];
export type PlanGameRef = S["PlanGameRef"];
export type CouponKind = S["CouponKind"];
export type CouponDuration = S["CouponDuration"];
export type AdminCouponResponse = S["AdminCouponResponse"];
export type AdminCouponListResponse = S["AdminCouponListResponse"];
export type CreateCouponRequest = S["CreateCouponRequest"];
export type UpdateCouponRequest = S["UpdateCouponRequest"];
export type CouponRedemptionListResponse = S["CouponRedemptionListResponse"];
export type UpcomingPriceChange = S["UpcomingPriceChange"];
export type PriceChangeResponse = S["PriceChangeResponse"];
export type PriceChangeListResponse = S["PriceChangeListResponse"];
export type PriceTransferPreview = S["PriceTransferPreview"];
export type PriceTransferRequest = S["PriceTransferRequest"];
