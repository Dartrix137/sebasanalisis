"use client";

/**
 * Vista de sesión de ruleta: ingreso manual (paso 5), los paneles del motor
 * estadístico núcleo (paso 6) y el de gestión de banca (paso 7).
 *
 * Sigue la composición de `docs/design/ruleta.jpeg` y `ruleta2.jpeg`, que son
 * dos secciones de la misma pantalla: columna izquierda con la sesión, el
 * teclado de números y la secuencia; columna derecha con los paneles de
 * análisis.
 *
 * El copy se aparta de los mockups a propósito. El original decía "Predicciones
 * — próxima tirada", "Precisión verificada" y "el motor empezará a medir tus
 * aciertos": todo eso implica que el sistema anticipa el resultado de un giro
 * independiente. Ver §0 y la skill `terminologia-no-predictiva`.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";
import {
  AllCategoriesPanel,
  PerformancePanel,
} from "@/components/roulette/AnalysisPanels";
import { BankrollPanel } from "@/components/roulette/BankrollPanel";
import { BetHistory, BetRow } from "@/components/roulette/BetRow";
import { SignalBoard } from "@/components/roulette/SignalBoard";
import { SummaryPanel } from "@/components/roulette/SummaryPanel";
import { DISCLAIMER_TEXT } from "@/components/Disclaimer";
import { Badge, Button, Card, CardHeader, ErrorBox, Field } from "@/components/ui";
import {
  ApiError,
  analysisApi,
  bankrollApi,
  betsApi,
  gamesApi,
  sessionsApi,
  spinsApi,
} from "@/lib/api-client";
import { TONE_CLASSES, describeOutcome, toneOf } from "@/lib/outcomes";
import { useSession } from "@/lib/session";
import type { GameVariantResponse } from "@/lib/types/games";
import type {
  SessionPerformanceResponse,
  SessionResponse,
  SessionSummaryResponse,
} from "@/lib/types/sessions";
import type { SpinResponse } from "@/lib/types/spins";
import type { BetResponse } from "@/lib/types/bets";
import type {
  BankrollSuggestionResponse,
  EligibleBetResponse,
  ProgressionTableResponse,
  StatisticalSuggestionsPanel,
  StreakAlert,
} from "@/lib/types/suggestions";

const CURRENCY = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

export function RouletteSession({ sessionId }: { sessionId: string }) {
  const { user, loading, withToken } = useSession();
  const router = useRouter();

  const [session, setSession] = useState<SessionResponse | null>(null);
  const [variant, setVariant] = useState<GameVariantResponse | null>(null);
  const [spins, setSpins] = useState<SpinResponse[]>([]);
  const [panel, setPanel] = useState<StatisticalSuggestionsPanel | null>(null);
  const [streak, setStreak] = useState<StreakAlert | null>(null);
  const [performance, setPerformance] = useState<SessionPerformanceResponse | null>(null);
  const [bankroll, setBankroll] = useState<BankrollSuggestionResponse | null>(null);
  const [progression, setProgression] = useState<ProgressionTableResponse | null>(null);
  const [eligibleBets, setEligibleBets] = useState<EligibleBetResponse[]>([]);
  const [bets, setBets] = useState<BetResponse[]>([]);
  const [summary, setSummary] = useState<SessionSummaryResponse | null>(null);
  // Sobre qué apuesta se estima el riesgo de agotar la banca. Null a propósito
  // al abrir: el motor no decide a qué se apuesta, así que hasta que el usuario
  // elija no se muestra ninguna estimación.
  const [selectedBetId, setSelectedBetId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [manual, setManual] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);

  const load = useCallback(async () => {
    const s = await withToken((t) => sessionsApi.get(t, sessionId));
    const [v, sp, pn, st, pf, bk, pg, eb, bt, sm] = await Promise.all([
      // La variante se pide por id, no listando los juegos: listar con
      // `include_inactive` exige rol admin y daba 403 a un usuario normal.
      withToken((t) => gamesApi.variant(t, s.game_variant_id)),
      withToken((t) => spinsApi.list(t, sessionId)),
      withToken((t) => analysisApi.suggestions(t, sessionId)),
      withToken((t) => analysisApi.streak(t, sessionId)),
      withToken((t) => analysisApi.performance(t, sessionId)),
      withToken((t) => bankrollApi.suggestion(t, sessionId, selectedBetId ?? undefined)),
      withToken((t) =>
        bankrollApi.progression(t, sessionId, {
          stages: 10,
          betId: selectedBetId ?? undefined,
        }),
      ),
      withToken((t) => bankrollApi.eligibleBets(t, sessionId)),
      withToken((t) => betsApi.list(t, sessionId)),
      withToken((t) => sessionsApi.summary(t, sessionId)),
    ]);
    setSession(s);
    setVariant(v);
    setSpins(sp);
    setPanel(pn);
    setStreak(st);
    setPerformance(pf);
    setBankroll(bk);
    setProgression(pg);
    setEligibleBets(eb);
    setBets(bt);
    setSummary(sm);
  }, [withToken, sessionId, selectedBetId]);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    load().catch((e) => setError(describe(e)));
  }, [loading, user, router, load]);

  async function run(action: () => Promise<unknown>) {
    setPending(true);
    setError(null);
    try {
      await action();
      await load();
    } catch (e) {
      setError(describe(e));
    } finally {
      setPending(false);
    }
  }

  if (loading || !user) return null;
  if (error && !session) {
    return (
      <div className="min-h-screen">
        <AppHeader />
        <main className="mx-auto max-w-3xl p-6">
          <ErrorBox message={error} />
          <Button className="mt-4" onClick={() => router.push("/dashboard")}>
            Volver al menú
          </Button>
        </main>
      </div>
    );
  }
  if (!session || !variant) return null;

  const abierta = session.status === "active";
  const categoryLabels = Object.fromEntries(
    variant.config.categories.map((c) => [c.id, c.label]),
  );
  const ultimo = spins.at(-1) ?? null;
  const masRecientePrimero = [...spins].reverse();

  function addSpin(value: string) {
    if (!abierta) return;
    run(() =>
      withToken((t) => spinsApi.create(t, sessionId, { result_value: value, source: "manual" })),
    );
  }

  return (
    <div className="min-h-screen">
      <AppHeader>
        <Badge>{spins.length} números</Badge>
        <Badge tone={abierta ? "ok" : "off"}>{abierta ? "sesión abierta" : "cerrada"}</Badge>
      </AppHeader>

      {/* Banner fijo: obligatorio en toda pantalla que muestre análisis (§0). */}
      <p
        role="note"
        className="border-b border-edge bg-gold/10 px-6 py-2 text-center text-xs text-white"
      >
        {DISCLAIMER_TEXT}
      </p>

      <main className="mx-auto grid max-w-6xl items-start gap-4 p-4 sm:gap-5 sm:p-6 lg:grid-cols-2">
        {error ? (
          <div className="lg:col-span-2">
            <ErrorBox message={error} />
          </div>
        ) : null}

        {/*
          Izquierda: las señales. Es lo primero que se mira y lo único que no
          comparte tarjeta con nada más.
        */}
        <div className="space-y-5">
          {!abierta ? <SummaryPanel summary={summary} /> : null}
          <SignalBoard panel={panel} streak={streak} categoryLabels={categoryLabels} />
        </div>

        {/*
          Derecha: la mesa. Apostar y registrar el número son un solo bucle, así
          que van en una tarjeta y no en tres.
        */}
        <Card>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              {renaming === null ? (
                <button
                  type="button"
                  onClick={() => abierta && setRenaming(session.name ?? "")}
                  disabled={!abierta}
                  className="text-left text-base font-bold text-white enabled:hover:text-gold"
                >
                  {session.name ?? "Sesión sin nombre"}
                </button>
              ) : (
                <form
                  className="flex items-end gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      await withToken((t) =>
                        sessionsApi.update(t, sessionId, { name: renaming.trim() || null }),
                      );
                      setRenaming(null);
                    });
                  }}
                >
                  <Field
                    label="Nombre"
                    maxLength={100}
                    autoFocus
                    value={renaming}
                    onChange={(e) => setRenaming(e.target.value)}
                  />
                  <Button type="submit" disabled={pending}>
                    Guardar
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setRenaming(null)}>
                    Cancelar
                  </Button>
                </form>
              )}
              <p className="mt-0.5 text-xs capitalize text-muted">{variant.name}</p>
            </div>

            <div className="text-right">
              <p className="text-xs text-muted">Banca</p>
              <p className="text-xl font-bold tabular-nums text-white">
                {CURRENCY.format(session.bankroll_current)}
              </p>
            </div>
          </div>

          {abierta ? (
            <div className="mt-4 border-t border-edge pt-4">
              <BetRow
                config={variant.config}
                bets={bets}
                bankrollCurrent={session.bankroll_current}
                suggestedBet={bankroll?.suggested_bet ?? null}
                riskWarning={bankroll?.risk_warning ?? null}
                abierta={abierta}
                pending={pending}
                onPlace={(body) =>
                  run(() => withToken((t) => betsApi.create(t, sessionId, body)))
                }
                onCancel={(betId) =>
                  run(() => withToken((t) => betsApi.cancel(t, sessionId, betId)))
                }
              />
            </div>
          ) : (
            <p className="mt-4 border-t border-edge pt-4 text-xs text-muted">
              Esta sesión está cerrada. Puedes consultarla, pero no registrar más números.
            </p>
          )}

          {abierta ? (
            <div className="mt-4 border-t border-edge pt-4">
              <h3 className="mb-2 text-sm font-bold text-white">Número que salió</h3>
              <div className="grid grid-cols-7 gap-1 sm:grid-cols-10 sm:gap-1.5">
                {variant.config.possible_outcomes.map((o) => (
                  <button
                    key={o}
                    type="button"
                    disabled={pending}
                    onClick={() => addSpin(o)}
                    className={`rounded-lg py-3 text-sm font-bold transition-transform disabled:opacity-40 enabled:hover:scale-105 sm:py-2 ${
                      TONE_CLASSES[toneOf(variant.config, o)]
                    }`}
                  >
                    {o}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="mt-4 border-t border-edge pt-4">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-sm font-bold text-white">
                Últimos números
                <span className="ml-2 text-xs font-normal text-muted">
                  el más reciente primero
                </span>
              </h3>
              {abierta && ultimo ? (
                <button
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    run(() => withToken((t) => spinsApi.remove(t, sessionId, ultimo.id)))
                  }
                  className="text-xs text-muted transition-colors hover:text-white disabled:opacity-40"
                >
                  Deshacer último
                </button>
              ) : null}
            </div>

            {spins.length === 0 ? (
              <p className="py-4 text-sm text-muted">
                Toca el número que salió para empezar a registrar.
              </p>
            ) : (
              <>
                <ol className="mt-2 flex flex-wrap gap-1.5">
                  {masRecientePrimero.slice(0, 24).map((s) => (
                    <li
                      key={s.id}
                      title={describeOutcome(variant.config, s.result_value)
                        .map((d) => `${d.category}: ${d.option}`)
                        .join(" · ")}
                      className={`flex h-8 w-8 items-center justify-center rounded-lg text-sm font-bold ${
                        TONE_CLASSES[toneOf(variant.config, s.result_value)]
                      }`}
                    >
                      {s.result_value}
                    </li>
                  ))}
                </ol>
                {spins.length > 24 ? (
                  <p className="mt-2 text-xs text-muted">
                    y {spins.length - 24} más atrás.
                  </p>
                ) : null}
              </>
            )}
          </div>
        </Card>

        {/*
          Todo lo que no forma parte del bucle de la mesa se consulta de vez en
          cuando, no a cada giro: va plegado y a ancho completo.
        */}
        <div className="space-y-3 lg:col-span-2">
          <Detalle titulo="Cómo va el motor frente a una línea base ingenua">
            <PerformancePanel performance={performance} />
          </Detalle>

          {abierta ? (
            <Detalle titulo="Gestión de banca y tabla de progresión">
              <BankrollPanel
                suggestion={bankroll}
                progression={progression}
                eligibleBets={eligibleBets}
                selectedBetId={selectedBetId}
                onSelectBet={setSelectedBetId}
              />
            </Detalle>
          ) : null}

          <Detalle titulo="Todas las categorías, incluidas las señales débiles">
            <AllCategoriesPanel panel={panel} categoryLabels={categoryLabels} />
          </Detalle>

          <Detalle titulo="Apuestas de esta sesión">
            <BetHistory bets={bets} />
          </Detalle>

          <Detalle titulo="Ajustes de la sesión">
            <Card>
              <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                <Stat label="Banca inicial" value={CURRENCY.format(session.bankroll_start)} />
                <Stat label="Apuesta base" value={CURRENCY.format(session.base_bet)} />
                <Stat label="Límite de mesa" value={CURRENCY.format(session.table_limit)} />
                <Stat
                  label="Progresión"
                  value={`${session.strategy_selected}${
                    session.strategy_mode === "two_sector" ? " · dos sectores" : ""
                  }`}
                />
                <Stat label="Escalón actual" value={String(session.strategy_stage + 1)} />
              </dl>
              {abierta ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button
                    variant="ghost"
                    disabled={pending || session.strategy_stage === 0}
                    onClick={() =>
                      run(() => withToken((t) => sessionsApi.resetStrategy(t, sessionId)))
                    }
                  >
                    Reiniciar progresión
                  </Button>
                  <Button
                    variant="danger"
                    disabled={pending}
                    onClick={() => run(() => withToken((t) => sessionsApi.close(t, sessionId)))}
                  >
                    Cerrar sesión de mesa
                  </Button>
                </div>
              ) : null}
            </Card>
          </Detalle>
        </div>
      </main>
    </div>
  );
}

/** Bloque plegado para lo que se consulta de vez en cuando, no a cada giro. */
function Detalle({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <details className="rounded-card border border-edge bg-ink-raised/60">
      <summary className="cursor-pointer px-5 py-3 text-sm font-bold text-muted transition-colors hover:text-white">
        {titulo}
      </summary>
      <div className="px-2 pb-2">{children}</div>
    </details>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-edge bg-ink px-3 py-2.5">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm font-bold capitalize">{value}</dd>
    </div>
  );
}

function describe(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Error inesperado";
}
