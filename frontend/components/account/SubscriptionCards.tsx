"use client";

/**
 * Apartado de suscripción y pagos de "Mi cuenta" (§3.6 y §5.4 de la Fase 4).
 *
 * Muestra lo que el servidor dice de la suscripción (`GET /billing/subscription`)
 * y del historial (`GET /billing/payments`), y deja gestionarla: cancelar o
 * reanudar la renovación automática, cambiar el medio de pago guardado y pasar
 * de un modo de pago al otro. Aquí no se calcula ningún precio ni se decide
 * ningún acceso. Un medio de pago se guarda con `PaymentSourceForm`, que manda
 * la tarjeta o el Nequi directo a Wompi.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { PaymentSourceForm } from "@/components/billing/PaymentSourceForm";
import { Badge, Button, Card, CardHeader, ErrorBox, SuccessBox } from "@/components/ui";
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
import type { TokenizedSource } from "@/lib/tokenize";
import type {
  AcceptanceResponse,
  BillingAvailabilityResponse,
  PaymentListResponse,
  SubscriptionResponse,
} from "@/lib/types/billing";

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

/** Lo que la tarjeta tiene abierto: una confirmación o el formulario del medio de pago. */
type Panel = "cancel" | "manual" | "source" | null;

export function SubscriptionCard() {
  const { user, withToken } = useSession();
  // `undefined` = todavía no llegó; `null` = la cuenta nunca pagó una suscripción.
  const [subscription, setSubscription] = useState<SubscriptionResponse | null | undefined>(
    undefined,
  );
  const [availability, setAvailability] = useState<BillingAvailabilityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Todo se confirma en la misma tarjeta, sin ventanas del navegador.
  const [panel, setPanel] = useState<Panel>(null);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // El medio de pago se acaba de guardar: su fila lo marca hasta la siguiente acción.
  const [sourceUpdated, setSourceUpdated] = useState(false);
  const noticeRef = useRef<HTMLDivElement>(null);

  // Al guardar, el formulario se cierra y la tarjeta cambia de alto: se lleva
  // la vista hasta la confirmación para que no pase desapercibida.
  useEffect(() => {
    if (notice) noticeRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [notice]);

  useEffect(() => {
    withToken((t) => billingApi.subscription(t))
      .then(setSubscription)
      .catch((err) => setError(messageOf(err)));
    // Si no responde, simplemente no se ofrece guardar un medio de pago.
    billingApi
      .availability()
      .then(setAvailability)
      .catch(() => undefined);
  }, [withToken]);

  function show(next: Panel) {
    setPanel(next);
    setError(null);
    setNotice(null);
    setSourceUpdated(false);
  }

  async function run(
    request: (token: string) => Promise<SubscriptionResponse>,
    done: (next: SubscriptionResponse) => string,
  ): Promise<boolean> {
    setWorking(true);
    setError(null);
    setNotice(null);
    setSourceUpdated(false);
    try {
      const next = await withToken(request);
      setSubscription(next);
      setPanel(null);
      setNotice(done(next));
      return true;
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setWorking(false);
    }
    return false;
  }

  async function saveSource(source: TokenizedSource, acceptance: AcceptanceResponse) {
    const before = subscription;
    const saved = await run(
      (t) =>
        billingApi.setPaymentMethod(t, {
          payment_source_token: source.token,
          payment_source_type: source.type,
          acceptance_token: acceptance.acceptance_token,
          personal_data_token: acceptance.personal_data_token,
        }),
      (next) => {
        const label = sourceLabel(next) ?? "tu medio de pago";
        if (before?.status === "past_due") {
          return next.status === "past_due"
            ? `Medio de pago guardado: ${label}. Volvimos a intentar el cobro pendiente y todavía no pasó; el resultado te llega por correo.`
            : `Medio de pago guardado: ${label}. El cobro pendiente quedó aprobado.`;
        }
        return before?.renewal_mode === "automatic" && before.status !== "canceled"
          ? `Medio de pago actualizado: ${label}. Hoy no se te cobró nada.`
          : `Renovación automática activada con ${label}. Hoy no se te cobró nada.`;
      },
    );
    if (saved) setSourceUpdated(true);
  }

  // El acceso que no sale de una suscripción (administrador o acceso manual).
  const reason = user?.access.reason;
  const withoutPaying =
    user?.access.granted && reason !== "subscription"
      ? reason === "admin"
        ? "Tu cuenta entra a la mesa por ser administradora."
        : "Tu cuenta tiene acceso otorgado por un administrador."
      : null;

  const canSaveSource = availability?.enabled === true && availability.tokenizer !== null;
  const until = subscription?.current_period_end
    ? formatLegalDate(subscription.current_period_end)
    : "fin del período";
  const automatic = subscription?.renewal_mode === "automatic";
  const canceled = subscription?.status === "canceled";

  const sourceForm =
    panel === "source" && availability ? (
      <div
        role="group"
        aria-label="Guardar un medio de pago"
        className="rounded-lg border border-edge p-3.5"
      >
        <p className="mb-3 text-sm text-white">
          {automatic && !canceled
            ? "El medio nuevo reemplaza al que tienes guardado. Hoy no se te cobra nada: el próximo cobro es el de la renovación, y antes te avisamos por correo."
            : `Hoy no se te cobra nada: ya pagaste hasta el ${until}. Desde entonces se renueva sola con el medio que guardes, y antes de cada cobro te avisamos por correo.`}
          {subscription?.status === "past_due"
            ? " Como tienes un cobro pendiente, lo intentamos de inmediato con el medio nuevo."
            : ""}
        </p>
        <PaymentSourceForm
          availability={availability}
          submitLabel="Guardar medio de pago"
          busyLabel="Guardando…"
          busy={working}
          onSource={saveSource}
        />
        <div className="mt-3">
          <Button variant="ghost" disabled={working} onClick={() => show(null)}>
            Ahora no
          </Button>
        </div>
      </div>
    ) : null;

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
            ) : canceled ? (
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
            {subscription.price_change ? (
              // Un cambio de precio que ya se le avisó por correo (§4.10). En la
              // renovación automática se dice desde qué cobro: un período cuyo
              // primer intento llega antes de la fecha se cobra con el precio viejo.
              <Row label="Precio nuevo">
                {formatMoney(subscription.price_change.new_price_cents, subscription.currency)} /{" "}
                {intervalLabel(subscription.plan.interval, subscription.plan.interval_count)},{" "}
                {subscription.price_change.first_charge_at
                  ? `desde el cobro del ${formatLegalDate(subscription.price_change.first_charge_at)}`
                  : `desde el ${formatLegalDate(subscription.price_change.effective_at)}`}
              </Row>
            ) : null}
            <Row label="Forma de pago">{RENEWAL_MODE_LABEL[subscription.renewal_mode]}</Row>
            {automatic && sourceLabel(subscription) ? (
              <Row label="Medio de pago">
                {sourceUpdated ? (
                  <span className="mr-2">
                    <Badge tone="ok">Actualizado</Badge>
                  </span>
                ) : null}
                {sourceLabel(subscription)}
              </Row>
            ) : null}
            {subscription.next_charge_at && subscription.next_charge_cents !== null ? (
              <Row label="Próximo cobro">
                {formatMoney(subscription.next_charge_cents, subscription.currency)}, a partir del{" "}
                {formatLegalDate(subscription.next_charge_at)}
              </Row>
            ) : null}
          </dl>
          {notice ? (
            <div ref={noticeRef} className="mt-3 scroll-mt-4">
              <SuccessBox message={notice} />
            </div>
          ) : null}

          {withoutPaying ? (
            // Con acceso manual no hace falta pagar; lo ya pagado sigue corriendo.
            <p className="mt-4 text-sm leading-relaxed text-muted">
              {withoutPaying} Mientras lo tenga no necesitas pagar; el período que ya pagaste
              sigue corriendo.
              {automatic && subscription.in_force && !canceled
                ? " Tu suscripción se sigue renovando sola: si no quieres ese cobro, cancela la renovación."
                : ""}
            </p>
          ) : null}

          {!subscription.in_force ? (
            withoutPaying ? null : (
              <p className="mt-4 text-sm leading-relaxed text-muted">
                Tu período terminó y ya no tienes acceso a la mesa. Puedes volver cuando quieras
                desde{" "}
                <Link href="/planes" className={LINK}>
                  los planes
                </Link>
                .
              </p>
            )
          ) : canceled ? (
            <div className="mt-4 space-y-3">
              <p className="text-sm leading-relaxed text-muted">
                Cancelaste la renovación: no se hace ningún cobro más y conservas el acceso hasta
                esa fecha. Si cambias de opinión antes, puedes reanudarla.
              </p>
              {sourceForm ?? (
                <div className="flex flex-wrap gap-3">
                  <Button
                    variant="ghost"
                    disabled={working}
                    onClick={() =>
                      run(
                        (t) => billingApi.resumeSubscription(t),
                        () => "Renovación reanudada.",
                      )
                    }
                  >
                    {working ? "Reanudando…" : "Reanudar la renovación"}
                  </Button>
                  {canSaveSource ? (
                    <Button variant="ghost" disabled={working} onClick={() => show("source")}>
                      Reanudar con otro medio de pago
                    </Button>
                  ) : null}
                </div>
              )}
            </div>
          ) : automatic ? (
            <div className="mt-4 space-y-3">
              <p className="text-sm leading-relaxed text-muted">
                {subscription.status === "past_due"
                  ? "No pudimos hacer el último cobro. Lo vamos a intentar de nuevo antes de que termine tu período; si no pasa, tu suscripción vence ese día. Si el problema es tu medio de pago, cámbialo: al guardarlo intentamos el cobro de inmediato. "
                  : "Se renueva sola. "}
                Antes de cada cobro te avisamos por correo con el monto y la fecha. Si cancelas,
                conservas el acceso hasta que termine el período que ya pagaste.
              </p>
              {panel === "cancel" ? (
                <div
                  role="group"
                  aria-label="Confirmar la cancelación"
                  className="rounded-lg border border-edge p-3.5"
                >
                  <p className="text-sm text-white">
                    ¿Cancelar la renovación? No se te cobra más y tu acceso sigue hasta el {until}.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-3">
                    <Button
                      variant="danger"
                      disabled={working}
                      onClick={() =>
                        run(
                          (t) => billingApi.cancelSubscription(t),
                          () => "Renovación cancelada. No te vamos a hacer más cobros.",
                        )
                      }
                    >
                      {working ? "Cancelando…" : "Sí, cancelar la renovación"}
                    </Button>
                    <Button variant="ghost" disabled={working} onClick={() => show(null)}>
                      No, dejarla como está
                    </Button>
                  </div>
                </div>
              ) : panel === "manual" ? (
                <div
                  role="group"
                  aria-label="Confirmar el paso a pago manual"
                  className="rounded-lg border border-edge p-3.5"
                >
                  <p className="text-sm text-white">
                    ¿Pasar a pago manual? Dejamos de guardar tu medio de pago y no se te cobra
                    más. Tu acceso sigue hasta el {until}; para seguir después, pagas tú el
                    siguiente período, y unos días antes te lo recordamos por correo.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-3">
                    <Button
                      variant="danger"
                      disabled={working}
                      onClick={() =>
                        run(
                          (t) => billingApi.removePaymentMethod(t),
                          () =>
                            "Tu suscripción pasó a pago manual. No te vamos a hacer más cobros automáticos.",
                        )
                      }
                    >
                      {working ? "Cambiando…" : "Sí, pasar a pago manual"}
                    </Button>
                    <Button variant="ghost" disabled={working} onClick={() => show(null)}>
                      No, dejarla como está
                    </Button>
                  </div>
                </div>
              ) : (
                (sourceForm ?? (
                  <div className="flex flex-wrap gap-3">
                    {canSaveSource ? (
                      <Button variant="ghost" onClick={() => show("source")}>
                        Cambiar el medio de pago
                      </Button>
                    ) : null}
                    <Button variant="ghost" onClick={() => show("manual")}>
                      Pasar a pago manual
                    </Button>
                    <Button variant="ghost" onClick={() => show("cancel")}>
                      Cancelar la renovación
                    </Button>
                  </div>
                ))
              )}
            </div>
          ) : withoutPaying ? null : (
            <div className="mt-4 space-y-3">
              <p className="text-sm leading-relaxed text-muted">
                No se hace ningún cobro automático. Si quieres seguir después de esa fecha,{" "}
                <Link href={`/planes/pagar?plan=${subscription.plan.id}`} className={LINK}>
                  paga el siguiente período
                </Link>{" "}
                antes de que venza: empieza cuando termine el actual, así que no pierdes días.
              </p>
              {sourceForm ??
                (canSaveSource ? (
                  <Button variant="ghost" onClick={() => show("source")}>
                    Activar la renovación automática
                  </Button>
                ) : null)}
            </div>
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
