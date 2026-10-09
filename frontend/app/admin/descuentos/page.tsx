"use client";

/**
 * Admin: cupones de descuento (§4.5 de la Fase 4). Crear, editar, activar y
 * desactivar, y ver quién usó cada uno.
 *
 * Un cupón no se borra: se desactiva. Con redenciones, su descuento ya no se
 * puede cambiar. Todo cambio pide un motivo y queda en la bitácora. Ningún
 * código promete resultados: el servidor rechaza los que lo hacen.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Pager } from "@/components/admin/Pager";
import { SelectField } from "@/components/admin/SelectField";
import { SuccessBox } from "@/components/AuthShell";
import { Badge, Button, Card, CardHeader, Checkbox, ErrorBox, Field } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import { formatDateTime } from "@/lib/admin";
import { centsToInput, formatMoney, parseMoneyToCents } from "@/lib/money";
import { useSession } from "@/lib/session";
import type {
  AdminCouponListResponse,
  AdminCouponResponse,
  AdminPlanResponse,
  CouponDuration,
  CouponKind,
  CouponRedemptionListResponse,
  UpdateCouponRequest,
} from "@/lib/types/billing";

const PAGE_SIZE = 25;

type ActiveFilter = "" | "true" | "false";

const KINDS: readonly (readonly [CouponKind, string])[] = [
  ["percent", "Porcentaje"],
  ["fixed_cents", "Monto fijo (COP)"],
];

const DURATIONS: readonly (readonly [CouponDuration, string])[] = [
  ["once", "Solo el primer cobro"],
  ["repeating", "Varios cobros"],
  ["forever", "Todos los cobros"],
];

const ACTIVE_OPTIONS: readonly (readonly [ActiveFilter, string])[] = [
  ["", "Todos"],
  ["true", "Activos"],
  ["false", "Desactivados"],
];

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

/** La fecha local (AAAA-MM-DD) de un instante, para un campo de fecha. */
function localDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function discountLabel(c: AdminCouponResponse): string {
  const amount =
    c.kind === "percent" ? `${c.value} %` : formatMoney(c.value, c.currency ?? "COP");
  const duration =
    c.duration === "once"
      ? "en el primer cobro"
      : c.duration === "forever"
        ? "en todos los cobros"
        : `en ${c.duration_periods} cobros`;
  return `${amount} ${duration}`;
}

interface CouponDraft {
  code: string;
  kind: CouponKind;
  value: string;
  duration: CouponDuration;
  durationPeriods: string;
  maxRedemptions: string;
  validFrom: string;
  validUntil: string;
  planIds: string[];
}

const EMPTY: CouponDraft = {
  code: "",
  kind: "percent",
  value: "",
  duration: "once",
  durationPeriods: "",
  maxRedemptions: "",
  validFrom: "",
  validUntil: "",
  planIds: [],
};

function draftOf(c: AdminCouponResponse): CouponDraft {
  return {
    code: c.code,
    kind: c.kind,
    value: c.kind === "percent" ? String(c.value) : centsToInput(c.value),
    duration: c.duration,
    durationPeriods: c.duration_periods === null ? "" : String(c.duration_periods),
    maxRedemptions: c.max_redemptions === null ? "" : String(c.max_redemptions),
    validFrom: localDate(c.valid_from),
    validUntil: localDate(c.valid_until),
    planIds: [...c.plan_ids].sort(),
  };
}

/** Lo que el formulario manda a la API, o el error que impide mandarlo. */
function fieldsOf(draft: CouponDraft) {
  let value: number | null;
  if (draft.kind === "percent") {
    value = /^\d{1,2}$/.test(draft.value.trim()) ? Number(draft.value) : null;
    if (value === null || value < 1) return { error: "El porcentaje va de 1 a 99" };
  } else {
    value = parseMoneyToCents(draft.value);
    if (value === null) return { error: "El monto debe ser mayor que cero" };
  }
  return {
    fields: {
      kind: draft.kind,
      value,
      currency: draft.kind === "fixed_cents" ? ("COP" as const) : null,
      duration: draft.duration,
      duration_periods: draft.duration === "repeating" ? Number(draft.durationPeriods) : null,
      max_redemptions: draft.maxRedemptions.trim() ? Number(draft.maxRedemptions) : null,
      // El día de inicio cuenta desde su primer minuto; el de vencimiento, hasta el último.
      valid_from: draft.validFrom ? new Date(`${draft.validFrom}T00:00:00`).toISOString() : null,
      valid_until: draft.validUntil
        ? new Date(`${draft.validUntil}T23:59:59`).toISOString()
        : null,
      plan_ids: [...draft.planIds].sort(),
    },
  };
}

