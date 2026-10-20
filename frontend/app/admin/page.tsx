"use client";

/**
 * Admin: resumen del negocio (§4.7 de la Fase 4). Tarjetas con número y, en los
 * indicadores de flujo, la comparación con el mismo tramo del mes anterior. Sin
 * gráficos. Todo lo calcula el servidor (`GET /admin/overview`); aquí solo se
 * le da formato.
 *
 * Las fotos del momento (suscripciones por estado, ingreso recurrente) no se
 * comparan: la base no guarda cómo estaban en una fecha pasada.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { PageSkeleton } from "@/components/PageSkeleton";
import { Card, ErrorBox } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import { SUBSCRIPTION_STATUS_LABEL } from "@/lib/billing";
import { formatMoney } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { AdminOverviewResponse, Comparison } from "@/lib/types/admin";

/** Si que suba es bueno, malo, o ninguna de las dos. Decide el color de la variación. */
type Direction = "up_is_good" | "up_is_bad" | "neutral";

const DAY = new Intl.DateTimeFormat("es-CO", {
  day: "numeric",
  month: "long",
  timeZone: "America/Bogota",
});

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo cargar el resumen";
}

function formatRate(bp: number | null): string {
  if (bp === null) return "—";
  return `${(bp / 100).toLocaleString("es-CO", { maximumFractionDigits: 2 })} %`;
}

export default function AdminOverviewPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  const [data, setData] = useState<AdminOverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (user.role !== "admin") {
      router.replace("/dashboard");
      return;
    }
    withToken((t) => adminApi.overview(t))
      .then(setData)
      .catch((e) => setError(messageOf(e)));
  }, [loading, user, router, withToken]);

  if (loading || !user || user.role !== "admin") return <PageSkeleton shape="list" />;

  // El tramo anterior termina en `previous_end`, que es excluyente: el último
  // día que cuenta es el anterior a ese instante si cae a medianoche.
  const previousLabel = data
    ? `${DAY.format(new Date(data.period.previous_start))} al ${DAY.format(
        new Date(new Date(data.period.previous_end).getTime() - 1),
      )}`
    : "";
  const currentLabel = data
    ? `${DAY.format(new Date(data.period.current_start))} a hoy`
    : "";

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 p-6">
      <header>
        <h1 className="text-xl font-extrabold">Resumen</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">
          {data
            ? `Mes en curso (${currentLabel}) frente al mismo tramo del mes anterior (${previousLabel}), en hora de Bogotá.`
            : "Indicadores del negocio, calculados en el servidor."}
        </p>
      </header>

      {error ? <ErrorBox message={error} /> : null}

      {data ? (
        <>
          <section aria-labelledby="hoy" className="space-y-3">
            <h2 id="hoy" className="text-sm font-bold uppercase tracking-wide text-muted">
              Hoy
            </h2>
            {data.recurring.length === 0 ? (
              <Card>
                <p className="text-sm text-muted">Ingreso recurrente mensual</p>
                <p className="mt-1 text-5xl font-extrabold text-white">
                  {formatMoney(0, "COP")}
                </p>
                <p className="mt-1 text-sm text-muted">Ninguna suscripción vigente que siga.</p>
              </Card>
            ) : (
              data.recurring.map((r) => (
                <Card key={r.currency}>
                  <p className="text-sm text-muted">Ingreso recurrente mensual</p>
                  <p className="mt-1 text-5xl font-extrabold text-white">
                    {formatMoney(r.total_cents, r.currency)}
                  </p>
                  <p className="mt-2 text-sm text-muted">
                    {r.subscriptions} suscripcion{r.subscriptions === 1 ? "" : "es"} vigentes que
                    siguen · renovación automática {formatMoney(r.automatic_cents, r.currency)} ·
                    pago manual {formatMoney(r.manual_cents, r.currency)}
                  </p>
                  <p className="mt-1 text-xs text-muted">
                    Lo que costará el próximo período de cada una, con su descuento, llevado a un
                    mes. Sin las canceladas.
                  </p>
                </Card>
              ))
            )}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <Tile label="Con período vigente" value={data.subscriptions.in_force} />
              <Tile label={SUBSCRIPTION_STATUS_LABEL.active} value={data.subscriptions.active} />
              <Tile label={SUBSCRIPTION_STATUS_LABEL.past_due} value={data.subscriptions.past_due} />
              <Tile label={SUBSCRIPTION_STATUS_LABEL.canceled} value={data.subscriptions.canceled} />
              <Tile label={SUBSCRIPTION_STATUS_LABEL.expired} value={data.subscriptions.expired} />
              <Tile label={SUBSCRIPTION_STATUS_LABEL.pending} value={data.subscriptions.pending} />
            </div>
          </section>

          <section aria-labelledby="mes" className="space-y-3">
            <h2 id="mes" className="text-sm font-bold uppercase tracking-wide text-muted">
              Este mes
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.collected.length === 0 ? (
                <Tile
                  label="Cobrado, neto de reembolsos"
                  value={0}
                  delta={{ current: 0, previous: 0 }}
                  direction="up_is_good"
                  format={(n) => formatMoney(n, "COP")}
                />
              ) : (
                data.collected.map((c) => (
                  <Tile
                    key={c.currency}
                    label="Cobrado, neto de reembolsos"
                    value={c.current_cents}
                    delta={{ current: c.current_cents, previous: c.previous_cents }}
                    direction="up_is_good"
                    format={(n) => formatMoney(n, c.currency)}
                  />
                ))
              )}
              <Tile
                label="Altas"
                value={data.new_subscriptions.current}
                delta={data.new_subscriptions}
                direction="up_is_good"
              />
              <Tile
                label="Cancelaciones"
                value={data.cancellations.current}
                delta={data.cancellations}
                direction="up_is_bad"
                note={`Tasa de cancelación: ${formatRate(data.cancellation_rate.current_bp)} (mes anterior: ${formatRate(data.cancellation_rate.previous_bp)})`}
              />
              <Tile
                label="Cobros fallidos"
                value={data.failed_charges.current}
                delta={data.failed_charges}
                direction="up_is_bad"
              />
              <Tile
                label="Registros nuevos"
                value={data.registrations.current}
                delta={data.registrations}
                direction="up_is_good"
              />
              <Tile
                label="De ellos, con el correo confirmado"
                value={data.verified_registrations.current}
                delta={data.verified_registrations}
                direction="up_is_good"
              />
            </div>
            <p className="text-xs text-muted">
              La tasa de cancelación es lo cancelado en el mes sobre las suscripciones con un período
              pagado al empezarlo, según sus pagos aprobados. Una cuenta eliminada ya no cuenta en
              los registros.
            </p>
          </section>
        </>
      ) : null}
    </main>
  );
}

