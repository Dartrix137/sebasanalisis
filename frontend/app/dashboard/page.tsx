"use client";

/**
 * Menú principal (paso 4): selector de juegos activos + atajo a la sesión de
 * mesa abierta, si existe (§4).
 *
 * Sin mockup de referencia: el sistema visual se hereda de `docs/design/`
 * (fondo azul-noche, tarjetas con borde sutil, acento dorado en la acción
 * primaria, rojo/verde de mesa solo para los números de la ruleta).
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { NewSessionForm } from "@/components/roulette/NewSessionForm";
import { Disclaimer } from "@/components/Disclaimer";
import { Badge, Button, Card, CardHeader, ErrorBox } from "@/components/ui";
import { ApiError, gamesApi, sessionsApi, spinsApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type { GameResponse, GameVariantResponse } from "@/lib/types/games";
import type { CreateSessionRequest, SessionResponse } from "@/lib/types/sessions";
import type { BulkSpinsRequest } from "@/lib/types/spins";

const CURRENCY = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

export default function DashboardPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();

  const [games, setGames] = useState<GameResponse[]>([]);
  const [openSessions, setOpenSessions] = useState<SessionResponse[]>([]);
  const [closedSessions, setClosedSessions] = useState<SessionResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [starting, setStarting] = useState<GameVariantResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function startSession(
    body: CreateSessionRequest,
    initial: BulkSpinsRequest | null,
  ) {
    setPending(true);
    setFormError(null);
    try {
      const sesion = await withToken((t) => sessionsApi.create(t, body));
      // La carga inicial va después de crear la sesión porque necesita su id.
      // Si falla, la sesión ya existe: se avisa sin entrar y queda listada en
      // "sesiones abiertas", para no crear una segunda al reintentar.
      if (initial) {
        try {
          await withToken((t) => spinsApi.createBulk(t, sesion.id, initial));
        } catch (e) {
          setFormError(
            (e instanceof ApiError ? e.message : "No se pudieron cargar los números") +
              " La sesión quedó creada y aparece en tus sesiones abiertas.",
          );
          setPending(false);
          await load();
          return;
        }
      }
      router.push(`/games/roulette/${sesion.id}`);
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "No se pudo crear la sesión");
      setPending(false);
    }
  }

  const load = useCallback(async () => {
    const [g, abiertas, cerradas] = await Promise.all([
      withToken((t) => gamesApi.list(t)),
      withToken((t) => sessionsApi.list(t, "active")),
      withToken((t) => sessionsApi.list(t, "closed")),
    ]);
    setGames(g);
    setOpenSessions(abiertas);
    // Más recientes primero: lo último que jugaste es lo que quieres revisar.
    setClosedSessions(
      [...cerradas].sort(
        (a, b) =>
          new Date(b.closed_at ?? b.started_at).getTime() -
          new Date(a.closed_at ?? a.started_at).getTime(),
      ),
    );
  }, [withToken]);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    load()
      .catch((e) => setError(e instanceof Error ? e.message : "Error inesperado"))
      .finally(() => setReady(true));
  }, [loading, user, router, load]);

  if (loading || !user) return null;

  const activeGames = games.filter((g) => g.variants.length > 0);

  return (
    <div className="min-h-screen">
      <AppHeader />

      <main className="mx-auto max-w-6xl space-y-6 p-6">
        <div>
          <h1 className="text-xl font-extrabold">
            Hola{user.display_name ? `, ${user.display_name}` : ""}
          </h1>
          <p className="mt-1 text-sm text-muted">
            Elige una mesa para registrar sus resultados y ver el análisis descriptivo de lo
            que ya ocurrió.
          </p>
        </div>

        {error ? <ErrorBox message={error} /> : null}

        {openSessions.length > 0 ? (
          <Card className="border-gold/40">
            <CardHeader
              title="Sesiones de mesa abiertas"
              subtitle="Retoma donde ibas: cada sesión guarda su propia secuencia y estadísticas."
            />
            <ul className="space-y-2">
              {openSessions.map((s) => (
                <li
                  key={s.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-edge bg-ink px-3.5 py-3"
                >
                  <div className="text-sm">
                    <span className="font-bold">{s.name ?? "Sesión sin nombre"}</span>
                    <span className="ml-2 text-muted">
                      banca {CURRENCY.format(s.bankroll_current)} · apuesta base{" "}
                      {CURRENCY.format(s.base_bet)} · {s.strategy_selected}
                      {s.strategy_mode === "two_sector" ? " (dos sectores)" : ""}
                    </span>
                  </div>
                  <Button onClick={() => router.push(`/games/roulette/${s.id}`)}>
                    Continuar
                  </Button>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}

        {closedSessions.length > 0 ? (
          <Card>
            <CardHeader
              title="Mesas cerradas"
              subtitle="Tu historial. Cada una guarda su secuencia, sus apuestas y su resumen."
            />
            <ul className="space-y-2">
              {closedSessions.map((s) => {
                const neto = s.bankroll_current - s.bankroll_start;
                return (
                  <li
                    key={s.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-edge bg-ink px-3.5 py-3"
                  >
                    <div className="text-sm">
                      <span className="font-bold">{s.name ?? "Sesión sin nombre"}</span>
                      <span className="ml-2 text-muted">
                        {s.closed_at
                          ? new Date(s.closed_at).toLocaleDateString("es-CO", {
                              day: "numeric",
                              month: "short",
                              year: "numeric",
                            })
                          : "sin fecha de cierre"}{" "}
                        · {s.strategy_selected}
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span
                        className={`text-sm font-bold tabular-nums ${
                          neto > 0
                            ? "text-signal-strong"
                            : neto < 0
                              ? "text-table-red"
                              : "text-muted"
                        }`}
                      >
                        {neto >= 0 ? "+" : "−"}
                        {CURRENCY.format(Math.abs(neto))}
                      </span>
                      <Button
                        variant="ghost"
                        onClick={() => router.push(`/games/roulette/${s.id}`)}
                      >
                        Ver
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
            <p className="mt-3 text-xs leading-relaxed text-muted">
              Un buen o mal resultado pasado no dice nada sobre la próxima sesión: cada
              giro es independiente y la ventaja de la casa no cambia.
            </p>
          </Card>
        ) : null}

        {ready && activeGames.length === 0 && !error ? (
          <Card>
            <p className="text-sm text-muted">
              No hay juegos activos todavía.
              {user.role === "admin"
                ? " Crea uno desde el panel de administración."
                : " Vuelve más tarde."}
            </p>
          </Card>
        ) : null}

        {activeGames.map((game) => (
          <Card key={game.id}>
            <CardHeader
              title={game.name}
              subtitle={`${game.variants.length} variante${
                game.variants.length === 1 ? "" : "s"
              } disponible${game.variants.length === 1 ? "" : "s"}`}
            />
            <ul className="grid gap-3 sm:grid-cols-2">
              {game.variants.map((v) => (
                <VariantCard key={v.id} variant={v} onStart={() => setStarting(v)} />
              ))}
            </ul>
          </Card>
        ))}

        {starting ? (
          <Card className="border-gold/40">
            <CardHeader
              title={`Nueva sesión · ${starting.name}`}
              subtitle="Define tu banca y tu límite antes de empezar, no durante la partida."
            />
            <NewSessionForm
              variant={starting}
              pending={pending}
              error={formError}
              onCancel={() => {
                setStarting(null);
                setFormError(null);
              }}
              onSubmit={startSession}
            />
          </Card>
        ) : null}

        <Disclaimer />
      </main>
    </div>
  );
}

function VariantCard({
  variant,
  onStart,
}: {
  variant: GameVariantResponse;
  onStart: () => void;
}) {
  const categorias = variant.config.categories.map((c) => c.label).join(" · ");

  return (
    <li className="rounded-card border border-edge bg-ink p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold capitalize">{variant.name}</h3>
          <p className="mt-1 text-xs text-muted">
            {variant.config.possible_outcomes.length} resultados posibles
          </p>
        </div>
        <Badge>{(variant.house_edge * 100).toFixed(2)} % ventaja de la casa</Badge>
      </div>

      <p className="mt-3 text-xs leading-relaxed text-muted">{categorias}</p>

      <Button className="mt-4 w-full" onClick={onStart}>
        Iniciar sesión de mesa
      </Button>
    </li>
  );
}