export default function AdminCouponsPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  const [page, setPage] = useState<AdminCouponListResponse | null>(null);
  const [plans, setPlans] = useState<AdminPlanResponse[]>([]);
  // `draft` es lo que hay escrito en el buscador; `filters`, lo que se buscó.
  const [draft, setDraft] = useState<{ query: string; active: ActiveFilter }>({
    query: "",
    active: "",
  });
  const [filters, setFilters] = useState(draft);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isAdmin = user?.role === "admin";

  const refresh = useCallback(async () => {
    setPage(
      await withToken((t) =>
        adminApi.listCoupons(t, {
          query: filters.query.trim() || undefined,
          active: filters.active === "" ? undefined : filters.active === "true",
          limit: PAGE_SIZE,
          offset,
        }),
      ),
    );
  }, [withToken, filters, offset]);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (!isAdmin) {
      router.replace("/dashboard");
      return;
    }
    refresh().catch((e) => setError(messageOf(e)));
  }, [loading, user, isAdmin, router, refresh]);

  useEffect(() => {
    if (loading || !isAdmin) return;
    withToken((t) => adminApi.listPlans(t))
      .then((r) => setPlans(r.items))
      .catch((e) => setError(messageOf(e)));
  }, [loading, isAdmin, withToken]);

  if (loading || !user || !isAdmin) return null;

  function handleSearch(event: React.FormEvent) {
    event.preventDefault();
    setOffset(0);
    setSelected(null);
    setFilters(draft);
  }

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">Descuentos</h1>
          <p className="mt-1 max-w-prose text-sm text-muted">
            Cupones para la suscripción. Un cupón no se borra: se desactiva. Todo cambio pide un
            motivo y queda en la bitácora.
          </p>
        </div>
        <Button variant="ghost" onClick={() => router.push("/admin")}>
          Volver al panel
        </Button>
      </header>

      {error ? <ErrorBox message={error} /> : null}

      <Card>
        <CardHeader
          title="Nuevo cupón"
          subtitle="El código lo ve el cliente: no puede prometer resultados. Un cupón nunca deja el total en cero; una cortesía total se da como acceso invitado desde Usuarios."
        />
        <CouponForm plans={plans} onDone={refresh} />
      </Card>

      <Card>
        <CardHeader title="Cupones" />
        <form onSubmit={handleSearch} className="grid gap-4 sm:grid-cols-[1fr_12rem_auto]">
          <Field
            label="Buscar por código"
            value={draft.query}
            onChange={(e) => setDraft((d) => ({ ...d, query: e.target.value }))}
          />
          <SelectField
            label="Estado"
            value={draft.active}
            options={ACTIVE_OPTIONS}
            onChange={(v) => setDraft((d) => ({ ...d, active: v }))}
          />
          <div className="flex items-end">
            <Button type="submit">Buscar</Button>
          </div>
        </form>

        {page ? (
          <>
            {page.items.length === 0 ? (
              <p className="mt-4 text-sm text-muted">No hay cupones con ese filtro.</p>
            ) : (
              <ul className="mt-4 divide-y divide-edge">
                {page.items.map((c) => (
                  <li key={c.id} className="py-3" data-testid={`cupon-${c.code}`}>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="break-words font-bold text-white">{c.code}</p>
                        <p className="text-xs text-muted">
                          {discountLabel(c)} · Usos: {c.redemptions_count}
                          {c.max_redemptions === null ? "" : ` de ${c.max_redemptions}`}
                          {c.valid_until ? ` · Vence el ${localDate(c.valid_until)}` : ""}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={c.active ? "ok" : "off"}>
                          {c.active ? "Activo" : "Desactivado"}
                        </Badge>
                        <Button
                          variant="ghost"
                          aria-expanded={selected === c.id}
                          onClick={() => setSelected(selected === c.id ? null : c.id)}
                        >
                          {selected === c.id ? "Cerrar" : "Ver"}
                        </Button>
                      </div>
                    </div>
                    {selected === c.id ? (
                      <div className="mt-4 space-y-5 rounded-lg border border-edge bg-ink p-4">
                        <CouponForm coupon={c} plans={plans} onDone={refresh} />
                        <Redemptions couponId={c.id} />
                      </div>
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
              onChange={setOffset}
            />
          </>
        ) : null}
      </Card>
    </main>
  );
}

/** Crea un cupón o, si recibe uno, lo edita y lo activa o desactiva. */
function CouponForm({
  coupon,
  plans,
  onDone,
}: {
  coupon?: AdminCouponResponse;
  plans: AdminPlanResponse[];
  onDone: () => Promise<void>;
}) {
  const { withToken } = useSession();
  const [draft, setDraft] = useState<CouponDraft>(coupon ? draftOf(coupon) : EMPTY);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  // Con redenciones el descuento ya no cambia: el servidor lo rechaza.
  const used = !!coupon && coupon.redemptions_count > 0;

  function set<K extends keyof CouponDraft>(key: K, value: CouponDraft[K]) {
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
      if (!coupon) setDraft(EMPTY);
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
    if (!coupon) {
      void run(
        () =>
          withToken((t) =>
            adminApi.createCoupon(t, { ...fields, code: draft.code, active: true, reason }),
          ),
        "Cupón creado",
      );
      return;
    }
    // Solo viaja lo que cambió: una fecha que no se tocó no pierde su hora.
    const before = draftOf(coupon);
    const body: UpdateCouponRequest = { reason };
    if (draft.kind !== before.kind || draft.value !== before.value) {
      body.kind = fields.kind;
      body.value = fields.value;
      body.currency = fields.currency;
    }
    if (draft.duration !== before.duration || draft.durationPeriods !== before.durationPeriods) {
      body.duration = fields.duration;
      body.duration_periods = fields.duration_periods;
    }
    if (draft.maxRedemptions !== before.maxRedemptions) {
      body.max_redemptions = fields.max_redemptions;
    }
    if (draft.validFrom !== before.validFrom) {
      if (!fields.valid_from) {
        setError("El inicio de la vigencia no puede quedar vacío");
        return;
      }
      body.valid_from = fields.valid_from;
    }
    if (draft.validUntil !== before.validUntil) body.valid_until = fields.valid_until;
    if (fields.plan_ids.join() !== before.planIds.join()) body.plan_ids = fields.plan_ids;
    void run(
      () => withToken((t) => adminApi.updateCoupon(t, coupon.id, body)),
      "Cupón actualizado",
    );
  }

  function handleToggle() {
    if (!coupon) return;
    void run(
      () =>
        withToken((t) => adminApi.updateCoupon(t, coupon.id, { active: !coupon.active, reason })),
      coupon.active ? "Cupón desactivado" : "Cupón activado",
    );
  }

  function togglePlan(planId: string, checked: boolean) {
    set(
      "planIds",
      checked ? [...draft.planIds, planId].sort() : draft.planIds.filter((id) => id !== planId),
    );
  }

  const reasonLabel = coupon ? `Motivo del cambio en ${coupon.code}` : "Motivo de la creación";

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {used ? (
        <p className="text-xs text-muted">
          Este cupón ya se usó: su descuento no se puede cambiar. Para ofrecer otro descuento,
          desactívalo y crea uno nuevo.
        </p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-3">
        {coupon ? null : (
          <Field
            label="Código"
            required
            minLength={3}
            maxLength={40}
            placeholder="BIENVENIDA10"
            hint="Letras sin tilde, números y guiones. Se guarda en mayúsculas y no se puede cambiar."
            value={draft.code}
            onChange={(e) => set("code", e.target.value)}
          />
        )}
        <SelectField
          label="Tipo de descuento"
          value={draft.kind}
          options={KINDS}
          disabled={used}
          onChange={(v) => setDraft((prev) => ({ ...prev, kind: v, value: "" }))}
        />
        <Field
          label={draft.kind === "percent" ? "Porcentaje (1 a 99)" : "Monto del descuento (COP)"}
          required
          disabled={used}
          inputMode="decimal"
          placeholder={draft.kind === "percent" ? "10" : "20000"}
          value={draft.value}
          onChange={(e) => set("value", e.target.value)}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <SelectField
          label="Aplica a"
          value={draft.duration}
          options={DURATIONS}
          disabled={used}
          onChange={(v) => set("duration", v)}
        />
        {draft.duration === "repeating" ? (
          <Field
            label="Cantidad de cobros"
            type="number"
            required
            disabled={used}
            min={1}
            max={120}
            value={draft.durationPeriods}
            onChange={(e) => set("durationPeriods", e.target.value)}
          />
        ) : null}
        <Field
          label="Tope de usos (opcional)"
          type="number"
          min={1}
          hint="Vacío = sin tope."
          value={draft.maxRedemptions}
          onChange={(e) => set("maxRedemptions", e.target.value)}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Vigente desde"
          type="date"
          hint={coupon ? undefined : "Vacío = desde ahora."}
          value={draft.validFrom}
          onChange={(e) => set("validFrom", e.target.value)}
        />
        <Field
          label="Vence el (opcional)"
          type="date"
          hint="Vacío = sin vencimiento."
          value={draft.validUntil}
          onChange={(e) => set("validUntil", e.target.value)}
        />
      </div>

      {plans.length > 0 ? (
        <fieldset>
          <legend className="mb-1.5 text-sm font-bold text-white">Planes a los que aplica</legend>
          <p className="mb-2 text-xs text-muted">Sin marcar ninguno, aplica a todos.</p>
          <div className="space-y-1.5">
            {plans.map((p) => (
              <Checkbox
                key={p.id}
                checked={draft.planIds.includes(p.id)}
                onChange={(e) => togglePlan(p.id, e.target.checked)}
              >
                {p.name} <span className="text-muted">· {p.code}</span>
              </Checkbox>
            ))}
          </div>
        </fieldset>
      ) : null}

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
          {pending ? "Guardando…" : coupon ? "Guardar cambios" : "Crear cupón"}
        </Button>
        {coupon ? (
          <Button
            type="button"
            variant={coupon.active ? "danger" : "ghost"}
            disabled={pending || reason.trim().length < 3}
            onClick={handleToggle}
          >
            {coupon.active ? "Desactivar cupón" : "Activar cupón"}
          </Button>
        ) : null}
      </div>
    </form>
  );
}

/** Quién usó el cupón. Las redenciones las escribe el pago (paso 5). */
function Redemptions({ couponId }: { couponId: string }) {
  const { withToken } = useSession();
  const [page, setPage] = useState<CouponRedemptionListResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    withToken((t) => adminApi.couponRedemptions(t, couponId, { limit: PAGE_SIZE, offset }))
      .then(setPage)
      .catch((e) => setError(messageOf(e)));
  }, [withToken, couponId, offset]);

  return (
    <section>
      <h3 className="mb-2 text-sm font-bold text-white">Redenciones</h3>
      {error ? <ErrorBox message={error} /> : null}
      {page ? (
        page.items.length === 0 ? (
          <p className="text-sm text-muted">Nadie ha usado este cupón.</p>
        ) : (
          <>
            <ul className="space-y-1.5 text-xs text-muted">
              {page.items.map((r) => (
                <li key={r.id} className="break-words">
                  <span className="font-bold text-white">{r.user_email}</span> ·{" "}
                  {formatDateTime(r.created_at)}
                  {r.subscription_id ? ` · suscripción ${r.subscription_id}` : ""}
                </li>
              ))}
            </ul>
            <Pager
              total={page.total}
              offset={page.offset}
              count={page.items.length}
              pageSize={PAGE_SIZE}
              onChange={setOffset}
            />
          </>
        )
      ) : null}
    </section>
  );
}
