"use client";

/**
 * Admin: usuarios (§4.2 de la Fase 4). Lista paginada con búsqueda y filtros
 * en el servidor, detalle de cada cuenta y las acciones de acceso manual.
 *
 * La decisión de acceso que se muestra es la misma que aplica la mesa
 * (`core/access.py`): aquí no se calcula nada. Toda acción pide un motivo y
 * queda en la bitácora.
 *
 * Quedan para el paso 6: reenviar la verificación y forzar el restablecimiento
 * de contraseña. La suscripción y los pagos de cada cuenta se ven aquí, de
 * solo lectura; las acciones sobre ellos llegan con la entrega 3 del paso 5.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Pager } from "@/components/admin/Pager";
import { SuccessBox } from "@/components/AuthShell";
import { Badge, Button, Card, CardHeader, ErrorBox, Field } from "@/components/ui";
import { ApiError, adminApi } from "@/lib/api-client";
import {
  ACCESS_REASON_LABEL,
  ACCESS_TYPE_LABEL,
  actionLabel,
  describeChange,
  formatDateTime,
} from "@/lib/admin";
import { UserBilling } from "@/components/admin/UserBilling";
import { formatLegalDate } from "@/lib/legal";
import { useSession } from "@/lib/session";
import type {
  AdminUserDetailResponse,
  AdminUserListResponse,
  SubscriptionFilter,
} from "@/lib/types/admin";
import type { AccessType, UserResponse, UserRole } from "@/lib/types/auth";

const PAGE_SIZE = 25;

const SELECT_CLASS =
  "w-full rounded-lg border border-edge bg-ink-sunken px-3 py-2.5 text-sm text-white outline-none focus:border-gold/60";

interface Filters {
  query: string;
  accessType: "" | AccessType;
  role: "" | UserRole;
  emailVerified: "" | "true" | "false";
  isActive: "" | "true" | "false";
  subscription: "" | SubscriptionFilter;
}

const NO_FILTERS: Filters = {
  query: "",
  accessType: "",
  role: "",
  emailVerified: "",
  isActive: "",
  subscription: "",
};

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

function toBool(value: "" | "true" | "false"): boolean | undefined {
  return value === "" ? undefined : value === "true";
}

export default function AdminUsersPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  // `draft` es lo que hay escrito en el formulario; `filters`, lo que se buscó.
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AdminUserListResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Cada búsqueda lleva su número: si una respuesta llega después de que se
  // pidió otra, se descarta. Sin esto, la lista completa del primer render
  // podía llegar tarde y pisar el resultado de una búsqueda ya hecha.
  const lastRequest = useRef(0);

  const load = useCallback(async () => {
    const request = ++lastRequest.current;
    const result = await withToken((t) =>
      adminApi.listUsers(t, {
        query: filters.query.trim() || undefined,
        accessType: filters.accessType || undefined,
        role: filters.role || undefined,
        emailVerified: toBool(filters.emailVerified),
        isActive: toBool(filters.isActive),
        subscription: filters.subscription || undefined,
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

  if (loading || !user || user.role !== "admin") return null;

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">Usuarios</h1>
          <p className="mt-1 max-w-prose text-sm text-muted">
            Cuentas, su acceso a la mesa y las acciones de acceso manual. Cada cambio pide un
            motivo y queda en la bitácora.
          </p>
        </div>
        <Button variant="ghost" onClick={() => router.push("/admin")}>
          Volver al panel
        </Button>
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
              label="Buscar por correo o nombre"
              type="search"
              value={draft.query}
              onChange={(e) => setDraft({ ...draft, query: e.target.value })}
            />
          </div>
          <Select
            label="Acceso manual"
            value={draft.accessType}
            onChange={(v) => setDraft({ ...draft, accessType: v as Filters["accessType"] })}
            options={[
              ["", "Todos"],
              ["none", "Sin acceso manual"],
              ["invited", "Invitado"],
              ["full", "Completo"],
            ]}
          />
          <Select
            label="Suscripción"
            value={draft.subscription}
            onChange={(v) => setDraft({ ...draft, subscription: v as Filters["subscription"] })}
            options={[
              ["", "Todas"],
              ["in_force", "Vigente"],
              ["lapsed", "Vencida"],
              ["pending", "Pago sin completar"],
              ["none", "Nunca abrió un pago"],
            ]}
          />
          <Select
            label="Estado"
            value={draft.isActive}
            onChange={(v) => setDraft({ ...draft, isActive: v as Filters["isActive"] })}
            options={[
              ["", "Todas"],
              ["true", "Activas"],
              ["false", "Suspendidas"],
            ]}
          />
          <Select
            label="Correo"
            value={draft.emailVerified}
            onChange={(v) => setDraft({ ...draft, emailVerified: v as Filters["emailVerified"] })}
            options={[
              ["", "Todos"],
              ["true", "Confirmado"],
              ["false", "Sin confirmar"],
            ]}
          />
          <Select
            label="Rol"
            value={draft.role}
            onChange={(v) => setDraft({ ...draft, role: v as Filters["role"] })}
            options={[
              ["", "Todos"],
              ["user", "Usuario"],
              ["admin", "Administrador"],
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
            <p className="text-sm text-muted">Ninguna cuenta coincide con la búsqueda.</p>
          ) : (
            <ul className="space-y-2">
              {page.items.map((u) => (
                <li key={u.id} className="rounded-lg border border-edge bg-ink">
                  <div className="flex flex-wrap items-center justify-between gap-3 px-3.5 py-3">
                    <div className="min-w-0 text-sm">
                      <p className="truncate font-bold text-white">{u.email}</p>
                      {u.display_name ? (
                        <p className="truncate text-xs text-muted">{u.display_name}</p>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {u.role === "admin" ? <Badge>admin</Badge> : null}
                      <Badge tone={u.access.granted ? "ok" : "off"}>
                        {ACCESS_REASON_LABEL[u.access.reason]}
                      </Badge>
                      <Button
                        variant="ghost"
                        aria-expanded={selected === u.id}
                        onClick={() => setSelected(selected === u.id ? null : u.id)}
                      >
                        {selected === u.id ? "Cerrar" : "Ver"}
                      </Button>
                    </div>
                  </div>
                  {selected === u.id ? (
                    <UserDetail
                      userId={u.id}
                      isSelf={u.id === user.id}
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

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-bold text-white">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={SELECT_CLASS}>
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

function accessSummary(u: UserResponse): string {
  const label = ACCESS_REASON_LABEL[u.access.reason];
  if (!u.access.until) return label;
  return u.access.granted
    ? `${label}, hasta el ${formatLegalDate(u.access.until)}`
    : `${label} el ${formatLegalDate(u.access.until)}`;
}

function UserDetail({
  userId,
  isSelf,
  onChanged,
}: {
  userId: string;
  isSelf: boolean;
  onChanged: () => void;
}) {
  const { withToken } = useSession();
  const [detail, setDetail] = useState<AdminUserDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setDetail(await withToken((t) => adminApi.getUser(t, userId)));
  }, [withToken, userId]);

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
  const u = detail.user;

  async function refresh() {
    await load();
    onChanged();
  }

  return (
    <div className="space-y-5 border-t border-edge p-3.5">
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <Data label="Acceso a la mesa" value={accessSummary(u)} />
        {u.role === "admin" ? null : (
          <Data label="Acceso manual" value={ACCESS_TYPE_LABEL[u.access_type]} />
        )}
        <Data label="Estado" value={u.is_active ? "Activa" : "Suspendida"} />
        <Data label="Correo" value={u.email_verified ? "Confirmado" : "Sin confirmar"} />
        <Data label="Registrada" value={formatLegalDate(u.created_at)} />
        <Data label="Mesas" value={String(detail.sessions_count)} />
        <Data
          label="Documentos aceptados"
          value={
            detail.consents.length
              ? detail.consents
                  .map((c) => `${c.title} v${c.version}${c.current ? "" : " (anterior)"}`)
                  .join(" · ")
              : "Ninguno"
          }
        />
      </dl>

      {u.role === "admin" ? (
        // Entra por su rol, no por el acceso manual: cambiarlo no tendría efecto.
        <p className="rounded-lg border border-edge p-3.5 text-sm leading-relaxed text-muted">
          <span className="font-bold text-white">Acceso manual: no aplica.</span> Un administrador
          siempre tiene acceso a la mesa por su rol.
        </p>
      ) : (
        <AccessForm user={u} subscribed={detail.subscription?.in_force ?? false} onDone={refresh} />
      )}
      <UserBilling detail={detail} />
      <StatusForm user={u} isSelf={isSelf} onDone={refresh} />
      <RoleForm user={u} isSelf={isSelf} onDone={refresh} />

      <section>
        <h3 className="text-sm font-bold text-white">Historial de acciones sobre esta cuenta</h3>
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

function AccessForm({
  user,
  subscribed,
  onDone,
}: {
  user: UserResponse;
  /** La cuenta tiene una suscripción con el período pagado vigente. */
  subscribed: boolean;
  onDone: () => Promise<void>;
}) {
  const { withToken } = useSession();
  const [accessType, setAccessType] = useState<AccessType>(user.access_type);
  // Fecha local (AAAA-MM-DD). Vacía = sin vencimiento.
  const [expires, setExpires] = useState(user.access_expires_at?.slice(0, 10) ?? "");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const id = `acceso-${user.id}`;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      await withToken((t) =>
        adminApi.updateUserAccess(t, user.id, {
          access_type: accessType,
          // El acceso vale hasta el final de ese día, hora del equipo del admin.
          access_expires_at:
            accessType === "invited" && expires
              ? new Date(`${expires}T23:59:59`).toISOString()
              : null,
          reason,
        }),
      );
      setReason("");
      setSaved(true);
      await onDone();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-edge p-3.5">
      <CardHeader
        title="Acceso manual"
        subtitle="Invitado puede llevar vencimiento. Completo no vence. Sin acceso manual lo retira."
      />
      {subscribed ? (
        // El acceso manual se evalúa antes que la suscripción (`core/access.py`).
        <p
          role="note"
          className="rounded-lg border border-gold/40 bg-gold/10 px-3.5 py-3 text-sm leading-relaxed text-white"
        >
          <span className="font-bold">Esta cuenta tiene una suscripción vigente.</span> El acceso
          manual no la reemplaza ni la cancela. Si le das Invitado o Completo, entra por ese
          acceso y no se le ofrece pagar mientras lo tenga; el período que ya pagó sigue
          corriendo. Dejarla en Sin acceso manual no le quita la mesa: sigue entrando por su
          suscripción. Para sacarla de la mesa, suspende la cuenta.
        </p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block" htmlFor={id}>
          <span className="mb-1.5 block text-sm font-bold text-white">Tipo de acceso</span>
          <select
            id={id}
            value={accessType}
            onChange={(e) => setAccessType(e.target.value as AccessType)}
            className={SELECT_CLASS}
          >
            {(Object.keys(ACCESS_TYPE_LABEL) as AccessType[]).map((a) => (
              <option key={a} value={a}>
                {ACCESS_TYPE_LABEL[a]}
              </option>
            ))}
          </select>
        </label>
        {accessType === "invited" ? (
          <Field
            label="Vence el (opcional)"
            type="date"
            hint="Vacío = sin vencimiento."
            value={expires}
            onChange={(e) => setExpires(e.target.value)}
          />
        ) : null}
      </div>
      <Field
        label="Motivo del cambio de acceso"
        required
        minLength={3}
        maxLength={500}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      {error ? <ErrorBox message={error} /> : null}
      {saved ? <SuccessBox message="Acceso actualizado" /> : null}
      <Button type="submit" disabled={pending}>
        {pending ? "Guardando…" : "Guardar acceso"}
      </Button>
    </form>
  );
}

/** Nombrar administrador o quitar el rol. Es la única forma de tener más de uno. */
function RoleForm({
  user,
  isSelf,
  onDone,
}: {
  user: UserResponse;
  isSelf: boolean;
  onDone: () => Promise<void>;
}) {
  const { withToken } = useSession();
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = user.role === "admin";

  // Nadie cambia su propio rol: así siempre queda al menos un administrador.
  if (isSelf) return null;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await withToken((t) =>
        adminApi.updateUserRole(t, user.id, { role: isAdmin ? "user" : "admin", reason }),
      );
      setReason("");
      await onDone();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-edge p-3.5">
      <CardHeader
        title={isAdmin ? "Quitar el rol de administrador" : "Nombrar administrador"}
        subtitle={
          isAdmin
            ? `Dejará de administrar. Su acceso a la mesa pasará a depender del acceso manual que tiene guardado: ${ACCESS_TYPE_LABEL[user.access_type].toLowerCase()}.`
            : user.is_active
              ? "Podrá gestionar usuarios, juegos y documentos legales, y entrará a la mesa por su rol."
              : "La cuenta está suspendida: reactívala antes de nombrarla administradora."
        }
      />
      {isAdmin || user.is_active ? (
        <>
          <Field
            label={isAdmin ? "Motivo para quitar el rol" : "Motivo del nombramiento"}
            required
            minLength={3}
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          {error ? <ErrorBox message={error} /> : null}
          <Button type="submit" variant={isAdmin ? "danger" : "ghost"} disabled={pending}>
            {pending ? "Un momento…" : isAdmin ? "Quitar rol de administrador" : "Nombrar administrador"}
          </Button>
        </>
      ) : null}
    </form>
  );
}

