"use client";

/**
 * La página de un juego, `/juegos/<slug>` (§7.2 de la Fase 4): sus variantes y
 * el formulario para abrir una mesa. Se llega desde el menú del inicio.
 *
 * El juego sale del menú (`GET /games`), que ya trae su estado y la decisión de
 * acceso del servidor con ese juego. Un juego oculto no le llega a un cliente:
 * para él no existe.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { GameIcon } from "@/components/GameIcon";
import { NewSessionForm } from "@/components/mesa/NewSessionForm";
import { VariantChoice, variantLabel } from "@/components/mesa/VariantChoice";
import { Card, ErrorBox } from "@/components/ui";
import { ApiError, gamesApi, sessionsApi, spinsApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type { GameMenuItem, GameVariantResponse } from "@/lib/types/games";
import type { CreateSessionRequest } from "@/lib/types/sessions";
import type { BulkSpinsRequest } from "@/lib/types/spins";

export function GamePage({ slug }: { slug: string }) {
  const { user, withToken } = useSession();
  const router = useRouter();

  const [game, setGame] = useState<GameMenuItem | null | undefined>(undefined);
  const [hasOpenTable, setHasOpenTable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState<GameVariantResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const formRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const [menu, abiertas] = await Promise.all([
      withToken((t) => gamesApi.list(t)),
      withToken((t) => sessionsApi.list(t, "active")),
    ]);
    setGame(menu.items.find((g) => g.slug === slug) ?? null);
    setHasOpenTable(abiertas.length > 0);
  }, [withToken, slug]);

  useEffect(() => {
    load().catch((e) => setError(e instanceof Error ? e.message : "Error inesperado"));
  }, [load]);

  useEffect(() => {
    if (starting) formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [starting]);

  async function startSession(body: CreateSessionRequest, initial: BulkSpinsRequest | null) {
    setPending(true);
    setFormError(null);
    try {
      const sesion = await withToken((t) => sessionsApi.create(t, body));
      // La carga inicial va después de crear la sesión porque necesita su id.
      // Si falla, la sesión ya existe: se avisa sin entrar y queda listada en
      // las mesas abiertas del inicio, para no crear una segunda al reintentar.
      if (initial) {
        try {
          await withToken((t) => spinsApi.createBulk(t, sesion.id, initial));
        } catch (e) {
          setFormError(
            (e instanceof ApiError ? e.message : "No se pudieron cargar los números") +
              " La mesa quedó creada y aparece en tus mesas abiertas.",
          );
          setPending(false);
          return;
        }
      }
      router.push(`/juegos/${sesion.game_slug}/mesa/${sesion.id}`);
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "No se pudo crear la mesa");
      setPending(false);
    }
  }

  if (!user || game === undefined) {
    return error ? <Pantalla><ErrorBox message={error} /></Pantalla> : null;
  }

  if (game === null) {
    return (
      <Pantalla>
        <Aviso titulo="Este juego no está disponible" />
      </Pantalla>
    );
  }

  const esAdmin = user.role === "admin";
  if (game.status === "coming_soon" && !esAdmin) {
    return (
      <Pantalla>
        <Aviso titulo={`${game.name}: próximamente`} texto={game.description || undefined} />
      </Pantalla>
    );
  }
  if (!game.access.granted) {
    return (
      <Pantalla>
        <Aviso titulo="Este juego no está incluido en tu plan" texto="Está disponible en otro plan.">
          <Link
            href="/planes"
            className="inline-flex rounded-lg bg-gold px-4 py-2.5 text-sm font-bold text-gold-ink hover:bg-gold-soft"
          >
            Ver planes
          </Link>
        </Aviso>
      </Pantalla>
    );
  }

  const menorVentaja = Math.min(...game.variants.map((v) => v.house_edge));

  return (
    <Pantalla>
      <header className="flex items-start gap-4">
        <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl border border-gold/40 text-gold">
          <GameIcon icon={game.icon} className="h-8 w-8" />
        </span>
        <div className="min-w-0">
          <h1 className="font-display text-4xl font-semibold leading-none tracking-tight sm:text-5xl">
            {game.name}
          </h1>
          {game.description ? (
            <p className="mt-2 max-w-prose text-sm text-muted">{game.description}</p>
          ) : null}
        </div>
      </header>

      <section className="mt-10" aria-labelledby="abrir-mesa">
        <h2 id="abrir-mesa" className="font-display text-2xl font-semibold leading-tight">
          Abrir una mesa nueva
        </h2>
        {game.variants.length === 0 ? (
          <p className="mt-3 text-sm text-muted">Este juego todavía no tiene variantes.</p>
        ) : (
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {game.variants.map((v) => (
              <VariantChoice
                key={v.id}
                variant={v}
                lowestEdge={game.variants.length > 1 && v.house_edge === menorVentaja}
                selected={starting?.id === v.id}
                primary={!hasOpenTable}
                onStart={() => {
                  setStarting(v);
                  setFormError(null);
                }}
              />
            ))}
          </ul>
        )}
        {starting ? (
          <div
            ref={formRef}
            className="mt-4 scroll-mt-6 rounded-card border border-gold/40 bg-ink-raised p-4 sm:p-6"
          >
            <h3 className="font-display text-2xl font-semibold leading-tight">
              Mesa {variantLabel(starting).toLowerCase()}
            </h3>
            <p className="mb-5 mt-1 text-sm text-muted">
              Define tu banca y tu límite antes de empezar, no durante la partida.
            </p>
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
          </div>
        ) : null}
      </section>
    </Pantalla>
  );
}

function Pantalla({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 pb-12 pt-6 sm:px-6">
        <Link
          href="/dashboard"
          className="mb-6 inline-flex items-center gap-1.5 rounded-lg border border-edge bg-ink-sunken px-3 py-2 text-sm font-bold text-muted transition-colors hover:border-gold/50 hover:text-white"
        >
          <span aria-hidden>←</span> Volver al menú
        </Link>
        {children}
      </main>
    </div>
  );
}

function Aviso({
  titulo,
  texto,
  children,
}: {
  titulo: string;
  texto?: string;
  children?: React.ReactNode;
}) {
  return (
    <Card>
      <h1 className="font-display text-3xl font-semibold leading-tight">{titulo}</h1>
      {texto ? <p className="mt-2 text-sm text-muted">{texto}</p> : null}
      {children ? <div className="mt-5 flex flex-wrap gap-3">{children}</div> : null}
    </Card>
  );
}
