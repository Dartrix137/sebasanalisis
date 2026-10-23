"use client";

/**
 * Admin: pagos (§4.3 de la Fase 4). Todos los cobros, también los que no se
 * completaron, con filtros en el servidor; el detalle de cada uno con la cadena
 * de eventos de la pasarela (los de firma inválida incluidos), reconsultar en la
 * pasarela y registrar un reembolso hecho en su panel.
 *
 * `?query=` en la dirección abre la página ya filtrada: así enlaza el detalle
 * de la cuenta en `/admin/usuarios`.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { MobileFilters } from "@/components/admin/MobileFilters";
import { Pager } from "@/components/admin/Pager";
import { PaymentDetail } from "@/components/admin/PaymentDetail";
import { SelectField } from "@/components/admin/SelectField";
import { PageSkeleton } from "@/components/PageSkeleton";
import { Badge, Button, Card, Checkbox, ErrorBox, Field } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import { formatDateTime } from "@/lib/admin";
import { PAYMENT_KIND_LABEL, PAYMENT_STATUS_LABEL, PAYMENT_STATUS_TONE } from "@/lib/billing";
import { formatMoney } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { AdminPaymentListResponse } from "@/lib/types/admin";
import type { PaymentKind, PaymentStatus } from "@/lib/types/billing";

const PAGE_SIZE = 25;

interface Filters {
  query: string;
  status: "" | PaymentStatus;
  kind: "" | PaymentKind;
  reversed: boolean;
  refunded: boolean;
}

const NO_FILTERS: Filters = { query: "", status: "", kind: "", reversed: false, refunded: false };

/** Filtros con un valor distinto del de "todos", sin contar la búsqueda. */
function activeFilters(f: Filters): number {
  return Object.entries(f).filter(([k, v]) => k !== "query" && v !== "" && v !== false)
    .length;
}

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

export default function AdminPaymentsPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  // Null hasta leer la dirección: así la primera búsqueda ya lleva `?query=`.
  const [filters, setFilters] = useState<Filters | null>(null);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AdminPaymentListResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lastRequest = useRef(0);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search).get("query") ?? "";
    const initial = { ...NO_FILTERS, query };
    setDraft(initial);
    setFilters(initial);
  }, []);

  const load = useCallback(async () => {
    if (!filters) return;
    const request = ++lastRequest.current;
    const result = await withToken((t) =>
      adminApi.listPayments(t, {
        query: filters.query.trim() || undefined,
        status: filters.status || undefined,
        kind: filters.kind || undefined,
        reversed: filters.reversed,
        refunded: filters.refunded,
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

  if (loading || !user || user.role !== "admin") return <PageSkeleton shape="list" />;

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 px-4 py-6 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold leading-none">Pagos</h1>
          <p className="mt-1 max-w-prose text-sm text-muted">
            Cada intento de cobro, con lo que respondió la pasarela. Reconsultar un pago usa la
            misma función del webhook. Los reembolsos se hacen en el panel de la pasarela y aquí se
            registran.
          </p>
        </div>
      </header>

      <Card>
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            setSelected(null);
            setOffset(0);
            setFilters(draft);
          }}
        >
          <div className="sm:col-span-2 lg:col-span-3">
            <Field
              label="Buscar por correo, referencia o transacción de la pasarela"
              type="search"
              value={draft.query}
              onChange={(e) => setDraft({ ...draft, query: e.target.value })}
            />
          </div>
          <MobileFilters active={activeFilters(draft)}>
            <SelectField
              label="Estado"
              value={draft.status}
              onChange={(v) => setDraft({ ...draft, status: v })}
              options={[
                ["", "Todos"],
                ["approved", PAYMENT_STATUS_LABEL.approved],
                ["pending", PAYMENT_STATUS_LABEL.pending],
                ["declined", PAYMENT_STATUS_LABEL.declined],
                ["voided", PAYMENT_STATUS_LABEL.voided],
                ["error", PAYMENT_STATUS_LABEL.error],
              ]}
            />
            <SelectField
              label="Tipo"
              value={draft.kind}
              onChange={(v) => setDraft({ ...draft, kind: v })}
              options={[
                ["", "Todos"],
                ["initial", PAYMENT_KIND_LABEL.initial],
                ["renewal", PAYMENT_KIND_LABEL.renewal],
              ]}
            />
            <div className="space-y-2 self-end">
              <Checkbox
                checked={draft.reversed}
                onChange={(e) => setDraft({ ...draft, reversed: e.target.checked })}
              >
                Anulados después de aprobados
              </Checkbox>
              <Checkbox
                checked={draft.refunded}
                onChange={(e) => setDraft({ ...draft, refunded: e.target.checked })}
              >
                Con reembolso registrado
              </Checkbox>
            </div>
          </MobileFilters>
          <div className="flex items-end sm:col-span-2 lg:col-span-3">
            <Button type="submit">Buscar</Button>
          </div>
        </form>
      </Card>

      {error ? <ErrorBox message={error} /> : null}

      {page ? (
        <Card>
          {page.items.length === 0 ? (
            <p className="text-sm text-muted">Ningún pago coincide con la búsqueda.</p>
          ) : (
            <ul className="-my-1 divide-y divide-edge">
              {page.items.map((p) => (
                <li key={p.id}>
                  <div className="relative flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="min-w-0 text-sm">
                      <p className="truncate font-bold text-white">
                        {formatMoney(p.amount_cents, p.currency)} ·{" "}
                        {p.user_email ?? "Cuenta eliminada"}
                      </p>
                      <p className="truncate text-xs text-muted">
                        {formatDateTime(p.created_at)} · {PAYMENT_KIND_LABEL[p.kind]} ·{" "}
                        {p.plan_name}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {p.reversed_at ? <Badge>Anulado después</Badge> : null}
                      {p.refunded_cents > 0 ? <Badge>Con reembolso</Badge> : null}
                      <Badge tone={PAYMENT_STATUS_TONE[p.status]}>
                        {PAYMENT_STATUS_LABEL[p.status]}
                      </Badge>
                      <Button
                        variant="ghost"
                        className="after:absolute after:inset-0 after:rounded-lg after:content-['']"
                        aria-expanded={selected === p.id}
                        onClick={() => setSelected(selected === p.id ? null : p.id)}
                      >
                        {selected === p.id ? "Cerrar" : "Ver"}
                      </Button>
                    </div>
                  </div>
                  {selected === p.id ? (
                    <PaymentDetail
                      paymentId={p.id}
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
