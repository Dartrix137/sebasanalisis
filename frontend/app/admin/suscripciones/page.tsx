"use client";

/**
 * Admin: suscripciones (§4.3 de la Fase 4). Lista paginada con filtros en el
 * servidor (estado, plan, modo y correo), el detalle de cada una con sus pagos
 * y su bitácora, y las acciones: extender, cancelar al final del período y
 * cancelar de inmediato. Cada acción pide un motivo y queda en la bitácora.
 *
 * El estado es el de la base: lo pone el job de renovaciones cada hora. Si el
 * período pagado sigue vigente lo dice el servidor con su reloj (`in_force`).
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Pager } from "@/components/admin/Pager";
import { SelectField } from "@/components/admin/SelectField";
import { SubscriptionActions } from "@/components/admin/SubscriptionActions";
import { Badge, Button, Card, ErrorBox, Field } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import { actionLabel, describeChange, formatDateTime } from "@/lib/admin";
import {
  PAYMENT_STATUS_LABEL,
  PAYMENT_STATUS_TONE,
  RENEWAL_MODE_LABEL,
  SUBSCRIPTION_STATUS_LABEL,
  sourceLabel,
} from "@/lib/billing";
import { formatLegalDate } from "@/lib/legal";
import { formatMoney, intervalLabel } from "@/lib/money";
import { useSession } from "@/lib/session";
import type {
  AdminSubscriptionDetailResponse,
  AdminSubscriptionListResponse,
} from "@/lib/types/admin";
import type { AdminPlanResponse, RenewalMode, SubscriptionStatus } from "@/lib/types/billing";

const PAGE_SIZE = 25;

interface Filters {
  query: string;
  status: "" | SubscriptionStatus;
  planId: string;
  renewalMode: "" | RenewalMode;
}

const NO_FILTERS: Filters = { query: "", status: "", planId: "", renewalMode: "" };

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

export default function AdminSubscriptionsPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  // `draft` es lo que hay escrito en el formulario; `filters`, lo que se buscó.
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AdminSubscriptionListResponse | null>(null);
  const [plans, setPlans] = useState<AdminPlanResponse[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Una respuesta que llega después de que se pidió otra se descarta.
  const lastRequest = useRef(0);

  const load = useCallback(async () => {
    const request = ++lastRequest.current;
    const result = await withToken((t) =>
      adminApi.listSubscriptions(t, {
        query: filters.query.trim() || undefined,
        status: filters.status || undefined,
        planId: filters.planId || undefined,
        renewalMode: filters.renewalMode || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    );
    if (request === lastRequest.current) setPage(result);
  }, [withToken, filters, offset]);

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
    load().catch((e) => setError(messageOf(e)));
  }, [loading, user, router, load]);

  useEffect(() => {
    if (loading || user?.role !== "admin") return;
    withToken((t) => adminApi.listPlans(t))
      .then((r) => setPlans(r.items))
      .catch((e) => setError(messageOf(e)));
  }, [loading, user, withToken]);

  if (loading || !user || user.role !== "admin") return null;

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">Suscripciones</h1>
          <p className="mt-1 max-w-prose text-sm text-muted">
            Lo que cada cuenta pagó y hasta cuándo. Extender o cancelar pide un motivo, queda en la
            bitácora y le llega un correo al cliente.
          </p>
        </div>
      </header>

      <Card>
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            setSelected(null);
            setOffset(0);
            setFilters(draft);
          }}
        >
          <div className="sm:col-span-2 lg:col-span-4">
            <Field
              label="Buscar por correo"
              type="search"
              value={draft.query}
              onChange={(e) => setDraft({ ...draft, query: e.target.value })}
            />
          </div>
          <SelectField
            label="Estado"
            value={draft.status}
            onChange={(v) => setDraft({ ...draft, status: v })}
            options={[
              ["", "Todas menos sin completar"],
              ["active", SUBSCRIPTION_STATUS_LABEL.active],
              ["past_due", SUBSCRIPTION_STATUS_LABEL.past_due],
              ["canceled", SUBSCRIPTION_STATUS_LABEL.canceled],
              ["expired", SUBSCRIPTION_STATUS_LABEL.expired],
              ["pending", SUBSCRIPTION_STATUS_LABEL.pending],
            ]}
          />
          <SelectField
            label="Plan"
            value={draft.planId}
            onChange={(v) => setDraft({ ...draft, planId: v })}
            options={[["", "Todos"], ...plans.map((p) => [p.id, p.name] as const)]}
          />
          <SelectField
            label="Modo"
            value={draft.renewalMode}
            onChange={(v) => setDraft({ ...draft, renewalMode: v })}
            options={[
              ["", "Todos"],
              ["automatic", "Renovación automática"],
              ["manual", "Pago manual"],
            ]}
          />
          <div className="flex items-end">
            <Button type="submit" className="w-full">
              Buscar
            </Button>
          </div>
        </form>
      </Card>

      {error ? <ErrorBox message={error} /> : null}

      {page ? (
        <Card>
          {page.items.length === 0 ? (
            <p className="text-sm text-muted">Ninguna suscripción coincide con la búsqueda.</p>
          ) : (
            <ul className="space-y-2">
              {page.items.map((s) => (
                <li key={s.id} className="rounded-lg border border-edge bg-ink">
                  <div className="flex flex-wrap items-center justify-between gap-3 px-3.5 py-3">
                    <div className="min-w-0 text-sm">
                      <p className="truncate font-bold text-white">{s.user_email}</p>
                      <p className="text-xs text-muted">
                        {s.plan.name}
                        {s.current_period_end
                          ? ` · ${s.in_force ? "hasta el" : "venció el"} ${formatLegalDate(s.current_period_end)}`
                          : ""}
                        {" · "}
                        {s.renewal_mode === "automatic" ? "automática" : "manual"}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={s.in_force ? "ok" : "off"}>
                        {SUBSCRIPTION_STATUS_LABEL[s.status]}
                      </Badge>
                      <Button
                        variant="ghost"
                        aria-expanded={selected === s.id}
                        onClick={() => setSelected(selected === s.id ? null : s.id)}
                      >
                        {selected === s.id ? "Cerrar" : "Ver"}
                      </Button>
                    </div>
                  </div>
                  {selected === s.id ? (
                    <SubscriptionDetail
                      subscriptionId={s.id}
                      onChanged={() => load().catch((e) => setError(messageOf(e)))}
                    />
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          <Pager
            total={page.total}
            offset={page.offset}
            count={page.items.length}
            pageSize={PAGE_SIZE}
            onChange={(next) => {
              setSelected(null);
              setOffset(next);
            }}
          />
        </Card>
      ) : null}
    </main>
  );
}

function SubscriptionDetail({
  subscriptionId,
  onChanged,
}: {
  subscriptionId: string;
  onChanged: () => void;
}) {
  const { withToken } = useSession();
  const [detail, setDetail] = useState<AdminSubscriptionDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setDetail(await withToken((t) => adminApi.getSubscription(t, subscriptionId)));
  }, [withToken, subscriptionId]);

  useEffect(() => {
    load().catch((e) => setError(messageOf(e)));
  }, [load]);

  if (error) {
    return (
      <div className="border-t border-edge p-3.5">
        <ErrorBox message={error} />
      </div>
    );
  }
  if (!detail) return null;
  const s = detail.subscription;
  const source = sourceLabel(s);

  async function refresh() {
    await load();
    onChanged();
  }

  return (
    <div className="space-y-5 border-t border-edge p-3.5">
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <Data label="Estado" value={`${SUBSCRIPTION_STATUS_LABEL[s.status]}${s.in_force ? ", vigente" : ", sin período vigente"}`} />
        <Data label="Modo" value={RENEWAL_MODE_LABEL[s.renewal_mode]} />
        <Data
          label="Precio congelado"
          value={`${formatMoney(s.price_cents, s.currency)} / ${intervalLabel(s.plan.interval, s.plan.interval_count)}`}
        />
        <Data
          label="Período"
          value={
            s.current_period_start && s.current_period_end
              ? `Del ${formatLegalDate(s.current_period_start)} al ${formatLegalDate(s.current_period_end)}`
              : "—"
          }
        />
        <Data
          label="Próximo cobro"
          value={
            s.next_charge_at && s.next_charge_cents !== null
              ? `${formatMoney(s.next_charge_cents, s.currency)}, desde el ${formatLegalDate(s.next_charge_at)}`
              : "Ninguno previsto"
          }
        />
        {s.price_change ? (
          <Data
            label="Precio nuevo (ya avisado)"
            value={`${formatMoney(s.price_change.new_price_cents, s.currency)}, desde el ${formatLegalDate(s.price_change.effective_at)}`}
          />
        ) : null}
        <Data label="Medio de pago guardado" value={source ?? "Ninguno"} />
        {s.retry_count > 0 ? (
          <Data label="Intentos fallidos del período" value={String(s.retry_count)} />
        ) : null}
        {s.canceled_at ? <Data label="Cancelada" value={formatDateTime(s.canceled_at)} /> : null}
        <Data label="Creada" value={formatDateTime(s.created_at)} />
      </dl>

      <SubscriptionActions subscription={s} onDone={refresh} />

      <section>
        <h3 className="text-sm font-bold text-white">Pagos de esta suscripción</h3>
        {detail.payments.length === 0 ? (
          <p className="mt-1 text-sm text-muted">Sin pagos.</p>
        ) : (
          <ul className="mt-2 divide-y divide-edge">
            {detail.payments.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span className="text-white">
                  <span className="font-bold">{formatMoney(p.amount_cents, p.currency)}</span> ·{" "}
                  {formatDateTime(p.resolved_at ?? p.created_at)}
                  <span className="block break-all text-xs text-muted">{p.reference}</span>
                </span>
                <Badge tone={PAYMENT_STATUS_TONE[p.status]}>{PAYMENT_STATUS_LABEL[p.status]}</Badge>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted">
          Los eventos de Wompi, reconsultar un pago y registrar un reembolso están en Pagos.
        </p>
      </section>

      <section>
        <h3 className="text-sm font-bold text-white">Historial de acciones sobre esta suscripción</h3>
        {detail.audit.length === 0 ? (
          <p className="mt-1 text-sm text-muted">Sin acciones registradas.</p>
        ) : (
          <ul className="mt-2 space-y-2 text-xs text-muted">
            {detail.audit.map((entry) => (
              <li key={entry.id}>
                <span className="font-bold text-white">{actionLabel(entry)}</span> ·{" "}
                {formatDateTime(entry.created_at)} · {entry.admin_email}
                <br />
                {describeChange(entry.before)} → {describeChange(entry.after)}
                {entry.reason ? (
                  <>
                    <br />
                    Motivo: {entry.reason}
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Data({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="break-words text-white">{value}</dd>
    </div>
  );
}
