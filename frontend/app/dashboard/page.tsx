"use client";

/**
 * Menú principal (paso 4): la mesa abierta para retomar, las variantes para
 * abrir una nueva y el historial de mesas cerradas (§4).
 *
 * Sin mockup de referencia: hereda el sistema de `docs/design/` (azul noche,
 * dorado para la acción principal, rojo/verde de mesa solo para los números).
 * El motivo visual son los propios números de la mesa: la secuencia registrada
 * es la materia prima del producto, así que la mesa abierta se reconoce por
 * sus últimos números y no por un texto.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";
import { Disclaimer } from "@/components/Disclaimer";
import { STRATEGY_LABEL } from "@/components/roulette/BankrollPanel";
import { NewSessionForm } from "@/components/roulette/NewSessionForm";
import { Button, ErrorBox } from "@/components/ui";
import { ApiError, gamesApi, sessionsApi, spinsApi } from "@/lib/api-client";
import { TONE_CLASSES, toneOf } from "@/lib/outcomes";
import { useSession } from "@/lib/session";
import type { GameResponse, GameVariantResponse } from "@/lib/types/games";
import type { CreateSessionRequest, SessionResponse } from "@/lib/types/sessions";
import type { BulkSpinsRequest } from "@/lib/types/spins";

const CURRENCY = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

const SIGNED = (n: number) => `${n >= 0 ? "+" : "−"}${CURRENCY.format(Math.abs(n))}`;

/** Cuántas mesas abiertas traen sus números: más allá, la lista es solo texto. */
const MESAS_CON_NUMEROS = 6;

/** Nombres de las variantes precargadas; cualquier otra usa el suyo tal cual. */
const VARIANT_LABEL: Record<string, string> = {
  european: "Europea",
  american: "Americana",
};

function variantLabel(v: GameVariantResponse | undefined): string {
  if (!v) return "Variante";
  return VARIANT_LABEL[v.name] ?? v.name.charAt(0).toUpperCase() + v.name.slice(1);
}

