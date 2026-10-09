"use client";

/**
 * Admin: planes (§4.4 de la Fase 4). Crear, editar, activar y desactivar.
 *
 * Un plan no se borra: se desactiva y deja de ofrecerse. Todo cambio pide un
 * motivo y queda en la bitácora. La selección de juegos incluidos llega con el
 * paso 7.
 *
 * Los montos se escriben en unidades de la moneda (100000) y viajan en
 * centavos.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { SelectField } from "@/components/admin/SelectField";
import { SuccessBox } from "@/components/AuthShell";
import { Badge, Button, Card, CardHeader, ErrorBox, Field } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import { centsToInput, formatMoney, intervalLabel, parseMoneyToCents } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { AdminPlanResponse, PlanInterval } from "@/lib/types/billing";

const INTERVALS: readonly (readonly [PlanInterval, string])[] = [
  ["month", "Mes"],
  ["year", "Año"],
];

const TEXTAREA_CLASS =
  "w-full rounded-lg border border-edge bg-ink-sunken px-3.5 py-2.5 text-sm text-white outline-none placeholder:text-muted/70 focus:border-gold/60";

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

interface PlanDraft {
  code: string;
  name: string;
  description: string;
  price: string;
  interval: PlanInterval;
  intervalCount: string;
  sortOrder: string;
}

const EMPTY: PlanDraft = {
  code: "",
  name: "",
  description: "",
  price: "",
  interval: "month",
  intervalCount: "1",
  sortOrder: "0",
};

function draftOf(plan: AdminPlanResponse): PlanDraft {
  return {
    code: plan.code,
    name: plan.name,
    description: plan.description,
    price: centsToInput(plan.price_cents),
    interval: plan.interval,
    intervalCount: String(plan.interval_count),
    sortOrder: String(plan.sort_order),
  };
}

/** Lo que el formulario manda a la API, o el error que impide mandarlo. */
function fieldsOf(draft: PlanDraft) {
  const priceCents = parseMoneyToCents(draft.price);
  if (priceCents === null) return { error: "El precio debe ser un monto mayor que cero" };
  return {
    fields: {
      name: draft.name,
      description: draft.description,
      price_cents: priceCents,
      interval: draft.interval,
      interval_count: Number(draft.intervalCount),
      sort_order: Number(draft.sortOrder),
    },
  };
}

