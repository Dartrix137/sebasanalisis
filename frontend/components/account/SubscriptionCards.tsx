"use client";

/**
 * Apartado de suscripción y pagos de "Mi cuenta" (§3.6 y §5.4 de la Fase 4).
 *
 * De solo lectura: muestra lo que el servidor dice de la suscripción
 * (`GET /billing/subscription`) y del historial (`GET /billing/payments`).
 * Cancelar, reanudar y cambiar el medio de pago llegan con la entrega 3 del
 * paso 5. Aquí no se calcula ningún precio ni se decide ningún acceso.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Card, CardHeader, ErrorBox } from "@/components/ui";
import { ApiError, billingApi } from "@/lib/api-client";
import { PAYMENT_STATUS_LABEL, PAYMENT_STATUS_TONE, RENEWAL_MODE_LABEL } from "@/lib/billing";
import { formatLegalDate } from "@/lib/legal";
import { formatMoney, intervalLabel } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { PaymentListResponse, SubscriptionResponse } from "@/lib/types/billing";

const LINK = "font-bold text-gold hover:text-gold-soft";

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-4 gap-y-0.5 py-1.5">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right text-white">{children}</dd>
    </div>
  );
}

export function SubscriptionCard() {
  const { user, withToken } = useSession();
  // `undefined` = todavía no llegó; `null` = la cuenta nunca pagó una suscripción.
  const [subscription, setSubscription] = useState<SubscriptionResponse | null | undefined>(
    undefined,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    withToken((t) => billingApi.subscription(t))
      .then(setSubscription)
      .catch((err) => setError(messageOf(err)));
  }, [withToken]);

  // El acceso que no sale de una suscripción (administrador o acceso manual).
  const reason = user?.access.reason;
  const withoutPaying =
    user?.access.granted && reason !== "subscription"
      ? reason === "admin"
        ? "Tu cuenta entra a la mesa por ser administradora."
        : "Tu cuenta tiene acceso otorgado por un administrador."
      : null;

  return (
    <Card>
      <CardHeader title="Suscripción" subtitle="Tu plan y hasta cuándo tienes acceso." />
      {error ? <ErrorBox message={error} /> : null}

      {subscription === null ? (
        <div className="space-y-3 text-sm">
          <p className="text-muted">
            {withoutPaying ?? "No tienes una suscripción."}
            {withoutPaying ? " No tienes una suscripción, y no la necesitas." : ""}
          </p>
          {withoutPaying ? null : (
            <Link href="/planes" className={LINK}>
              Ver los planes
            </Link>
          )}
        </div>
      ) : null}

      {subscription ? (
        <div data-testid="suscripcion">
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-base font-bold text-white">{subscription.plan.name}</p>
            {subscription.in_force ? (
              <Badge tone="ok">Vigente</Badge>
            ) : (
              <Badge tone="off">Vencida</Badge>
            )}
          </div>
          <dl className="mt-3 divide-y divide-edge text-sm">
            {subscription.current_period_end ? (
              <Row label={subscription.in_force ? "Acceso hasta" : "Venció el"}>
                {formatLegalDate(subscription.current_period_end)}
              </Row>
            ) : null}
            <Row label="Precio">
              {formatMoney(subscription.price_cents, subscription.currency)} /{" "}
              {intervalLabel(subscription.plan.interval, subscription.plan.interval_count)}
            </Row>
            <Row label="Forma de pago">{RENEWAL_MODE_LABEL[subscription.renewal_mode]}</Row>
          </dl>

          {withoutPaying ? (
            // Con acceso manual no se le cobra: el período pagado sigue corriendo.
            <p className="mt-4 text-sm leading-relaxed text-muted">
              {withoutPaying} Mientras lo tenga no necesitas pagar; el período que ya pagaste
              sigue corriendo.
            </p>
          ) : subscription.in_force ? (
            <p className="mt-4 text-sm leading-relaxed text-muted">
              No se hace ningún cobro automático. Si quieres seguir después de esa fecha,{" "}
              <Link href={`/planes/pagar?plan=${subscription.plan.id}`} className={LINK}>
                paga el siguiente período
              </Link>{" "}
              antes de que venza: empieza cuando termine el actual, así que no pierdes días.
            </p>
          ) : (
            <p className="mt-4 text-sm leading-relaxed text-muted">
              Tu período terminó y ya no tienes acceso a la mesa. Puedes volver cuando quieras
              desde{" "}
              <Link href="/planes" className={LINK}>
                los planes
              </Link>
              .
            </p>
          )}
        </div>
      ) : null}
    </Card>
  );
}

export function PaymentsCard() {
  const { withToken } = useSession();
  const [page, setPage] = useState<PaymentListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    withToken((t) => billingApi.payments(t))
      .then(setPage)
      .catch((err) => setError(messageOf(err)));
  }, [withToken]);

  return (
    <Card>
      <CardHeader
        title="Historial de pagos"
        subtitle="Los cobros de tu cuenta, del más reciente al más antiguo. El recibo de cada pago aprobado te llegó por correo."
      />
      {error ? <ErrorBox message={error} /> : null}
      {page?.items.length === 0 ? (
        <p className="text-sm text-muted">Todavía no hay pagos en tu cuenta.</p>
      ) : null}
      {page?.items.length ? (
        <ul className="divide-y divide-edge" data-testid="historial-de-pagos">
          {page.items.map((p) => (
            <li
              key={p.id}
              className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5 text-sm"
            >
              <div className="min-w-0">
                <p className="font-bold text-white">
                  {formatMoney(p.amount_cents, p.currency)} · {p.plan_name}
                </p>
                <p className="text-xs text-muted">
                  {formatLegalDate(p.resolved_at ?? p.created_at)}
                  {p.period_start && p.period_end
                    ? ` · Período del ${formatLegalDate(p.period_start)} al ${formatLegalDate(p.period_end)}`
                    : ""}
                </p>
              </div>
              <Badge tone={PAYMENT_STATUS_TONE[p.status]}>{PAYMENT_STATUS_LABEL[p.status]}</Badge>
            </li>
          ))}
        </ul>
      ) : null}
      {page && page.total > page.items.length ? (
        <p className="mt-3 text-xs text-muted">
          Se muestran los {page.items.length} más recientes de {page.total}.
        </p>
      ) : null}
    </Card>
  );
}
