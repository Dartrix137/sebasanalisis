"use client";

/**
 * Trasladar el precio actual de un plan a sus suscripciones vigentes (§4.10 de
 * la Fase 4). Va en `/admin/planes`, debajo del formulario del plan.
 *
 * Todo lo decide el servidor: cuántas suscripciones alcanza, cuándo aplica a
 * cada una y qué correo le llega. Aquí se explica antes de pedirlo:
 *
 * - una subida se cobra 30 días después de que a cada cliente le llegó el aviso;
 * - una bajada aplica ya, desde su próximo cobro;
 * - un descuento que todavía corre sigue descontando sobre el precio nuevo;
 * - se puede cancelar mientras no se haya aplicado.
 */

import { useCallback, useEffect, useState } from "react";

import { SuccessBox } from "@/components/AuthShell";
import { Button, CardHeader, Checkbox, ErrorBox, Field } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import { formatDateTime } from "@/lib/admin";
import { formatMoney, intervalLabel } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { AdminPlanResponse, PriceChangeResponse, PriceTransferPreview } from "@/lib/types/billing";

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

export function PriceTransferPanel({ plan }: { plan: AdminPlanResponse }) {
  const { withToken } = useSession();
  const [preview, setPreview] = useState<PriceTransferPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setPreview(await withToken((t) => adminApi.priceTransferPreview(t, plan.id)));
  }, [withToken, plan.id]);

  useEffect(() => {
    load().catch((e) => setError(messageOf(e)));
  }, [load]);

  if (error) return <ErrorBox message={error} />;
  if (!preview) return null;

  const price = `${formatMoney(preview.price_cents, preview.currency)} / ${intervalLabel(plan.interval, plan.interval_count)}`;
  const eligible = preview.increases + preview.decreases;

  return (
    <section
      className="mt-4 space-y-3 rounded-lg border border-edge p-3.5"
      aria-label="Precio de las suscripciones vigentes"
    >
      <CardHeader
        title="Precio de las suscripciones vigentes"
        subtitle={`Cada suscripción conserva el precio con que se suscribió. Trasladar lleva el precio actual (${price}) a las vigentes de este plan, en los dos modos de pago; las canceladas no.`}
      />
      {preview.open_change ? (
        <OpenChange change={preview.open_change} onDone={load} />
      ) : eligible === 0 ? (
        <p className="text-sm text-muted">
          Todas las suscripciones vigentes de este plan ya pagan el precio actual.
        </p>
      ) : (
        <TransferForm planId={plan.id} preview={preview} price={price} onDone={load} />
      )}
    </section>
  );
}

function TransferForm({
  planId,
  preview,
  price,
  onDone,
}: {
  planId: string;
  preview: PriceTransferPreview;
  price: string;
  onDone: () => Promise<void>;
}) {
  const { withToken } = useSession();
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await withToken((t) => adminApi.createPriceTransfer(t, planId, { reason }));
      await onDone();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3" aria-label="Trasladar el precio">
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
        {preview.increases > 0 ? (
          <li>
            <span className="font-bold text-white">
              {preview.increases} suscripcion{preview.increases === 1 ? "" : "es"} sube
              {preview.increases === 1 ? "" : "n"} a {price}.
            </span>{" "}
            A cada cliente le llega un aviso por correo y el precio nuevo se le cobra desde 30 días
            después de ese aviso. Si el correo no sale, no corre el plazo.
          </li>
        ) : null}
        {preview.decreases > 0 ? (
          <li>
            <span className="font-bold text-white">
              {preview.decreases} suscripcion{preview.decreases === 1 ? "" : "es"} baja
              {preview.decreases === 1 ? "" : "n"} a {price}.
            </span>{" "}
            Aplica ya, desde su próximo cobro, y se le avisa por correo.
          </li>
        ) : null}
        <li>Un descuento que todavía corre se sigue aplicando, sobre el precio nuevo.</li>
      </ul>
      <Field
        label="Motivo del traslado"
        required
        minLength={3}
        maxLength={500}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}>
        Entiendo que se les escribirá a estos clientes y que cambiará lo que se les cobra.
      </Checkbox>
      {error ? <ErrorBox message={error} /> : null}
      <Button type="submit" variant="danger" disabled={pending || !confirmed}>
        {pending ? "Un momento…" : "Trasladar el precio a las vigentes"}
      </Button>
    </form>
  );
}

function OpenChange({
  change,
  onDone,
}: {
  change: PriceChangeResponse;
  onDone: () => Promise<void>;
}) {
  const { withToken } = useSession();
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await withToken((t) => adminApi.cancelPriceTransfer(t, change.id, { reason }));
      setDone(true);
      await onDone();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-3" data-testid="traslado-en-curso">
      <p className="text-sm text-white">
        <span className="font-bold">
          Traslado en curso a {formatMoney(change.new_price_cents, change.currency)}
        </span>
        , registrado el {formatDateTime(change.created_at)} por {change.created_by_email}.
      </p>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
        <Count label="Suscripciones" value={change.total} />
        <Count label="Avisadas" value={change.notified} />
        <Count label="Esperando su aviso" value={change.waiting_notice} />
        <Count label="Con el precio aplicado" value={change.applied} />
      </dl>
      <p className="text-xs text-muted">Motivo: {change.reason}</p>
      <form onSubmit={handleSubmit} className="space-y-3" aria-label="Cancelar el traslado">
        <p className="text-sm text-muted">
          Cancelarlo deja con su precio a las suscripciones a las que todavía no se les aplicó. A
          quien ya recibió el aviso le llega otro que dice que el precio no cambia.
        </p>
        <Field
          label="Motivo de la cancelación"
          required
          minLength={3}
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        {error ? <ErrorBox message={error} /> : null}
        {done ? <SuccessBox message="Traslado cancelado" /> : null}
        <Button type="submit" variant="ghost" disabled={pending}>
          {pending ? "Un momento…" : "Cancelar el traslado"}
        </Button>
      </form>
    </div>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-bold text-white">{value}</dd>
    </div>
  );
}
