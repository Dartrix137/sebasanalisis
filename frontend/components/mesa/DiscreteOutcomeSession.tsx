"use client";

/**
 * La mesa de un juego de resultados discretos: el componente del módulo
 * `discrete_outcome` (§7.3 de la Fase 4), que juega la ruleta y todo juego que
 * se describa con `categories_json`. Nada aquí supone ruleta: el teclado sale
 * de `possible_outcomes` y su tono y columnas de la pista `display`.
 *
 * Desde la Fase 3 (§2.10) la pieza central es la recomendación: qué apostar en
 * el siguiente giro, o no apostar.
 *
 * Lo que cambió respecto del analizador:
 *
 * - El ranking top-3, las señales por categoría, la racha activa y la tasa de
 *   coincidencia del motor salieron de la vista. Las frecuencias y las
 *   probabilidades teóricas de la recomendación se muestran dentro de "¿Por qué
 *   recomienda esto?": son el respaldo, no el protagonista.
 * - La recomendación se recalcula sola al ingresar cada número.
 * - La gestión de banca no se elige: la mesa muestra las tres progresiones con
 *   lo que pediría cada una para el mercado recomendado.
 *
 * Sigue la composición de `docs/design/ruleta.jpeg` y `ruleta2.jpeg` en lo que
 * queda vigente: columna izquierda con el análisis, derecha con la mesa. En el
 * celular (decidido el 2026-10-20) va una sola columna con la recomendación
 * compacta arriba y el teclado justo debajo: es lo que se mira y se toca en
 * cada giro, con una mano, mientras se sigue la mesa del casino.
 *
 * El copy se aparta de los mockups a propósito. El original decía "Predicciones
 * — próxima tirada", "Precisión verificada" y "el motor empezará a medir tus
 * aciertos": todo eso implica que el sistema anticipa el resultado de un giro
 * independiente. Ver §0 y la skill `terminologia-no-predictiva`.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PageSkeleton } from "@/components/PageSkeleton";
import { BankrollPanel } from "@/components/mesa/BankrollPanel";
import { BetHistory, BetRow } from "@/components/mesa/BetRow";
import { AYUDA } from "@/components/mesa/NewSessionForm";
import { RecommendationCard } from "@/components/mesa/RecommendationCard";
import { RoundStatus } from "@/components/mesa/RoundStatus";
import { StopCard } from "@/components/mesa/StopCard";
import { SummaryPanel } from "@/components/mesa/SummaryPanel";
import { variantLabel } from "@/components/mesa/VariantChoice";
import { Badge, Button, ErrorBox, Field } from "@/components/ui";
import {
  ApiError,
  betsApi,
  gamesApi,
  recommendationApi,
  sessionsApi,
  spinsApi,
} from "@/lib/api-client";
import { TONE_CLASSES, describeOutcome, keypadColumns, toneOf } from "@/lib/outcomes";
import { useSession } from "@/lib/session";
import type { GameVariantResponse } from "@/lib/types/games";
import type {
  SessionResponse,
  SessionSummaryResponse,
  UpdateSessionRequest,
} from "@/lib/types/sessions";
import type { SpinResponse } from "@/lib/types/spins";
import type { BetResponse } from "@/lib/types/bets";
import type { RecommendationRecord, RecommendationResponse } from "@/lib/types/suggestions";

const CURRENCY = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

export function DiscreteOutcomeSession({ sessionId }: { sessionId: string }) {
  const { user, loading, withToken } = useSession();
  const router = useRouter();

  const [session, setSession] = useState<SessionResponse | null>(null);
  const [variant, setVariant] = useState<GameVariantResponse | null>(null);
  const [spins, setSpins] = useState<SpinResponse[]>([]);
  const [bets, setBets] = useState<BetResponse[]>([]);
  const [summary, setSummary] = useState<SessionSummaryResponse | null>(null);
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(
    null,
  );
  const [history, setHistory] = useState<RecommendationRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [editingAjustes, setEditingAjustes] = useState(false);
  const [ajTableLimit, setAjTableLimit] = useState("");
  const [ajLossLimit, setAjLossLimit] = useState("");

  const load = useCallback(async () => {
    const s = await withToken((t) => sessionsApi.get(t, sessionId));
    const [v, sp, bt, sm, rc, hs] = await Promise.all([
      // La variante se pide por id: se lee aunque esté desactivada, porque la
      // mesa ya estaba abierta.
      withToken((t) => gamesApi.variant(t, s.game_variant_id)),
      withToken((t) => spinsApi.list(t, sessionId)),
      withToken((t) => betsApi.list(t, sessionId)),
      withToken((t) => sessionsApi.summary(t, sessionId)),
      // La recomendación se recalcula sola: `load()` corre tras cada giro.
      withToken((t) => recommendationApi.latest(t, sessionId)),
      // Para explicar cómo movió las progresiones la recomendación anterior.
      withToken((t) => recommendationApi.history(t, sessionId)),
    ]);
    setSession(s);
    setVariant(v);
    setSpins(sp);
    setBets(bt);
    setSummary(sm);
    setRecommendation(rc);
    setHistory(hs);
  }, [withToken, sessionId]);

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

  /**
   * Anotar o quitar una apuesta pendiente solo cambia la lista de apuestas: la
   * banca, los escalones y la recomendación se mueven cuando entra el número.
   * Por eso aquí no se recarga toda la mesa.
   */
  async function runBets(action: () => Promise<unknown>) {
    setPending(true);
    setError(null);
    try {
      await action();
      setBets(await withToken((t) => betsApi.list(t, sessionId)));
    } catch (e) {
      setError(describe(e));
    } finally {
      setPending(false);
    }
  }

  if (loading || !user) return <PageSkeleton shape="mesa" />;
  if (error && !session) {
    return (
      <div className="flex-1">
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
  if (!session || !variant) return <PageSkeleton shape="mesa" />;

  const abierta = session.status === "active";
  // Banca sin la apuesta base o límite de pérdida alcanzado: abierta, sin apuestas.
  const parada = abierta && session.stop_reason !== null;
  const ultimo = spins.at(-1) ?? null;
  const penultimo = spins.at(-2) ?? null;
  const masRecientePrimero = [...spins].reverse();
  const columnas = keypadColumns(variant.config);

  const pendientes = bets.filter((b) => b.status === "pending");
  const disponible =
    session.bankroll_current - pendientes.reduce((acc, b) => acc + b.amount, 0);
  // Cambia cuando cambia algo que mueve los montos de las gestiones.
  const bankrollVersion = [
    spins.length,
    session.bankroll_current,
    session.stage_martingale,
    session.stage_two_sector,
    session.table_limit,
    session.loss_limit,
  ].join("|");

  const limiteActual = session.loss_limit;
  const limiteNuevo = ajLossLimit === "" ? null : Number(ajLossLimit);
  // §9 del documento verificado: el límite se puede fijar o bajar, nunca subir
  // ni quitar con la sesión abierta. El backend lo rechaza igual; esto avisa antes.
  const limiteInvalido =
    limiteNuevo !== null &&
    (!(limiteNuevo > 0) ||
      limiteNuevo > session.bankroll_start ||
      (limiteActual !== null && limiteNuevo > limiteActual));
  const quitaLimite = limiteActual !== null && limiteNuevo === null;

  const persistida = session;
  function guardarAjustes() {
    const cambios: UpdateSessionRequest = {};
    if (Number(ajTableLimit) !== persistida.table_limit) {
      cambios.table_limit = Number(ajTableLimit);
    }
    if (limiteNuevo !== limiteActual) cambios.loss_limit = limiteNuevo;
    run(async () => {
      if (Object.keys(cambios).length > 0) {
        await withToken((t) => sessionsApi.update(t, sessionId, cambios));
      }
      setEditingAjustes(false);
    });
  }

  function addSpin(value: string) {
    if (!abierta) return;
    run(() =>
      withToken((t) => spinsApi.create(t, sessionId, { result_value: value, source: "manual" })),
    );
  }

  return (
    <div className="flex-1">
      <AppHeader />

      {/*
        Franja de la mesa: volver, cuál es y cuánto queda en la banca. Reemplaza
        al botón "Volver al menú" y a los indicadores que iban en el encabezado,
        para que la recomendación empiece lo más arriba posible en el celular.
      */}
      <div className="border-b border-edge">
        <div className="mx-auto flex max-w-6xl items-center gap-2 px-2 py-1.5 sm:px-4">
          <Link
            href="/dashboard"
            aria-label="Volver al menú"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-xl text-muted transition-colors hover:bg-ink-raised hover:text-white"
          >
            <span aria-hidden>←</span>
          </Link>
          <div className="min-w-0 flex-1">
            {renaming === null ? (
              <button
                type="button"
                onClick={() => abierta && setRenaming(session.name ?? "")}
                disabled={!abierta}
                className="block max-w-full truncate text-left text-base font-bold leading-tight text-white enabled:hover:text-gold"
              >
                {session.name ?? "Sesión sin nombre"}
              </button>
            ) : (
              <p className="text-base font-bold leading-tight text-white">Cambiar el nombre</p>
            )}
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted">
              <span>{variantLabel(variant)}</span>
              <span>{spins.length} números</span>
              {abierta ? null : <Badge tone="off">cerrada</Badge>}
            </p>
          </div>
          <div className="shrink-0 pr-2 text-right">
            <p className="text-xs text-muted">Banca</p>
            <p className="font-display text-2xl font-semibold leading-none tabular-nums text-white">
              {CURRENCY.format(session.bankroll_current)}
            </p>
          </div>
        </div>
        {renaming !== null ? (
          <form
            className="mx-auto flex max-w-6xl flex-wrap items-end gap-2 px-4 pb-3 sm:px-6"
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
            <div className="min-w-0 flex-1 basis-48">
              <Field
                label="Nombre"
                maxLength={100}
                autoFocus
                value={renaming}
                onChange={(e) => setRenaming(e.target.value)}
              />
            </div>
            <Button type="submit" disabled={pending}>
              Guardar
            </Button>
            <Button type="button" variant="ghost" onClick={() => setRenaming(null)}>
              Cancelar
            </Button>
          </form>
        ) : null}
      </div>

      {/* `grid-cols-1` y no la columna implícita: esa crece con la tabla de
          progresión (más ancha que un celular) y desborda la pantalla. Desde
          tableta, dos columnas: la recomendación al lado del teclado. */}
      <main className="mx-auto grid w-full max-w-6xl grid-cols-1 items-start gap-4 px-4 pb-6 pt-4 sm:gap-5 sm:px-6 md:grid-cols-2">
        {error ? (
          <div className="md:col-span-2">
            <ErrorBox message={error} />
          </div>
        ) : null}

        {/*
          La recomendación: lo primero de la pantalla. Responde la pregunta que
          el analizador dejaba abierta — qué apostar en el siguiente giro, o no
          apostar (§2.10).
        */}
        <div className="space-y-5">
          {!abierta ? <SummaryPanel summary={summary} /> : null}
          {parada ? (
            <StopCard
              session={session}
              busy={pending}
              onClose={() => run(() => withToken((t) => sessionsApi.close(t, sessionId)))}
            />
          ) : abierta ? (
            <RecommendationCard
              recommendation={recommendation}
              registration={{
                config: variant.config,
                available: disponible,
                pendingBets: pendientes,
                busy: pending,
                // Dos zonas (dos docenas) son dos apuestas: una por casilla.
                onRegister: (bodies) =>
                  runBets(async () => {
                    for (const body of bodies) {
                      await withToken((t) => betsApi.create(t, sessionId, body));
                    }
                  }),
              }}
            />
          ) : null}
        </div>

        {/*
          La mesa: el teclado justo debajo de la recomendación (al lado, desde
          tableta), porque es lo que se toca en cada giro. Lo que dejó el número,
          los últimos números y las apuestas del giro van después.
        */}
        <section aria-label="La mesa" className="space-y-4">
          {abierta ? (
            <div>
              <h2 className="mb-2 text-sm font-bold text-white">Número que salió</h2>
              <Keypad
                config={variant.config}
                columns={columnas}
                disabled={pending}
                onPick={addSpin}
              />
            </div>
          ) : null}

          {abierta ? (
            <RoundStatus
              session={session}
              lastSpin={ultimo}
              previousSpin={penultimo}
              bets={bets}
              history={history}
            />
          ) : (
            <p className="text-sm text-muted">
              Esta sesión está cerrada. Puedes consultarla, pero no registrar más números.
            </p>
          )}

          <div className="border-t border-edge pt-2">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-bold text-white">
                Últimos números
                <span className="ml-2 text-xs font-normal text-muted">
                  el más reciente primero
                </span>
              </h2>
              {abierta && ultimo ? (
                <button
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    run(() => withToken((t) => spinsApi.remove(t, sessionId, ultimo.id)))
                  }
                  className="-mr-3 inline-flex min-h-11 shrink-0 items-center rounded-lg px-3 text-sm font-bold text-muted transition-colors hover:bg-ink-raised hover:text-white disabled:opacity-40"
                >
                  Deshacer último
                </button>
              ) : null}
            </div>

            {spins.length === 0 ? (
              <p className="py-3 text-sm text-muted">
                Toca el número que salió para empezar a registrar.
              </p>
            ) : (
              <>
                <ol className="mt-1 flex flex-wrap gap-1.5">
                  {masRecientePrimero.slice(0, 24).map((s) => (
                    <li
                      key={s.id}
                      title={describeOutcome(variant.config, s.result_value)
                        .map((d) => `${d.category}: ${d.option}`)
                        .join(" · ")}
                      className={`flex h-8 w-8 items-center justify-center rounded-md font-display text-base font-semibold ${
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

          {parada ? (
            <p className="border-t border-edge pt-3 text-xs text-muted">
              Esta mesa ya no acepta apuestas. Puedes seguir anotando números o
              deshacer el último si quedó mal ingresado.
            </p>
          ) : abierta ? (
            <div className="border-t border-edge pt-3">
              <BetRow
                config={variant.config}
                bets={bets}
                bankrollCurrent={session.bankroll_current}
                baseBet={session.base_bet}
                recommends={recommendation?.decision === "RECOMMEND"}
                abierta={abierta}
                pending={pending}
                onPlace={(body) =>
                  runBets(() => withToken((t) => betsApi.create(t, sessionId, body)))
                }
                onCancel={(betId) =>
                  runBets(() => withToken((t) => betsApi.cancel(t, sessionId, betId)))
                }
              />
            </div>
          ) : null}
        </section>

        {/*
          Todo lo que no forma parte del bucle de la mesa se consulta de vez en
          cuando, no a cada giro: va plegado, en filas, a ancho completo.
        */}
        <div className="divide-y divide-edge border-y border-edge md:col-span-2">
          {abierta ? (
            <Detalle titulo="Gestión de banca y tabla de progresión">
              <BankrollPanel sessionId={sessionId} version={bankrollVersion} />
            </Detalle>
          ) : null}

          <Detalle titulo="Apuestas de esta sesión">
            <BetHistory bets={bets} summary={summary} />
          </Detalle>

          <Detalle titulo="Ajustes de la sesión">
            <div>
              {editingAjustes ? (
                <form
                  className="space-y-4"
                  onSubmit={(e) => {
                    e.preventDefault();
                    guardarAjustes();
                  }}
                >
                  <dl className="grid grid-cols-2 gap-3 text-sm">
                    <Stat label="Banca inicial" value={CURRENCY.format(session.bankroll_start)} />
                    <Stat label="Apuesta base" value={CURRENCY.format(session.base_bet)} />
                  </dl>
                  <p className="text-xs text-muted">
                    La banca inicial y la apuesta base no se pueden editar: cambiarlas a mitad de
                    sesión invalidaría la progresión ya calculada.
                  </p>

                  <Field
                    label="Límite de mesa"
                    required
                    type="number"
                    min={1}
                    value={ajTableLimit}
                    onChange={(e) => setAjTableLimit(e.target.value)}
                    info={AYUDA.limiteMesa}
                  />

                  <Field
                    label="Límite de pérdida"
                    type="number"
                    min={1}
                    max={limiteActual ?? session.bankroll_start}
                    placeholder="Sin límite"
                    value={ajLossLimit}
                    onChange={(e) => setAjLossLimit(e.target.value)}
                    info={AYUDA.limitePerdida}
                    hint={
                      limiteActual === null
                        ? "Cuánto estás dispuesto a perder en esta sesión. Una vez fijado se puede bajar, no subir."
                        : `Puedes bajarlo, pero no subirlo ni quitarlo con la sesión abierta (hoy: ${CURRENCY.format(
                            limiteActual,
                          )}).`
                    }
                  />
                  {limiteInvalido || quitaLimite ? (
                    <ErrorBox
                      message={
                        quitaLimite || (limiteActual !== null && limiteNuevo! > limiteActual)
                          ? "El límite de pérdida no se puede subir ni quitar con la sesión abierta: aumentarlo para recuperar es justo lo que busca evitar."
                          : "El límite de pérdida debe ser mayor que cero y no superar la banca inicial."
                      }
                    />
                  ) : null}

                  <div className="flex gap-2">
                    <Button
                      type="submit"
                      disabled={
                        pending || !(Number(ajTableLimit) > 0) || limiteInvalido || quitaLimite
                      }
                    >
                      Guardar
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => setEditingAjustes(false)}
                    >
                      Cancelar
                    </Button>
                  </div>
                </form>
              ) : (
                <>
                  <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                    <Stat label="Banca inicial" value={CURRENCY.format(session.bankroll_start)} />
                    <Stat label="Apuesta base" value={CURRENCY.format(session.base_bet)} />
                    <Stat label="Límite de mesa" value={CURRENCY.format(session.table_limit)} />
                    <Stat
                      label="Límite de pérdida"
                      value={
                        session.loss_limit === null
                          ? "Sin fijar"
                          : CURRENCY.format(session.loss_limit)
                      }
                    />
                    {/*
                      Un escalón por progresión: las tres corren a la vez y el
                      usuario sigue la que quiera (§2.10). La plana no aparece
                      porque no tiene progresión: siempre es la apuesta base.
                    */}
                    <Stat
                      label="Escalón martingala"
                      value={String(session.stage_martingale + 1)}
                    />
                    <Stat
                      label="Escalón 2 sectores"
                      value={String(session.stage_two_sector + 1)}
                    />
                  </dl>
                  {abierta ? (
                    <div className="mt-4 flex flex-wrap gap-2">
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setAjTableLimit(String(session.table_limit));
                          setAjLossLimit(
                            session.loss_limit === null ? "" : String(session.loss_limit),
                          );
                          setEditingAjustes(true);
                        }}
                      >
                        Editar ajustes
                      </Button>
                      <Button
                        variant="ghost"
                        disabled={
                          pending ||
                          (session.stage_martingale === 0 && session.stage_two_sector === 0)
                        }
                        onClick={() =>
                          run(() => withToken((t) => sessionsApi.resetStrategy(t, sessionId)))
                        }
                      >
                        Reiniciar progresiones
                      </Button>
                      <Button
                        variant="danger"
                        disabled={pending}
                        onClick={() =>
                          run(() => withToken((t) => sessionsApi.close(t, sessionId)))
                        }
                      >
                        Cerrar sesión de mesa
                      </Button>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </Detalle>
        </div>
      </main>
    </div>
  );
}

/**
 * El teclado de resultados. Sale de `possible_outcomes`, en el orden de la
 * variante, sin suponer ningún juego.
 *
 * Seis columnas por defecto (o las de la pista `display`): en un celular de
 * 360 px cada tecla queda de más de 44 px de ancho. Los resultados que sobran
 * al repartir en filas completas van primero, en una fila que ocupa todo el
 * ancho: en la ruleta europea es el 0 solo, y en la americana el 0 y el 00 a
 * medias. El resto queda en filas completas, sin un hueco al final.
 */
function Keypad({
  config,
  columns,
  disabled,
  onPick,
}: {
  config: GameVariantResponse["config"];
  columns: number | null;
  disabled: boolean;
  onPick: (value: string) => void;
}) {
  const cols = columns ?? 6;
  const outcomes = config.possible_outcomes;
  const sobran = outcomes.length % cols;
  // Solo si esa primera fila se reparte en partes iguales.
  const ancho = sobran > 0 && cols % sobran === 0 ? cols / sobran : 1;

  return (
    <div
      data-testid="teclado"
      className="grid gap-1.5"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {outcomes.map((o, i) => (
        <button
          key={o}
          type="button"
          disabled={disabled}
          onClick={() => onPick(o)}
          style={i < sobran && ancho > 1 ? { gridColumn: `span ${ancho}` } : undefined}
          className={`flex min-h-12 items-center justify-center rounded-lg font-display text-xl font-semibold transition-transform enabled:active:scale-95 disabled:opacity-40 ${
            TONE_CLASSES[toneOf(config, o)]
          }`}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

/** Fila plegada para lo que se consulta de vez en cuando, no a cada giro. */
function Detalle({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <details className="group">
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 py-3 text-sm font-bold text-muted transition-colors hover:text-white [&::-webkit-details-marker]:hidden">
        {titulo}
        <span aria-hidden className="text-xs transition-transform group-open:rotate-180">
          ▼
        </span>
      </summary>
      <div className="pb-4">{children}</div>
    </details>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm font-bold capitalize">{value}</dd>
    </div>
  );
}

function describe(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Error inesperado";
}
