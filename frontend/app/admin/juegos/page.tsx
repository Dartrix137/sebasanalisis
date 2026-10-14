"use client";

/**
 * Admin: juegos y variantes (§4.1 y §7.2 de la Fase 4). Formulario
 * estructurado, sin builder visual. El backtest del motor está en
 * `/admin/motor`. Sin mockup de referencia — el sistema visual se hereda de
 * `docs/design/` (fondo azul-noche, tarjetas, acento dorado).
 *
 * Un juego nace oculto: se publica cuando tiene sus variantes. Cambiar el
 * estado pide un motivo y queda en la bitácora; el slug, el tipo y el módulo
 * no cambian después de creado.
 *
 * Desde el 2026-10-14 el producto sale solo con la ruleta, y cada juego futuro
 * tendrá su propio motor, escrito en código (decisión del usuario): crear un
 * juego desde cero con la configuración a mano no es sencillo de hacer bien.
 * Por eso el alta de juegos y de variantes está oculta (`ALTA_DE_JUEGOS`), no
 * borrada, por si una versión futura la vuelve a abrir. Lo que la ruleta
 * necesita sigue a la vista: editar sus variantes (umbrales de señal) y el
 * estado, el orden, el ícono y la descripción del juego.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Pager } from "@/components/admin/Pager";
import { SelectField } from "@/components/admin/SelectField";
import { VariantForm } from "@/components/admin/VariantForm";
import { Badge, Button, Card, CardHeader, ErrorBox, Field } from "@/components/ui";
import { GAME_ICON_LABEL, GAME_MODULE_LABEL, GAME_STATUS_LABEL } from "@/lib/admin";
import { ApiError, adminApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type {
  GameIcon,
  GameModule,
  GameResponse,
  GameStatus,
  GameVariantResponse,
} from "@/lib/types/games";

type FormError = { message: string; details?: string[] } | null;

const PAGE_SIZE = 20;

// Oculta "Nuevo juego" y "+ Variante" (decisión del 2026-10-14: por ahora solo
// la ruleta). Los endpoints de alta siguen en la API; encenderlo los vuelve a
// mostrar sin más cambios.
const ALTA_DE_JUEGOS = false;

const STATUS_OPTIONS = Object.entries(GAME_STATUS_LABEL) as [GameStatus, string][];
const ICON_OPTIONS = Object.entries(GAME_ICON_LABEL) as [GameIcon, string][];
// `sports` está reservado (§8.2): se lista para que se vea, pero el servidor
// rechaza crear un juego con él.
const MODULE_OPTIONS = Object.entries(GAME_MODULE_LABEL) as [GameModule, string][];

const STATUS_TONE: Record<GameStatus, "ok" | "off" | "neutral"> = {
  active: "ok",
  coming_soon: "neutral",
  hidden: "off",
};

export default function AdminGamesPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();

  const [games, setGames] = useState<GameResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<GameStatus | "">("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<FormError>(null);
  const [pending, setPending] = useState(false);
  const [editing, setEditing] = useState<{ gameId: string; variant?: GameVariantResponse } | null>(
    null,
  );

  const refresh = useCallback(async () => {
    const page = await withToken((t) =>
      adminApi.listGames(t, {
        status: statusFilter || undefined,
        q: query.trim() || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    );
    setGames(page.items);
    setTotal(page.total);
  }, [withToken, statusFilter, query, offset]);

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
    refresh().catch((e) => setError({ message: describe(e) }));
  }, [loading, user, router, refresh]);

  async function run(action: () => Promise<unknown>): Promise<boolean> {
    setPending(true);
    setError(null);
    try {
      await action();
      await refresh();
      setEditing(null);
      return true;
    } catch (e) {
      setError(
        e instanceof ApiError
          ? { message: e.message, details: e.validationErrors }
          : { message: describe(e) },
      );
      return false;
    } finally {
      setPending(false);
    }
  }

  if (loading || !user || user.role !== "admin") return null;

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <header>
        <h1 className="text-xl font-extrabold">Juegos</h1>
        <p className="mt-1 text-sm text-muted">
          Juegos del menú y sus variantes. Formulario estructurado, sin builder visual.
        </p>
      </header>

      {error ? <ErrorBox message={error.message} details={error.details} /> : null}

      {ALTA_DE_JUEGOS ? (
        <NewGameCard
          pending={pending}
          onCreate={(body) => run(() => withToken((t) => adminApi.createGame(t, body)))}
        />
      ) : null}

      <div className="grid gap-3 sm:grid-cols-[12rem_1fr] sm:items-end">
        <SelectField<GameStatus | "">
          label="Estado"
          value={statusFilter}
          options={[["", "Todos"], ...STATUS_OPTIONS]}
          onChange={(v) => {
            setStatusFilter(v);
            setOffset(0);
          }}
        />
        <Field
          label="Buscar"
          placeholder="Nombre o slug"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOffset(0);
          }}
        />
      </div>

      {games.map((game) => (
        <div key={game.id} data-testid={`game-${game.slug}`}>
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-base font-bold">
                  {game.name}{" "}
                  <span className="font-mono text-xs font-normal text-muted">/juegos/{game.slug}</span>
                </h2>
                <p className="mt-1 text-sm text-muted">
                  {GAME_MODULE_LABEL[game.module]} · ícono {GAME_ICON_LABEL[game.icon].toLowerCase()} ·
                  orden {game.sort_order} · {game.variants.length} variante
                  {game.variants.length === 1 ? "" : "s"} ·{" "}
                  <span className="font-mono text-xs">{game.type}</span>
                </p>
                {game.description ? (
                  <p className="mt-1 max-w-prose text-sm text-white/80">{game.description}</p>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={STATUS_TONE[game.status]}>{GAME_STATUS_LABEL[game.status]}</Badge>
                {ALTA_DE_JUEGOS ? (
                  <Button variant="ghost" onClick={() => setEditing({ gameId: game.id })}>
                    + Variante
                  </Button>
                ) : null}
              </div>
            </div>

            <GameSettings
              game={game}
              pending={pending}
              onSave={(body) => run(() => withToken((t) => adminApi.updateGame(t, game.id, body)))}
            />

            <ul className="mt-4 space-y-2">
              {game.variants.map((v) => (
                <li
                  key={v.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-edge bg-ink px-3.5 py-3"
                >
                  <div className="text-sm">
                    <span className="font-bold">{v.name}</span>
                    <span className="ml-2 text-muted">
                      ventaja de la casa {(v.house_edge * 100).toFixed(2)} % ·{" "}
                      {v.config.possible_outcomes.length} resultados ·{" "}
                      {v.config.categories.length} categorías
                    </span>
                    {v.description ? (
                      <span className="block text-xs text-muted">{v.description}</span>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={v.active ? "ok" : "off"}>{v.active ? "activa" : "inactiva"}</Badge>
                    <Button
                      variant="ghost"
                      onClick={() => setEditing({ gameId: game.id, variant: v })}
                    >
                      Editar
                    </Button>
                  </div>
                </li>
              ))}
            </ul>

            {editing?.gameId === game.id ? (
              <div className="mt-4 rounded-card border border-gold/30 bg-ink p-4">
                <h3 className="mb-4 text-sm font-bold">
                  {editing.variant ? `Editar «${editing.variant.name}»` : "Nueva variante"}
                </h3>
                <VariantForm
                  initial={editing.variant}
                  pending={pending}
                  error={error}
                  onCancel={() => setEditing(null)}
                  onSubmit={(body) =>
                    run(() =>
                      withToken((t) =>
                        editing.variant
                          ? adminApi.updateVariant(t, game.id, editing.variant.id, body)
                          : adminApi.createVariant(t, game.id, body),
                      ),
                    )
                  }
                />
              </div>
            ) : null}
          </Card>
        </div>
      ))}

      {games.length === 0 ? <p className="text-sm text-muted">No hay juegos con ese filtro.</p> : null}

      <Pager
        total={total}
        offset={offset}
        count={games.length}
        pageSize={PAGE_SIZE}
        onChange={setOffset}
      />
    </main>
  );
}

function NewGameCard({
  pending,
  onCreate,
}: {
  pending: boolean;
  onCreate: (body: {
    name: string;
    type: string;
    slug: string;
    module: GameModule;
    description: string;
    icon: GameIcon;
    sort_order: number;
    status: GameStatus;
    reason: string;
  }) => Promise<boolean>;
}) {
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [slug, setSlug] = useState("");
  const [module, setModule] = useState<GameModule>("discrete_outcome");
  const [description, setDescription] = useState("");
  const [icon, setIcon] = useState<GameIcon>("generico");
  const [sortOrder, setSortOrder] = useState("0");
  const [reason, setReason] = useState("");

  return (
    <Card>
      <CardHeader
        title="Nuevo juego"
        subtitle="Nace oculto: los clientes no lo ven hasta que lo actives. El tipo, el slug y el módulo no cambian después."
      />
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await onCreate({
            name: name.trim(),
            type: type.trim(),
            slug: slug.trim(),
            module,
            description: description.trim(),
            icon,
            sort_order: Number(sortOrder) || 0,
            status: "hidden",
            reason: reason.trim(),
          });
          if (ok) {
            setName("");
            setType("");
            setSlug("");
            setDescription("");
            setSortOrder("0");
            setReason("");
          }
        }}
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <Field
            label="Nombre"
            required
            placeholder="Dados"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Field
            label="Tipo"
            required
            placeholder="dice"
            hint="Identificador interno. No se repite."
            value={type}
            onChange={(e) => setType(e.target.value)}
          />
          <Field
            label="Slug"
            required
            placeholder="dados"
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
            hint="Va en la URL: /juegos/<slug>. Minúsculas, números y guiones."
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <SelectField<GameModule>
            label="Módulo"
            value={module}
            options={MODULE_OPTIONS}
            onChange={setModule}
            hint="Decide qué pantalla lo juega. Deportes está reservado."
          />
          <SelectField<GameIcon> label="Ícono" value={icon} options={ICON_OPTIONS} onChange={setIcon} />
          <Field
            label="Orden en el menú"
            type="number"
            step="1"
            min={0}
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value)}
          />
        </div>
        <Field
          label="Descripción"
          hint="La ve el cliente en el menú de juegos."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <Field
          label="Motivo de la creación"
          required
          minLength={3}
          placeholder="Por qué se crea"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <Button type="submit" disabled={pending}>
          Crear juego
        </Button>
      </form>
    </Card>
  );
}

function GameSettings({
  game,
  pending,
  onSave,
}: {
  game: GameResponse;
  pending: boolean;
  onSave: (body: {
    name?: string;
    description?: string;
    icon?: GameIcon;
    sort_order?: number;
    status?: GameStatus;
    reason?: string;
  }) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(game.name);
  const [description, setDescription] = useState(game.description);
  const [icon, setIcon] = useState<GameIcon>(game.icon);
  const [sortOrder, setSortOrder] = useState(String(game.sort_order));
  const [status, setStatus] = useState<GameStatus>(game.status);
  const [reason, setReason] = useState("");

  if (!open) {
    return (
      <div className="mt-3">
        <Button variant="ghost" onClick={() => setOpen(true)}>
          Editar juego
        </Button>
      </div>
    );
  }

  const statusChanges = status !== game.status;

  return (
    <form
      className="mt-4 space-y-3 rounded-card border border-edge bg-ink p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        const body: Parameters<typeof onSave>[0] = {};
        if (name.trim() !== game.name) body.name = name.trim();
        if (description.trim() !== game.description) body.description = description.trim();
        if (icon !== game.icon) body.icon = icon;
        if ((Number(sortOrder) || 0) !== game.sort_order) body.sort_order = Number(sortOrder) || 0;
        if (statusChanges) {
          body.status = status;
          body.reason = reason.trim();
        }
        if (await onSave(body)) {
          setOpen(false);
          setReason("");
        }
      }}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Nombre" required value={name} onChange={(e) => setName(e.target.value)} />
        <SelectField<GameIcon> label="Ícono" value={icon} options={ICON_OPTIONS} onChange={setIcon} />
        <Field
          label="Orden en el menú"
          type="number"
          step="1"
          min={0}
          value={sortOrder}
          onChange={(e) => setSortOrder(e.target.value)}
        />
      </div>
      <Field
        label="Descripción"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <SelectField<GameStatus>
        label="Estado"
        value={status}
        options={STATUS_OPTIONS}
        onChange={setStatus}
        hint="Oculto: fuera del menú de los clientes. Próximamente: en el menú, sin abrir mesas. Las mesas ya abiertas siguen funcionando."
      />
      {statusChanges ? (
        <Field
          label="Motivo del cambio de estado"
          required
          minLength={3}
          hint="Queda en la bitácora."
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" disabled={pending}>
          Guardar
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
          Cancelar
        </Button>
      </div>
    </form>
  );
}

function describe(e: unknown): string {
  return e instanceof Error ? e.message : "Error inesperado";
}
