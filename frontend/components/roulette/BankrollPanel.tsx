"use client";

/**
 * Panel de gestión de banca (§2.8), con una pestaña por gestión (§2.10: la mesa
 * ofrece las tres a la vez y el usuario sigue la que quiera).
 *
 * Reglas de producto que este archivo hace cumplir visualmente:
 * - La tabla de progresión se puede ver ANTES de comprometerse con una gestión,
 *   con montos reales en pesos y no en unidades abstractas.
 * - El crecimiento exponencial del riesgo se advierte de forma explícita.
 * - Los escalones que la banca o la mesa no soportan se marcan en la tabla:
 *   son el punto donde la progresión deja de poder recuperarse.
 * - El disclaimer de banca viaja con la sugerencia y se muestra siempre.
 */

import { useEffect, useState } from "react";

import { Badge, Card, CardHeader, ErrorBox } from "@/components/ui";
import { bankrollApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type { UUID } from "@/lib/types/auth";
import type { BankrollStrategy } from "@/lib/types/sessions";
import type {
  BankrollAlertLevel,
  BankrollSuggestionResponse,
  EligibleBetResponse,
  ProgressionRowResponse,
  ProgressionTableResponse,
} from "@/lib/types/suggestions";

const MONEY = (n: number) =>
  new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency: "COP",
    maximumFractionDigits: 0,
  }).format(n);

export const STRATEGY_LABEL: Record<BankrollStrategy, string> = {
  flat: "Apuesta plana",
  martingale: "Martingala",
  two_sector_recovery: "Recuperación de 2 sectores",
};

const TAB_LABEL: Record<BankrollStrategy, string> = {
  flat: "Plana",
  martingale: "Martingala",
  two_sector_recovery: "2 sectores",
};

/** Orden de menú, el mismo que usa la tarjeta de recomendación. */
export const STRATEGY_ORDER: readonly BankrollStrategy[] = [
  "flat",
  "martingale",
  "two_sector_recovery",
];

/** Las progresiones que multiplican el dinero expuesto en cada escalón. */
const EXPONENTIAL: ReadonlySet<BankrollStrategy> = new Set<BankrollStrategy>([
  "martingale",
  "two_sector_recovery",
]);

const ALERT_STYLES: Record<BankrollAlertLevel, { box: string; tag: string; label: string }> = {
  critical: {
    box: "border-table-red/40 bg-table-red/10 text-white",
    tag: "text-table-red",
    label: "Crítico",
  },
  caution: {
    box: "border-signal-medium/40 bg-signal-medium/10 text-white",
    tag: "text-signal-medium",
    label: "Atención",
  },
  info: {
    box: "border-edge bg-ink text-muted",
    tag: "text-muted",
    label: "Nota",
  },
};

