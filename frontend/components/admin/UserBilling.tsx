"use client";

/**
 * Suscripción y pagos de una cuenta, en el detalle de `/admin/usuarios` (§4.2 de
 * la Fase 4). Es un resumen: las acciones sobre la suscripción (§4.3: extender,
 * cancelar al final del período y cancelar de inmediato) y su bitácora viven
 * solo en `/admin/suscripciones`, a donde lleva el enlace (decidido el
 * 2026-10-15, para no tener las mismas acciones en dos sitios). Los eventos de
 * la pasarela, reconsultar un pago y registrar un reembolso están en `/admin/pagos`.
 */

import Link from "next/link";

import { Badge } from "@/components/ui";
import { formatDateTime } from "@/lib/admin";
import {
  PAYMENT_STATUS_LABEL,
  PAYMENT_STATUS_TONE,
  RENEWAL_MODE_LABEL,
  SUBSCRIPTION_STATUS_LABEL,
} from "@/lib/billing";
import { formatLegalDate } from "@/lib/legal";
import { formatMoney, intervalLabel } from "@/lib/money";
import type { AdminUserDetailResponse } from "@/lib/types/admin";

export function UserBilling({ detail }: { detail: AdminUserDetailResponse }) {
  const { subscription, payments } = detail;

  return (
    <section data-testid="suscripcion-y-pagos" className="space-y-3">
      <div>
        <h3 className="text-sm font-bold text-white">Suscripción</h3>
        {subscription ? (
          <p className="mt-2 text-sm leading-relaxed text-muted">
            <span className="font-bold text-white">{subscription.plan.name}</span>
            {" · "}
            {SUBSCRIPTION_STATUS_LABEL[subscription.status].toLowerCase()}
            {" · "}
            {subscription.in_force ? "vigente" : "vencida"}
            {subscription.current_period_end
              ? subscription.in_force
                ? `, hasta el ${formatLegalDate(subscription.current_period_end)}`
                : ` el ${formatLegalDate(subscription.current_period_end)}`
              : ""}
            {" · "}
            {formatMoney(subscription.price_cents, subscription.currency)} /{" "}
            {intervalLabel(subscription.plan.interval, subscription.plan.interval_count)} (precio
            congelado){" · "}
            {RENEWAL_MODE_LABEL[subscription.renewal_mode]}
          </p>
        ) : (
          <p className="mt-2 text-sm text-muted">Esta cuenta nunca ha pagado una suscripción.</p>
        )}
      </div>

      {subscription ? (
        <Link
          href={`/admin/suscripciones?query=${encodeURIComponent(detail.user.email)}`}
          className="inline-block text-sm font-bold text-gold underline-offset-2 hover:underline"
        >
          Extender o cancelar en Suscripciones →
        </Link>
      ) : null}

      <div>
        <h3 className="text-sm font-bold text-white">Pagos</h3>
        {payments.length === 0 ? (
          <p className="mt-2 text-sm text-muted">Sin intentos de pago.</p>
        ) : (
          <ul className="mt-2 divide-y divide-edge">
            {payments.map((p) => (
              <li key={p.id} className="py-2 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <p className="text-white">
                    <span className="font-bold">{formatMoney(p.amount_cents, p.currency)}</span>
                    {" · "}
                    {p.plan_name}
                    {p.discount_cents > 0
                      ? ` · con descuento de ${formatMoney(p.discount_cents, p.currency)}`
                      : ""}
                  </p>
                  <span className="flex flex-wrap gap-1.5">
                    {p.reversed_at ? <Badge>Anulado después</Badge> : null}
                    {p.refunded_cents > 0 ? (
                      <Badge>Reembolsado {formatMoney(p.refunded_cents, p.currency)}</Badge>
                    ) : null}
                    <Badge tone={PAYMENT_STATUS_TONE[p.status]}>
                      {PAYMENT_STATUS_LABEL[p.status]}
                    </Badge>
                  </span>
                </div>
                <p className="mt-0.5 break-all text-xs text-muted">
                  {formatDateTime(p.resolved_at ?? p.created_at)}
                  {p.period_start && p.period_end
                    ? ` · período del ${formatLegalDate(p.period_start)} al ${formatLegalDate(p.period_end)}`
                    : ""}
                  {" · "}referencia{" "}
                  <Link
                    href={`/admin/pagos?query=${encodeURIComponent(p.reference)}`}
                    className="text-gold underline-offset-2 hover:underline"
                  >
                    {p.reference}
                  </Link>
                  {p.provider_transaction_id ? ` · transacción ${p.provider_transaction_id}` : ""}
                  {p.failure_reason ? ` · ${p.failure_reason}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted">
          Se muestran los últimos 20 intentos. Los eventos de la pasarela, reconsultar un pago y
          registrar un reembolso están en Pagos (el enlace de cada referencia).
        </p>
      </div>
    </section>
  );
}
