"use client";

/**
 * Panel de administración (paso 3): CRUD de juegos/variantes y gestión de
 * acceso de usuarios. Sin mockup de referencia — el sistema visual se hereda de
 * `docs/design/` (fondo azul-noche, tarjetas, acento dorado).
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { BacktestPanel } from "@/components/admin/BacktestPanel";
import { VariantForm } from "@/components/admin/VariantForm";
import { Badge, Button, Card, CardHeader, ErrorBox, Field } from "@/components/ui";
import { ApiError, adminApi, gamesApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type { AccessType, UserResponse } from "@/lib/types/auth";
import type { GameResponse, GameVariantResponse } from "@/lib/types/games";

type FormError = { message: string; details?: string[] } | null;

const ACCESS_TYPES: AccessType[] = ["trial", "invited", "full"];

export default function AdminPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();

  const [games, setGames] = useState<GameResponse[]>([]);
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [error, setError] = useState<FormError>(null);
  const [pending, setPending] = useState(false);
  const [editing, setEditing] = useState<{ gameId: string; variant?: GameVariantResponse } | null>(
    null,
  );

  const [newGameName, setNewGameName] = useState("");
  const [newGameType, setNewGameType] = useState("");

  const refresh = useCallback(async () => {
    const [g, u] = await Promise.all([
      withToken((t) => gamesApi.list(t, true)),
      withToken((t) => adminApi.listUsers(t)),
    ]);
    setGames(g);
    setUsers(u);
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
    refresh().catch((e) => setError({ message: describe(e) }));
  }, [loading, user, router, refresh]);

  async function run(action: () => Promise<unknown>) {
    setPending(true);
    setError(null);
    try {
      await action();
      await refresh();
      setEditing(null);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? { message: e.message, details: e.validationErrors }
          : { message: describe(e) },
      );
    } finally {
      setPending(false);
    }
  }

  if (loading || !user || user.role !== "admin") return null;

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-extrabold">Panel de administración</h1>
          <p className="mt-1 text-sm text-muted">
            Juegos, variantes y acceso de usuarios. Formulario estructurado, sin builder visual.
          </p>
        </div>
        <Button variant="ghost" onClick={() => router.push("/dashboard")}>
          Volver
        </Button>
      </header>

      {error ? <ErrorBox message={error.message} details={error.details} /> : null}

      <Card>
        <CardHeader
          title="Nuevo juego"
          subtitle="El tipo es el identificador interno y no se puede repetir."
        />
        <form
          className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              await withToken((t) =>
                adminApi.createGame(t, {
                  name: newGameName.trim(),
                  type: newGameType.trim(),
                  active: true,
                }),
              );
              setNewGameName("");
              setNewGameType("");
            });
          }}
        >
          <Field
            label="Nombre"
            required
            placeholder="Dados"
            value={newGameName}
            onChange={(e) => setNewGameName(e.target.value)}
          />
          <Field
            label="Tipo"
            required
            placeholder="dice"
            value={newGameType}
            onChange={(e) => setNewGameType(e.target.value)}
          />
          <Button type="submit" disabled={pending}>
            Crear juego
          </Button>
        </form>
      </Card>

      {games.map((game) => (
        <Card key={game.id}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-bold">
                {game.name}{" "}
                <span className="font-mono text-xs font-normal text-muted">{game.type}</span>
              </h2>
              <p className="mt-1 text-sm text-muted">
                {game.variants.length} variante{game.variants.length === 1 ? "" : "s"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge tone={game.active ? "ok" : "off"}>
                {game.active ? "activo" : "inactivo"}
              </Badge>
              <Button
                variant="ghost"
                disabled={pending}
                onClick={() =>
                  run(() =>
                    withToken((t) => adminApi.updateGame(t, game.id, { active: !game.active })),
                  )
                }
              >
                {game.active ? "Desactivar" : "Activar"}
              </Button>
              <Button variant="ghost" onClick={() => setEditing({ gameId: game.id })}>
                + Variante
              </Button>
            </div>
          </div>

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
      ))}

      {/* Métricas internas del motor (§2.10). Sólo admin: no las ve el cliente. */}
      <BacktestPanel variants={games.flatMap((g) => g.variants)} />

      <Card>
        <CardHeader title="Usuarios" subtitle="Cambia el tipo de acceso de cada cuenta." />
        <ul className="space-y-2">
          {users.map((u) => (
            <li
              key={u.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-edge bg-ink px-3.5 py-3"
            >
              <div className="text-sm">
                <span className="font-bold">{u.display_name ?? u.email}</span>
                {u.display_name ? <span className="ml-2 text-muted">{u.email}</span> : null}
                {u.role === "admin" ? (
                  <span className="ml-2">
                    <Badge>admin</Badge>
                  </span>
                ) : null}
              </div>
              <select
                value={u.access_type}
                disabled={pending}
                onChange={(e) =>
                  run(() =>
                    withToken((t) =>
                      adminApi.updateUserAccess(t, u.id, e.target.value as AccessType),
                    ),
                  )
                }
                className="rounded-lg border border-edge bg-ink-sunken px-3 py-2 text-sm text-white outline-none focus:border-gold/60"
              >
                {ACCESS_TYPES.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </li>
          ))}
        </ul>
      </Card>
    </main>
  );
}

function describe(e: unknown): string {
  return e instanceof Error ? e.message : "Error inesperado";
}