export function StrategyTabs({
  value,
  onChange,
}: {
  value: BankrollStrategy;
  onChange: (s: BankrollStrategy) => void;
}) {
  return (
    <div role="tablist" aria-label="Gestión de banca" className="flex gap-1 rounded-lg bg-ink p-1">
      {STRATEGY_ORDER.map((s) => {
        const activa = s === value;
        return (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={activa}
            onClick={() => onChange(s)}
            className={`flex-1 rounded-md px-2 py-1.5 text-xs font-bold transition-colors ${
              activa ? "bg-gold text-gold-ink" : "text-muted hover:text-white"
            }`}
          >
            {TAB_LABEL[s]}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Las tres tablas de progresión antes de abrir la mesa. §2.8 exige que el costo
 * de cada escalón se vea antes de comprometerse con una gestión.
 */
export function ProgressionPreviewTabs({
  tables,
}: {
  tables: Partial<Record<BankrollStrategy, ProgressionTableResponse>>;
}) {
  const [tab, setTab] = useState<BankrollStrategy>("flat");
  const tabla = tables[tab];

  return (
    <details className="rounded-lg border border-edge bg-ink px-3.5 py-3">
      <summary className="cursor-pointer text-xs font-bold text-muted hover:text-white">
        Ver la tabla de progresión de cada gestión, con montos reales
      </summary>
      <div className="mt-3">
        <StrategyTabs value={tab} onChange={setTab} />
        {tabla ? (
          <ProgressionTable progression={tabla} />
        ) : (
          <p className="mt-3 text-xs text-muted">Calculando…</p>
        )}
      </div>
    </details>
  );
}

interface PanelData {
  strategy: BankrollStrategy;
  suggestion: BankrollSuggestionResponse;
  progression: ProgressionTableResponse;
  eligibleBets: EligibleBetResponse[];
}

/**
 * Gestión de banca de una sesión abierta. Pide sus propios datos para la
 * pestaña visible; `version` cambia cuando algo de la sesión que afecta a los
 * montos cambió (un giro, una apuesta resuelta, los límites).
 */
export function BankrollPanel({ sessionId, version }: { sessionId: UUID; version: string }) {
  const { withToken } = useSession();
  const [tab, setTab] = useState<BankrollStrategy>("flat");
  // Sobre qué apuesta se estima el riesgo de agotar la banca. Null a propósito:
  // sin elección no se muestra ninguna estimación.
  const [selectedBetId, setSelectedBetId] = useState<string | null>(null);
  const [data, setData] = useState<PanelData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    (async () => {
      const eligibleBets = await withToken((t) => bankrollApi.eligibleBets(t, sessionId, tab));
      // Una apuesta que no está en la lista de esta gestión daría un 422.
      const betId =
        selectedBetId !== null && eligibleBets.some((b) => b.id === selectedBetId)
          ? selectedBetId
          : undefined;
      const [suggestion, progression] = await Promise.all([
        withToken((t) => bankrollApi.suggestion(t, sessionId, { betId, strategy: tab })),
        withToken((t) =>
          bankrollApi.progression(t, sessionId, { stages: 10, betId, strategy: tab }),
        ),
      ]);
      if (cancelado) return;
      setData({ strategy: tab, suggestion, progression, eligibleBets });
      setError(null);
    })().catch((e: unknown) => {
      if (!cancelado) setError(e instanceof Error ? e.message : "Error inesperado");
    });
    return () => {
      cancelado = true;
    };
  }, [withToken, sessionId, tab, selectedBetId, version]);

  return (
    <Card>
      <CardHeader
        title="Gestión de banca"
        subtitle="Cada gestión con su escalón actual, sus avisos y la tabla completa. Ninguna cambia la ventaja de la casa."
      />

      <StrategyTabs
        value={tab}
        onChange={(s) => {
          setTab(s);
          setSelectedBetId(null);
        }}
      />

      <div className="mt-4">
        {error ? <ErrorBox message={error} /> : null}
        {data === null || data.strategy !== tab ? (
          <p className="py-6 text-center text-xs text-muted">Calculando…</p>
        ) : (
          <StrategyDetail
            data={data}
            selectedBetId={selectedBetId}
            onSelectBet={setSelectedBetId}
          />
        )}
      </div>
    </Card>
  );
}

function StrategyDetail({
  data,
  selectedBetId,
  onSelectBet,
}: {
  data: PanelData;
  selectedBetId: string | null;
  onSelectBet: (betId: string | null) => void;
}) {
  const { suggestion, progression, eligibleBets } = data;
  const plana = suggestion.strategy === "flat";

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge>{STRATEGY_LABEL[suggestion.strategy]}</Badge>
        {plana ? null : <Badge>Escalón {suggestion.stage + 1}</Badge>}
        {suggestion.sectors > 1 ? <Badge>{suggestion.sectors} sectores</Badge> : null}
      </div>

      <dl className="grid grid-cols-2 gap-2">
        <Amount label="Apuesta del escalón" value={MONEY(suggestion.suggested_bet)} emphasis />
        {suggestion.sectors > 1 ? (
          <Amount label="Por sector" value={MONEY(suggestion.bet_per_sector)} />
        ) : null}
        <Amount label="Arriesgado en la serie" value={MONEY(suggestion.cumulative_risked)} />
        {suggestion.ruin_probability_estimate !== null ? (
          <Amount
            label="Riesgo de agotar la banca"
            value={`${(suggestion.ruin_probability_estimate * 100).toFixed(2)} %`}
          />
        ) : null}
      </dl>

      <p className="mt-2 text-xs leading-relaxed text-muted">
        {suggestion.sectors > 1
          ? "Montos sobre dos zonas a la vez, como dos docenas o dos columnas."
          : "Montos sobre una apuesta de una sola zona. Si la recomendación cubre dos zonas, la tarjeta de recomendación ya los ajusta."}
      </p>

      {plana ? null : (
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <span>
            Si apuestas con esta gestión y pierdes →{" "}
            <span className="font-bold text-white">
              {MONEY(suggestion.next_if_lost.suggested_bet)}
            </span>
          </span>
          <span>
            Si ganas →{" "}
            <span className="font-bold text-white">
              {MONEY(suggestion.next_if_won.suggested_bet)}
            </span>
          </span>
        </p>
      )}

      {/*
        El riesgo de agotar la banca depende de sobre qué apuesta se juega. Sin
        elección, el campo viaja en null y no se muestra un número inventado.
      */}
      {eligibleBets.length > 0 ? (
        <label className="mt-3 block">
          <span className="mb-1.5 block text-xs font-bold text-white">
            Calcular el riesgo sobre esta apuesta
          </span>
          <select
            value={selectedBetId ?? ""}
            onChange={(e) => onSelectBet(e.target.value || null)}
            className="w-full rounded-lg border border-edge bg-ink-sunken px-3 py-2 text-xs text-white outline-none focus:border-gold/60"
          >
            <option value="">Sin elegir — no se estima el riesgo</option>
            {eligibleBets.map((b) => (
              <option key={b.id} value={b.id}>
                {b.label} — {(b.theoretical_probability * 100).toFixed(1)} % teórico
              </option>
            ))}
          </select>
          <span className="mt-1 block text-xs text-muted">
            Todas cubren la misma cantidad de resultados: elegir una u otra no
            cambia el riesgo, solo sobre qué apuesta se calcula.
          </span>
        </label>
      ) : null}

      {/*
        La diferencia de fondo entre las familias de progresión, que las tablas
        de montos no dejan ver: ganar no siempre deja ganancia.
      */}
      <p className="mt-3 rounded-lg border border-edge bg-ink px-3.5 py-3 text-xs leading-relaxed text-muted">
        {suggestion.recovers_only_to_break_even ? (
          <>
            Si ganas en este escalón,{" "}
            <span className="font-bold text-white">
              la serie vuelve a cero: recupera lo perdido y no deja ganancia.
            </span>
          </>
        ) : suggestion.net_result_if_won > 0 ? (
          <>
            Si ganas en este escalón, la serie cierra con{" "}
            <span className="font-bold text-white">{MONEY(suggestion.net_result_if_won)}</span>{" "}
            de ganancia.
          </>
        ) : (
          <>
            Si ganas en este escalón, la serie{" "}
            <span className="font-bold text-white">
              aún cierra en {MONEY(suggestion.net_result_if_won)}
            </span>
            : esta progresión no recupera todo lo perdido al acertar.
          </>
        )}
      </p>

      {suggestion.alerts.length > 0 ? (
        <div className="mt-3 space-y-1.5">
          {suggestion.alerts.map((a) => (
            <Alert key={a.code} alerta={a} />
          ))}
        </div>
      ) : null}

      {suggestion.risk_warning ? (
        <p className="mt-3 rounded-lg border border-signal-medium/40 bg-signal-medium/10 px-3.5 py-3 text-xs leading-relaxed text-white">
          {suggestion.risk_warning}
        </p>
      ) : (
        <p className="mt-3 text-xs leading-relaxed text-muted">{suggestion.disclaimer}</p>
      )}

      <details className="mt-4">
        <summary className="cursor-pointer text-xs font-bold text-muted hover:text-white">
          Ver la tabla de progresión con montos reales
        </summary>
        <ProgressionTable
          progression={progression}
          currentStage={plana ? null : suggestion.stage}
        />
      </details>
    </>
  );
}

function Alert({ alerta }: { alerta: BankrollSuggestionResponse["alerts"][number] }) {
  const estilo = ALERT_STYLES[alerta.level];
  return (
    <p
      role={alerta.level === "critical" ? "alert" : undefined}
      className={`rounded-lg border px-3 py-2 text-xs leading-relaxed ${estilo.box}`}
    >
      <span className={`mr-1.5 font-bold uppercase tracking-wide ${estilo.tag}`}>
        {estilo.label}
      </span>
      {alerta.message}
    </p>
  );
}

function Amount({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="rounded-lg border border-edge bg-ink px-3 py-2.5">
      <dt className="text-xs text-muted">{label}</dt>
      <dd
        className={`mt-0.5 font-bold ${emphasis ? "text-base text-gold" : "text-sm text-white"}`}
      >
        {value}
      </dd>
    </div>
  );
}

/** Tabla de progresión con montos reales, de una gestión. */
function ProgressionTable({
  progression,
  currentStage = null,
}: {
  progression: ProgressionTableResponse;
  currentStage?: number | null;
}) {
  const esExponencial = EXPONENTIAL.has(progression.strategy);

  return (
    <div>
      {esExponencial ? (
        <p className="mt-3 rounded-lg border border-signal-medium/40 bg-signal-medium/10 px-3.5 py-3 text-xs leading-relaxed text-white">
          Esta progresión crece de forma exponencial: cada escalón multiplica el
          dinero expuesto. Con esta banca soporta{" "}
          <span className="font-bold">{progression.max_affordable_stages}</span>{" "}
          {progression.max_affordable_stages === 1 ? "escalón" : "escalones"} antes de
          agotarse.
        </p>
      ) : (
        <p className="mt-3 text-xs leading-relaxed text-muted">
          La apuesta no cambia entre escalones. Con esta banca alcanza para{" "}
          <span className="font-bold text-white">{progression.max_affordable_stages}</span>{" "}
          {progression.max_affordable_stages === 1 ? "apuesta perdida" : "apuestas perdidas"}{" "}
          seguidas.
        </p>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[22rem] border-collapse text-xs">
          <caption className="sr-only">
            Progresión de {STRATEGY_LABEL[progression.strategy]} con apuesta base de{" "}
            {MONEY(progression.base_bet)}
          </caption>
          <thead>
            <tr className="text-left text-muted">
              <th scope="col" className="py-1.5 pr-2 font-bold">
                Escalón
              </th>
              {progression.sectors > 1 ? (
                <th scope="col" className="py-1.5 pr-2 text-right font-bold">
                  Por sector
                </th>
              ) : null}
              <th scope="col" className="py-1.5 pr-2 text-right font-bold">
                Apuesta
              </th>
              <th scope="col" className="py-1.5 text-right font-bold">
                Perdido si falla
              </th>
            </tr>
          </thead>
          <tbody>
            {progression.rows.map((row) => (
              <ProgressionRow
                key={row.stage}
                row={row}
                sectors={progression.sectors}
                isCurrent={row.stage === currentStage}
              />
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs leading-relaxed text-muted">{progression.disclaimer}</p>
    </div>
  );
}

function ProgressionRow({
  row,
  sectors,
  isCurrent,
}: {
  row: ProgressionRowResponse;
  sectors: number;
  isCurrent: boolean;
}) {
  const inalcanzable = row.exceeds_bankroll || row.exceeds_table_limit;
  const motivo = [
    row.exceeds_bankroll ? "supera la banca" : null,
    row.exceeds_table_limit ? "supera el límite de la mesa" : null,
  ]
    .filter(Boolean)
    .join(" y ");

  return (
    <tr
      className={`border-t border-edge ${inalcanzable ? "text-table-red" : "text-white"} ${
        isCurrent ? "bg-gold/10" : ""
      }`}
      title={inalcanzable ? `Este escalón ${motivo}` : undefined}
    >
      <th scope="row" className="py-1.5 pr-2 text-left font-bold">
        {row.stage + 1}
        {isCurrent ? <span className="ml-1 text-gold">·</span> : null}
      </th>
      {sectors > 1 ? (
        <td className="py-1.5 pr-2 text-right tabular-nums">{MONEY(row.bet_per_sector)}</td>
      ) : null}
      <td className="py-1.5 pr-2 text-right tabular-nums">{MONEY(row.total_bet)}</td>
      <td className="py-1.5 text-right font-bold tabular-nums">{MONEY(row.cumulative_loss)}</td>
    </tr>
  );
}
