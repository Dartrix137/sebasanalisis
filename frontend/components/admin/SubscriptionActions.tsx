"use client";

/**
 * Acciones del administrador sobre una suscripción (§4.3 de la Fase 4): extender
 * el período, cancelar la renovación al final del período y cancelar de
 * inmediato. Las usan `/admin/suscripciones` y el detalle de la cuenta en
 * `/admin/usuarios`.
 *
 * Todo lo decide el servidor (`PATCH /admin/subscriptions/:id`): aquí solo se
 * explica qué hace cada acción antes de pedirla. Cada una pide un motivo, queda
 * en la bitácora y le llega un correo al cliente (sin el motivo).
 */

import { useState } from "react";

import { SuccessBox } from "@/components/AuthShell";
import { Button, CardHeader, Checkbox, ErrorBox, Field } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import { formatLegalDate } from "@/lib/legal";
import { useSession } from "@/lib/session";
import type { SubscriptionAdminAction } from "@/lib/types/admin";
import type { SubscriptionResponse } from "@/lib/types/billing";

const MAX_DAYS = 90;

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

export function SubscriptionActions({
  subscription,
  onDone,
}: {
  subscription: SubscriptionResponse;
  onDone: () => Promise<void>;
}) {
  if (!subscription.in_force) {
    return (
      <p className="rounded-lg border border-edge p-3.5 text-sm leading-relaxed text-muted">
        <span className="font-bold text-white">Sin período vigente.</span> Extender o cancelar solo
        aplica a una suscripción con el período pagado vigente. Para darle acceso a esta cuenta, usa
        el acceso manual.
      </p>
    );
  }

  const renews =
    subscription.renewal_mode === "automatic" &&
    (subscription.status === "active" || subscription.status === "past_due");
  const until = subscription.current_period_end
    ? formatLegalDate(subscription.current_period_end)
    : "";

  return (
    <div className="space-y-3" data-testid="acciones-suscripcion">
      <ActionForm
        subscriptionId={subscription.id}
        action="extend"
        title="Extender el período"
        subtitle={
          renews
            ? `Corre el vencimiento (hoy el ${until}) sin cobrar nada. El próximo cobro y su aviso se corren con la fecha nueva.`
            : `Corre el vencimiento (hoy el ${until}) sin cobrar nada.`
        }
        button="Extender"
        withDays
        onDone={onDone}
      />
      {renews ? (
        <ActionForm
          subscriptionId={subscription.id}
          action="cancel_at_period_end"
          title="Cancelar la renovación al final del período"
          subtitle={`Conserva el acceso hasta el ${until} y no se le vuelve a cobrar. El cliente puede reanudarla desde su cuenta antes de esa fecha.`}
          button="Cancelar la renovación"
          onDone={onDone}
        />
      ) : null}
      <ActionForm
        subscriptionId={subscription.id}
        action="cancel_now"
        title="Cancelar de inmediato"
        subtitle="La cuenta pierde el acceso ahora y no se le vuelve a cobrar. No se devuelve nada: si corresponde, el reembolso se hace en el panel de Wompi y se registra en Pagos."
        button="Cancelar de inmediato"
        confirm="Entiendo que la cuenta pierde el acceso ahora, aunque haya pagado el período."
        danger
        onDone={onDone}
      />
      <p className="text-xs text-muted">
        Al cliente le llega un correo con el cambio. El motivo queda solo en la bitácora.
      </p>
    </div>
  );
}

function ActionForm({
  subscriptionId,
  action,
  title,
  subtitle,
  button,
  withDays = false,
  confirm,
  danger = false,
  onDone,
}: {
  subscriptionId: string;
  action: SubscriptionAdminAction;
  title: string;
  subtitle: string;
  button: string;
  withDays?: boolean;
  /** Casilla que hay que marcar antes de poder enviar. */
  confirm?: string;
  danger?: boolean;
  onDone: () => Promise<void>;
}) {
  const { withToken } = useSession();
  const [days, setDays] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      await withToken((t) =>
        adminApi.updateSubscription(t, subscriptionId, {
          action,
          days: withDays ? Number(days) : null,
          reason,
        }),
      );
      setReason("");
      setDays("");
      setConfirmed(false);
      setSaved(true);
      await onDone();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-lg border border-edge p-3.5"
      aria-label={title}
    >
      <CardHeader title={title} subtitle={subtitle} />
      <div className={withDays ? "grid gap-3 sm:grid-cols-[10rem_1fr]" : ""}>
        {withDays ? (
          <Field
            label="Días"
            type="number"
            required
            min={1}
            max={MAX_DAYS}
            inputMode="numeric"
            hint={`De 1 a ${MAX_DAYS}.`}
            value={days}
            onChange={(e) => setDays(e.target.value)}
          />
        ) : null}
        <Field
          label="Motivo"
          required
          minLength={3}
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </div>
      {confirm ? (
        <Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}>
          {confirm}
        </Checkbox>
      ) : null}
      {error ? <ErrorBox message={error} /> : null}
      {saved ? <SuccessBox message="Listo. El cambio quedó en la bitácora." /> : null}
      <Button
        type="submit"
        variant={danger ? "danger" : "ghost"}
        disabled={pending || (confirm !== undefined && !confirmed)}
      >
        {pending ? "Un momento…" : button}
      </Button>
    </form>
  );
}
