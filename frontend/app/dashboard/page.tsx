"use client";

/**
 * Inicio: la mesa abierta para retomar, el menú de juegos y el historial de
 * mesas cerradas (§4). Desde el paso 7 de la Fase 4 (§7) cada juego tiene su
 * página (`/juegos/<slug>`), donde se elige la variante y se abre la mesa, y
 * cada mesa vive en `/juegos/<slug>/mesa/<id>`.
 *
 * Sin mockup de referencia: hereda el sistema de `docs/design/` (azul noche,
 * dorado para la acción principal, rojo/verde de mesa solo para los números).
 * El motivo visual son los propios números de la mesa: la secuencia registrada
 * es la materia prima del producto, así que la mesa abierta se reconoce por
 * sus últimos números y no por un texto.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";
import { AccessGate } from "@/components/AccessGate";
import { Disclaimer } from "@/components/Disclaimer";
import { GameMenu } from "@/components/GameMenu";
import { STRATEGY_LABEL } from "@/components/mesa/BankrollPanel";
import { NumberChip, variantLabel } from "@/components/mesa/VariantChoice";
import { Button, ErrorBox } from "@/components/ui";
import { VerifyEmailNotice } from "@/components/VerifyEmailNotice";
import { gamesApi, sessionsApi, spinsApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type { GameMenuItem, GameVariantResponse } from "@/lib/types/games";
import type { SessionResponse } from "@/lib/types/sessions";

const CURRENCY = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

const SIGNED = (n: number) => `${n >= 0 ? "+" : "−"}${CURRENCY.format(Math.abs(n))}`;

/** Cuántas mesas abiertas traen sus números: más allá, la lista es solo texto. */
const MESAS_CON_NUMEROS = 6;

export default function DashboardPage() {
  // El menú llama a los endpoints de juego: sin acceso responderían 403, así
  // que primero pasa por la compuerta.
  return (
    <AccessGate>
      <Dashboard />
    </AccessGate>
  );
}

function Dashboard() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();

  const [games, setGames] = useState<GameMenuItem[]>([]);
  const [openSessions, setOpenSessions] = useState<SessionResponse[]>([]);
  const [closedSessions, setClosedSessions] = useState<SessionResponse[]>([]);
  // Números de cada mesa abierta, en orden cronológico (el más reciente al final).
  const [numbers, setNumbers] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

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
    setGames(g.items);
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

  if (loading || !user) return null;

  const variants = new Map(games.flatMap((g) => g.variants).map((v) => [v.id, v]));
  const [principal, ...otras] = openSessions;
  const abrir = (s: SessionResponse) => router.push(`/juegos/${s.game_slug}/mesa/${s.id}`);

  return (
    <div className="flex-1">
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

        <VerifyEmailNotice />

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
            onContinue={() => abrir(principal)}
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
                  onContinue={() => abrir(s)}
                />
              ))}
            </ul>
          </section>
        ) : null}

        <section className="mt-12" aria-labelledby="juegos">
          <SectionTitle id="juegos">Elige un juego</SectionTitle>
          {ready && games.length === 0 && !error ? (
            <p className="mt-3 text-sm text-muted">
              No hay juegos disponibles todavía.
              {user.role === "admin"
                ? " Crea uno desde el panel de administración."
                : " Vuelve más tarde."}
            </p>
          ) : null}
          <GameMenu games={games} isAdmin={user.role === "admin"} />
        </section>

        {closedSessions.length > 0 ? (
          <section className="mt-12" aria-labelledby="historial">
            <SectionTitle id="historial">Mesas cerradas</SectionTitle>
            <ul className="mt-3 divide-y divide-edge border-y border-edge">
              {closedSessions.map((s) => (
                <ClosedTableRow key={s.id} session={s} onOpen={() => abrir(s)} />
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

/**
 * "Europea, martingala en el escalón 2": variante y progresiones en una frase.
 *
 * Desde la Fase 3 la sesión no elige una progresión — corren las tres a la vez
 * (§2.10)—, así que se nombran las que tienen una serie abierta. Si ninguna la
 * tiene, no hay nada que contar más allá de la variante.
 */
function tableDescription(s: SessionResponse, v: GameVariantResponse | undefined): string {
  const abiertas: string[] = [];
  if (s.stage_martingale > 0) {
    abiertas.push(`martingala en el escalón ${s.stage_martingale + 1}`);
  }
  if (s.stage_two_sector > 0) {
    abiertas.push(`2 sectores en el escalón ${s.stage_two_sector + 1}`);
  }
  return abiertas.length === 0
    ? `${variantLabel(v)}, sin serie abierta`
    : `${variantLabel(v)}, ${abiertas.join(" y ")}`;
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
          {session.name ? "" : null}
          {[
            session.stage_martingale > 0
              ? `martingala, escalón ${session.stage_martingale + 1}`
              : null,
            session.stage_two_sector > 0
              ? `2 sectores, escalón ${session.stage_two_sector + 1}`
              : null,
          ]
            .filter(Boolean)
            .join(" · ") || "sin serie abierta"}
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