function Tile({
  label,
  value,
  delta,
  direction = "neutral",
  format = (n) => n.toLocaleString("es-CO"),
  note,
}: {
  label: string;
  value: number;
  delta?: Comparison;
  direction?: Direction;
  format?: (n: number) => string;
  note?: string;
}) {
  return (
    <Card>
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-3xl font-extrabold text-white">{format(value)}</p>
      {delta ? <Delta delta={delta} direction={direction} format={format} /> : null}
      {note ? <p className="mt-1 text-xs text-muted">{note}</p> : null}
    </Card>
  );
}

function Delta({
  delta,
  direction,
  format,
}: {
  delta: Comparison;
  direction: Direction;
  format: (n: number) => string;
}) {
  const diff = delta.current - delta.previous;
  // Flecha y signo además del color: la variación no se lee solo por el color.
  const arrow = diff > 0 ? "▲" : diff < 0 ? "▼" : "=";
  const good =
    diff === 0 || direction === "neutral" ? null : (diff > 0) === (direction === "up_is_good");
  const tone = good === null ? "text-muted" : good ? "text-signal-strong" : "text-table-red";
  const signed = diff > 0 ? `+${format(diff)}` : diff < 0 ? `−${format(-diff)}` : "sin cambio";
  return (
    <p className="mt-1 text-sm">
      <span className={`font-bold ${tone}`}>
        <span aria-hidden="true">{arrow} </span>
        {signed}
      </span>{" "}
      <span className="text-muted">frente a {format(delta.previous)} el mes anterior</span>
    </p>
  );
}
