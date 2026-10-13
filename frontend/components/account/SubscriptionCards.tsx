"use client";

/**
 * Apartado de suscripción y pagos de "Mi cuenta" (§3.6 y §5.4 de la Fase 4).
 *
 * Muestra lo que el servidor dice de la suscripción (`GET /billing/subscription`)
 * y del historial (`GET /billing/payments`), y deja cancelar o reanudar la
 * renovación automática. Cambiar el medio de pago y pasar de un modo al otro
 * llegan con la entrega 3 del paso 5. Aquí no se calcula ningún precio ni se
 * decide ningún acceso.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Button, Card, CardHeader, ErrorBox } from "@/components/ui";
import { ApiError, billingApi } from "@/lib/api-client";
import {
  PAYMENT_STATUS_LABEL,
  PAYMENT_STATUS_TONE,
  RENEWAL_MODE_LABEL,
  sourceLabel,
} from "@/lib/billing";
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
  // Cancelar pide confirmar en la misma tarjeta, sin ventanas del navegador.
  const [confirming, setConfirming] = useState(false);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    withToken((t) => billingApi.subscription(t))
      .then(setSubscription)
      .catch((err) => setError(messageOf(err)));
  }, [withToken]);

  async function change(action: "cancel" | "resume") {
    setWorking(true);
    setError(null);
    setNotice(null);
    try {
      const next = await withToken((t) =>
        action === "cancel" ? billingApi.cancelSubscription(t) : billingApi.resumeSubscription(t),
      );
      setSubscription(next);
      setConfirming(false);
      setNotice(
        action === "cancel"
          ? "Renovación cancelada. No te vamos a hacer más cobros."
          : "Renovación reanudada.",
      );
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setWorking(false);
    }
  }

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
            {!subscription.in_force ? (
              <Badge tone="off">Vencida</Badge>
            ) : subscription.status === "canceled" ? (
              <Badge tone="neutral">Renovación cancelada</Badge>
            ) : subscription.status === "past_due" ? (
              <Badge tone="off">Cobro pendiente</Badge>
            ) : (
              <Badge tone="ok">Vigente</Badge>
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
            {subscription.renewal_mode === "automatic" && sourceLabel(subscription) ? (
              <Row label="Medio de pago">{sourceLabel(subscription)}</Row>
            ) : null}
            {subscription.next_charge_at && subscription.next_charge_cents !== null ? (
              <Row label="Próximo cobro">
                {formatMoney(subscription.next_charge_cents, subscription.currency)}, a partir del{" "}
                {formatLegalDate(subscription.next_charge_at)}
              </Row>
            ) : null}
          </dl>
          {notice ? (
            <p role="status" className="mt-3 text-sm font-bold text-white">
              {notice}
            </p>
          ) : null}

          {withoutPaying ? (
            // Con acceso manual no se le cobra a mano; lo ya pagado sigue corriendo.
            <p className="mt-4 text-sm leading-relaxed text-muted">
              {withoutPaying} Mientras lo tenga no necesitas pagar; el período que ya pagaste
              sigue corriendo.
            </p>
          ) : !subscription.in_force ? (
            <p className="mt-4 text-sm leading-relaxed text-muted">
              Tu período terminó y ya no tienes acceso a la mesa. Puedes volver cuando quieras
              desde{" "}
              <Link href="/planes" className={LINK}>
                los planes
              </Link>
              .
            </p>
          ) : subscription.status === "canceled" ? (
            <div className="mt-4 space-y-3">
              <p className="text-sm leading-relaxed text-muted">
                Cancelaste la renovación: no se hace ningún cobro más y conservas el acceso hasta
                esa fecha. Si cambias de opinión antes, puedes reanudarla.
              </p>
              <Button variant="ghost" disabled={working} onClick={() => change("resume")}>
                {working ? "Reanudando…" : "Reanudar la renovación"}
              </Button>
            </div>
          ) : subscription.renewal_mode === "automatic" ? (
            <div className="mt-4 space-y-3">
              <p className="text-sm leading-relaxed text-muted">
                {subscription.status === "past_due"
                  ? "No pudimos hacer el último cobro. Lo vamos a intentar de nuevo antes de que termine tu período; si no pasa, tu suscripción vence ese día. "
                  : "Se renueva sola. "}
                Antes de cada cobro te avisamos por correo con el monto y la fecha. Si cancelas,
                conservas el acceso hasta que termine el período que ya pagaste.
              </p>
              {confirming ? (
                <div
                  role="group"
                  aria-label="Confirmar la cancelación"
                  className="rounded-lg border border-edge p-3.5"
                >
                  <p className="text-sm text-white">
                    ¿Cancelar la renovación? No se te cobra más y tu acceso sigue hasta el{" "}
                    {subscription.current_period_end
                      ? formatLegalDate(subscription.current_period_end)
                      : "fin del período"}
                    .
                  </p>
                  <div className="mt-3 flex flex-wrap gap-3">
                    <Button variant="danger" disabled={working} onClick={() => change("cancel")}>
                      {working ? "Cancelando…" : "Sí, cancelar la renovación"}
                    </Button>
                    <Button variant="ghost" disabled={working} onClick={() => setConfirming(false)}>
                      No, dejarla como está
                    </Button>
                  </div>
                </div>
              ) : (
                <Button variant="ghost" onClick={() => setConfirming(true)}>
                  Cancelar la renovación
                </Button>
              )}
            </div>
          ) : (
            <p className="mt-4 text-sm leading-relaxed text-muted">
              No se hace ningún cobro automático. Si quieres seguir después de esa fecha,{" "}
              <Link href={`/planes/pagar?plan=${subscription.plan.id}`} className={LINK}>
                paga el siguiente período
              </Link>{" "}
              antes de que venza: empieza cuando termine el actual, así que no pierdes días.
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