function StatusForm({
  user,
  isSelf,
  onDone,
}: {
  user: UserResponse;
  isSelf: boolean;
  onDone: () => Promise<void>;
}) {
  const { withToken } = useSession();
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Nadie se suspende a sí mismo: el servidor también lo rechaza.
  if (isSelf) return null;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await withToken((t) =>
        adminApi.updateUserStatus(t, user.id, { is_active: !user.is_active, reason }),
      );
      setReason("");
      await onDone();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-edge p-3.5">
      <CardHeader
        title={user.is_active ? "Suspender la cuenta" : "Reactivar la cuenta"}
        subtitle={
          user.is_active
            ? "Suspendida, la cuenta entra a Mi cuenta pero no a la mesa, tenga el acceso que tenga."
            : "Al reactivarla recupera el acceso que le corresponda."
        }
      />
      <Field
        label={user.is_active ? "Motivo de la suspensión" : "Motivo de la reactivación"}
        required
        minLength={3}
        maxLength={500}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      {error ? <ErrorBox message={error} /> : null}
      <Button type="submit" variant={user.is_active ? "danger" : "primary"} disabled={pending}>
        {pending ? "Un momento…" : user.is_active ? "Suspender cuenta" : "Reactivar cuenta"}
      </Button>
    </form>
  );
}