export default function AdminPlansPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  const [plans, setPlans] = useState<AdminPlanResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setPlans((await withToken((t) => adminApi.listPlans(t))).items);
  }, [withToken]);

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
    refresh().catch((e) => setError(messageOf(e)));
  }, [loading, user, router, refresh]);

  if (loading || !user || user.role !== "admin") return null;

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">Planes</h1>
          <p className="mt-1 max-w-prose text-sm text-muted">
            Lo que se ofrece en la página de planes. Un plan no se borra: se desactiva. Todo
            cambio pide un motivo y queda en la bitácora.
          </p>
        </div>
        <Button variant="ghost" onClick={() => router.push("/admin")}>
          Volver al panel
        </Button>
      </header>

      {error ? <ErrorBox message={error} /> : null}

      <Card>
        <CardHeader
          title="Nuevo plan"
          subtitle="El nombre y la descripción los ve el cliente: describen el servicio, sin promesas de resultados ni de ventaja."
        />
        <PlanForm onDone={refresh} />
      </Card>

      {plans ? (
        <Card>
          <CardHeader title="Planes" />
          {plans.length === 0 ? (
            <p className="text-sm text-muted">Todavía no hay planes.</p>
          ) : (
            <ul className="divide-y divide-edge">
              {plans.map((plan) => (
                <li key={plan.id} className="py-3" data-testid={`plan-${plan.code}`}>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="break-words font-bold text-white">
                        {plan.name} <span className="font-normal text-muted">· {plan.code}</span>
                      </p>
                      <p className="text-xs text-muted">
                        Se cobra {formatMoney(plan.price_cents, plan.currency)} /{" "}
                        {intervalLabel(plan.interval, plan.interval_count)}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={plan.active ? "ok" : "off"}>
                        {plan.active ? "Activo" : "Desactivado"}
                      </Badge>
                      <Button
                        variant="ghost"
                        aria-expanded={selected === plan.id}
                        onClick={() => setSelected(selected === plan.id ? null : plan.id)}
                      >
                        {selected === plan.id ? "Cerrar" : "Editar"}
                      </Button>
                    </div>
                  </div>
                  {selected === plan.id ? (
                    <div className="mt-4 rounded-lg border border-edge bg-ink p-4">
                      <PlanForm plan={plan} onDone={refresh} />
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : null}
    </main>
  );
}

/** Crea un plan o, si recibe uno, lo edita y lo activa o desactiva. */
function PlanForm({ plan, onDone }: { plan?: AdminPlanResponse; onDone: () => Promise<void> }) {
  const { withToken } = useSession();
  const [draft, setDraft] = useState<PlanDraft>(plan ? draftOf(plan) : EMPTY);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  function set<K extends keyof PlanDraft>(key: K, value: PlanDraft[K]) {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  async function run(action: () => Promise<unknown>, done: string) {
    setPending(true);
    setError(null);
    setSaved(null);
    try {
      await action();
      setReason("");
      setSaved(done);
      if (!plan) setDraft(EMPTY);
      await onDone();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const parsed = fieldsOf(draft);
    if (!parsed.fields) {
      setError(parsed.error);
      return;
    }
    const fields = parsed.fields;
    if (plan) {
      void run(
        () => withToken((t) => adminApi.updatePlan(t, plan.id, { ...fields, reason })),
        "Plan actualizado",
      );
    } else {
      void run(
        () =>
          withToken((t) =>
            adminApi.createPlan(t, {
              ...fields,
              code: draft.code.trim(),
              currency: "COP",
              active: true,
              reason,
            }),
          ),
        "Plan creado",
      );
    }
  }

  function handleToggle() {
    if (!plan) return;
    void run(
      () => withToken((t) => adminApi.updatePlan(t, plan.id, { active: !plan.active, reason })),
      plan.active ? "Plan desactivado" : "Plan activado",
    );
  }

  const reasonLabel = plan ? `Motivo del cambio en ${plan.code}` : "Motivo de la creación";

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {plan ? null : (
          <Field
            label="Código"
            required
            pattern="[a-z0-9][a-z0-9_\-]{1,49}"
            placeholder="trimestral"
            hint="Identificador estable, en minúsculas. No se puede cambiar después."
            value={draft.code}
            onChange={(e) => set("code", e.target.value)}
          />
        )}
        <Field
          label="Nombre"
          required
          maxLength={100}
          value={draft.name}
          onChange={(e) => set("name", e.target.value)}
        />
      </div>

      <label className="block">
        <span className="mb-1.5 block text-sm font-bold text-white">Descripción</span>
        <textarea
          required
          rows={4}
          maxLength={2000}
          value={draft.description}
          onChange={(e) => set("description", e.target.value)}
          className={TEXTAREA_CLASS}
        />
      </label>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field
          label="Precio que se cobra (COP)"
          required
          inputMode="decimal"
          placeholder="100000"
          hint={
            plan
              ? "Un precio nuevo aplica solo a suscripciones nuevas: las vigentes conservan el suyo."
              : "En pesos, sin puntos de miles. Es el único monto que se cobra."
          }
          value={draft.price}
          onChange={(e) => set("price", e.target.value)}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <SelectField
          label="Se cobra cada"
          value={draft.interval}
          options={INTERVALS}
          onChange={(v) => set("interval", v)}
        />
        <Field
          label="Cantidad de períodos"
          type="number"
          required
          min={1}
          max={36}
          hint="1 = cada mes; 3 = trimestral."
          value={draft.intervalCount}
          onChange={(e) => set("intervalCount", e.target.value)}
        />
        <Field
          label="Orden en la página"
          type="number"
          required
          min={0}
          max={10000}
          hint="El menor va primero."
          value={draft.sortOrder}
          onChange={(e) => set("sortOrder", e.target.value)}
        />
      </div>

      <Field
        label={reasonLabel}
        required
        minLength={3}
        maxLength={500}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />

      {error ? <ErrorBox message={error} /> : null}
      {saved ? <SuccessBox message={saved} /> : null}

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Guardando…" : plan ? "Guardar cambios" : "Crear plan"}
        </Button>
        {plan ? (
          <Button
            type="button"
            variant={plan.active ? "danger" : "ghost"}
            disabled={pending || reason.trim().length < 3}
            onClick={handleToggle}
          >
            {plan.active ? "Desactivar plan" : "Activar plan"}
          </Button>
        ) : null}
      </div>
    </form>
  );
}