export default function DashboardPage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();

  const [games, setGames] = useState<GameResponse[]>([]);
  const [openSessions, setOpenSessions] = useState<SessionResponse[]>([]);
  const [closedSessions, setClosedSessions] = useState<SessionResponse[]>([]);
  // Números de cada mesa abierta, en orden cronológico (el más reciente al final).
  const [numbers, setNumbers] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [starting, setStarting] = useState<GameVariantResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const formRef = useRef<HTMLDivElement>(null);

  async function startSession(body: CreateSessionRequest, initial: BulkSpinsRequest | null) {
    setPending(true);
    setFormError(null);
    try {
      const sesion = await withToken((t) => sessionsApi.create(t, body));
      // La carga inicial va después de crear la sesión porque necesita su id.
      // Si falla, la sesión ya existe: se avisa sin entrar y queda listada en
      // las mesas abiertas, para no crear una segunda al reintentar.
      if (initial) {
        try {
          await withToken((t) => spinsApi.createBulk(t, sesion.id, initial));
        } catch (e) {
          setFormError(
            (e instanceof ApiError ? e.message : "No se pudieron cargar los números") +
              " La mesa quedó creada y aparece en tus mesas abiertas.",
          );
          setPending(false);
          await load();
          return;
        }
      }
      router.push(`/games/roulette/${sesion.id}`);
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "No se pudo crear la mesa");
      setPending(false);
    }
  }

  const load = useCallback(async () => {
    const [g, abiertas, cerradas] = await Promise.all([
      withToken((t) => gamesApi.list(t)),
      withToken((t) => sessionsApi.list(t, "active")),
      withToken((t) => sessionsApi.list(t, "closed")),
    ]);
    const giros = await Promise.all(
      abiertas
        .slice(0, MESAS_CON_NUMEROS)
        .map((s) => withToken((t) => spinsApi.list(t, s.id))),
    );
    setGames(g);
    setOpenSessions(abiertas);
    setNumbers(
      Object.fromEntries(
        abiertas
          .slice(0, MESAS_CON_NUMEROS)
          .map((s, i) => [s.id, giros[i].map((sp) => sp.result_value)]),
      ),
    );
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

  useEffect(() => {
    if (starting) formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [starting]);

  if (loading || !user) return null;

  const activeGames = games.filter((g) => g.variants.length > 0);
  const variants = new Map(games.flatMap((g) => g.variants).map((v) => [v.id, v]));
  const [principal, ...otras] = openSessions;
  const abrir = (id: string) => router.push(`/games/roulette/${id}`);

  return (
    <div className="min-h-screen">
      <AppHeader />

      <main className="mx-auto max-w-5xl px-4 pb-12 pt-8 sm:px-6">
        <h1 className="font-display text-4xl font-semibold leading-none tracking-tight sm:text-5xl">
          Hola{user.display_name ? `, ${user.display_name}` : ""}
        </h1>
        <p className="mt-2 max-w-prose text-sm text-muted">
          {principal
            ? "Tu mesa te espera donde la dejaste."
            : "Abre una mesa y registra los números a medida que salen."}
        </p>

        {error ? (
          <div className="mt-6">
            <ErrorBox message={error} />
          </div>
        ) : null}

        {principal ? (
          <OpenTableHero
            session={principal}
            variant={variants.get(principal.game_variant_id)}
            numbers={numbers[principal.id] ?? []}
            onContinue={() => abrir(principal.id)}
          />
        ) : null}

        {otras.length > 0 ? (
          <section className="mt-10" aria-labelledby="otras-mesas">
            <SectionTitle id="otras-mesas">También abiertas</SectionTitle>
            <ul className="mt-3 divide-y divide-edge border-y border-edge">
              {otras.map((s) => (
                <OpenTableRow
                  key={s.id}
                  session={s}
                  variant={variants.get(s.game_variant_id)}
                  numbers={numbers[s.id]}
                  onContinue={() => abrir(s.id)}
                />
              ))}
            </ul>
          </section>
        ) : null}

        <section className="mt-12" aria-labelledby="abrir-mesa">
          <SectionTitle id="abrir-mesa">Abrir una mesa nueva</SectionTitle>

          {ready && activeGames.length === 0 && !error ? (
            <p className="mt-3 text-sm text-muted">
              No hay juegos activos todavía.
              {user.role === "admin"
                ? " Crea uno desde el panel de administración."
                : " Vuelve más tarde."}
            </p>
          ) : null}

          {activeGames.map((game) => {
            const menorVentaja = Math.min(...game.variants.map((v) => v.house_edge));
            return (
              <div key={game.id} className="mt-4">
                {activeGames.length > 1 ? (
                  <h3 className="mb-2 text-sm font-bold text-muted">{game.name}</h3>
                ) : null}
                <ul className="grid gap-3 sm:grid-cols-2">
                  {game.variants.map((v) => (
                    <VariantChoice
                      key={v.id}
                      variant={v}
                      lowestEdge={game.variants.length > 1 && v.house_edge === menorVentaja}
                      selected={starting?.id === v.id}
                      primary={!principal}
                      onStart={() => {
                        setStarting(v);
                        setFormError(null);
                      }}
                    />
                  ))}
                </ul>
              </div>
            );
          })}

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

        {closedSessions.length > 0 ? (
          <section className="mt-12" aria-labelledby="historial">
            <SectionTitle id="historial">Mesas cerradas</SectionTitle>
            <ul className="mt-3 divide-y divide-edge border-y border-edge">
              {closedSessions.map((s) => (
                <ClosedTableRow key={s.id} session={s} onOpen={() => abrir(s.id)} />
              ))}
            </ul>
            <p className="mt-3 max-w-prose text-xs leading-relaxed text-muted">
              Un buen o mal resultado pasado no dice nada sobre la próxima mesa: cada giro
              es independiente y la ventaja de la casa no cambia.
            </p>
          </section>
        ) : null}

        <div className="mt-12">
          <Disclaimer />
        </div>
      </main>
    </div>
  );
}

function SectionTitle({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h2 id={id} className="font-display text-2xl font-semibold leading-tight">
      {children}
    </h2>
  );
}

function NumberChip({
  value,
  variant,
  large = false,
  index = 0,
}: {
  value: string;
  variant: GameVariantResponse | undefined;
  large?: boolean;
  index?: number;
}) {
  const tone = variant ? toneOf(variant.config, value) : "neutral";
  return (
    <li
      style={large ? { animationDelay: `${index * 45}ms` } : undefined}
      className={`flex shrink-0 items-center justify-center rounded-full font-display font-semibold tabular-nums ${
        TONE_CLASSES[tone]
      } ${large ? "h-10 w-10 text-lg motion-safe:animate-chip-in sm:h-11 sm:w-11" : "h-6 w-6 text-xs"}`}
    >
      {value}
    </li>
  );
}

/** "Europea, con D'Alembert en el escalón 2": variante y progresión en una frase. */
function tableDescription(s: SessionResponse, v: GameVariantResponse | undefined): string {
  const nombre = STRATEGY_LABEL[s.strategy_selected] ?? s.strategy_selected;
  const progresion =
    s.strategy_selected === "flat"
      ? `con ${nombre.toLowerCase()}`
      : `con ${nombre} en el escalón ${s.strategy_stage + 1}`;
  return `${variantLabel(v)}, ${progresion}`;
}

/** La mesa abierta más reciente: lo primero que se busca al entrar. */
function OpenTableHero({
  session,
  variant,
  numbers,
  onContinue,
}: {
  session: SessionResponse;
  variant: GameVariantResponse | undefined;
  numbers: string[];
  onContinue: () => void;
}) {
  const neto = session.bankroll_current - session.bankroll_start;
  const recientes = [...numbers].reverse().slice(0, 14);

  return (
    <section
      aria-label="Tu mesa abierta"
      className="relative mt-8 overflow-hidden rounded-card border border-edge bg-ink-raised"
    >
      {/* Filo dorado: la única mesa que se destaca en la página. */}
      <div className="absolute inset-y-0 left-0 w-1 bg-gold" aria-hidden="true" />

      <div className="grid gap-6 p-5 pl-6 sm:grid-cols-[1fr_auto] sm:p-7 sm:pl-8">
        <div className="min-w-0">
          <p className="text-sm text-muted">
            {tableDescription(session, variant)}
          </p>
          <h2 className="mt-1 truncate font-display text-3xl font-semibold leading-tight sm:text-4xl">
            {session.name ?? "Mesa sin nombre"}
          </h2>

          {recientes.length > 0 ? (
            <div className="mt-5">
              <ol
                className="flex gap-1.5 overflow-x-auto pb-1"
                aria-label="Últimos números, el más reciente primero"
              >
                {recientes.map((n, i) => (
                  <NumberChip key={`${i}-${n}`} value={n} variant={variant} large index={i} />
                ))}
              </ol>
              <p className="mt-2 text-xs text-muted">
                {numbers.length} {numbers.length === 1 ? "número registrado" : "números registrados"}
                , el más reciente a la izquierda
              </p>
            </div>
          ) : (
            <p className="mt-5 text-sm text-muted">
              Todavía no has registrado números en esta mesa.
            </p>
          )}
        </div>

        <div className="flex flex-col justify-between gap-5 sm:items-end sm:text-right">
          <div>
            <p className="text-xs text-muted">Banca</p>
            <p className="font-display text-4xl font-semibold leading-none tabular-nums sm:text-5xl">
              {CURRENCY.format(session.bankroll_current)}
            </p>
            <p
              className={`mt-1.5 text-sm font-bold tabular-nums ${
                neto > 0 ? "text-signal-strong" : neto < 0 ? "text-table-red" : "text-muted"
              }`}
            >
              {neto === 0 ? "Igual que al empezar" : `${SIGNED(neto)} desde el inicio`}
            </p>
          </div>
          <Button onClick={onContinue} className="px-6">
            Volver a la mesa
          </Button>
        </div>
      </div>
    </section>
  );
}

function OpenTableRow({
  session,
  variant,
  numbers,
  onContinue,
}: {
  session: SessionResponse;
  variant: GameVariantResponse | undefined;
  numbers: string[] | undefined;
  onContinue: () => void;
}) {
  const recientes = numbers ? [...numbers].reverse().slice(0, 6) : [];
  return (
    <li className="flex flex-wrap items-center gap-x-6 gap-y-3 py-3.5">
      <div className="min-w-0 flex-1">
        <p className="truncate font-bold">{session.name ?? "Mesa sin nombre"}</p>
        <p className="text-xs text-muted">
          {tableDescription(session, variant)}
        </p>
      </div>
      {recientes.length > 0 ? (
        <ol className="hidden gap-1 md:flex" aria-label="Últimos números">
          {recientes.map((n, i) => (
            <NumberChip key={`${i}-${n}`} value={n} variant={variant} />
          ))}
        </ol>
      ) : null}
      <p className="w-32 text-right font-display text-xl font-semibold tabular-nums">
        {CURRENCY.format(session.bankroll_current)}
      </p>
      <Button variant="ghost" onClick={onContinue}>
        Continuar
      </Button>
    </li>
  );
}

/**
 * Cada variante se distingue por lo que de verdad la separa: cuántos ceros
 * tiene el cilindro. El doble cero es exactamente lo que sube la ventaja de la
 * casa de la americana.
 */
function VariantChoice({
  variant,
  lowestEdge,
  selected,
  primary,
  onStart,
}: {
  variant: GameVariantResponse;
  lowestEdge: boolean;
  selected: boolean;
  /** Dorado solo si abrir mesa es la acción principal (no hay otra abierta). */
  primary: boolean;
  onStart: () => void;
}) {
  const ceros = variant.config.possible_outcomes.filter(
    (o) => toneOf(variant.config, o) === "green",
  );

  return (
    <li
      className={`flex flex-col rounded-card border bg-ink-raised p-5 transition-colors ${
        selected ? "border-gold/60" : "border-edge"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-display text-3xl font-semibold leading-none">
            {variantLabel(variant)}
          </h3>
          <p className="mt-2 text-sm text-muted">
            {variant.config.possible_outcomes.length} números
            {ceros.length > 0
              ? `, ${ceros.length === 1 ? "un cero" : ceros.length === 2 ? "dos ceros" : `${ceros.length} ceros`}`
              : ""}
          </p>
        </div>
        {ceros.length > 0 ? (
          <ul className="flex gap-1" aria-hidden="true">
            {ceros.map((c) => (
              <NumberChip key={c} value={c} variant={variant} large />
            ))}
          </ul>
        ) : null}
      </div>

      <div className="mt-5 flex items-baseline gap-2">
        <span className="font-display text-2xl font-semibold tabular-nums">
          {(variant.house_edge * 100).toFixed(2).replace(".", ",")} %
        </span>
        <span className="text-sm text-muted">de ventaja para la casa</span>
      </div>
      <p className="mt-1 min-h-[1.25rem] text-xs text-muted">
        {lowestEdge ? "La ventaja más baja de las disponibles." : ""}
      </p>

      <Button
        className="mt-4"
        variant={primary ? "primary" : "ghost"}
        onClick={onStart}
        disabled={selected}
      >
        {selected ? "Configurando abajo" : `Abrir mesa ${variantLabel(variant).toLowerCase()}`}
      </Button>
    </li>
  );
}

function ClosedTableRow({ session, onOpen }: { session: SessionResponse; onOpen: () => void }) {
  const neto = session.bankroll_current - session.bankroll_start;
  const fecha = session.closed_at
    ? new Date(session.closed_at).toLocaleDateString("es-CO", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "Sin fecha de cierre";

  return (
    <li className="flex flex-wrap items-center gap-x-6 gap-y-2 py-3">
      <p className="w-28 shrink-0 text-xs text-muted">{fecha}</p>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-bold">{session.name ?? "Mesa sin nombre"}</p>
        <p className="text-xs text-muted">
          {STRATEGY_LABEL[session.strategy_selected] ?? session.strategy_selected}
        </p>
      </div>
      <p
        className={`w-32 text-right font-display text-xl font-semibold tabular-nums ${
          neto > 0 ? "text-signal-strong" : neto < 0 ? "text-table-red" : "text-muted"
        }`}
      >
        {neto === 0 ? "$ 0" : SIGNED(neto)}
      </p>
      <Button variant="ghost" onClick={onOpen}>
        Ver
      </Button>
    </li>
  );
}
