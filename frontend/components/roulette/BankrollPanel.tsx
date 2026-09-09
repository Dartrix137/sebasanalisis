"use client";

/**
 * Panel de gestión de banca (§2.8).
 *
 * Reglas de producto que este archivo hace cumplir visualmente:
 * - La tabla de progresión se puede ver ANTES de comprometerse con la
 *   estrategia, con montos reales en pesos y no en unidades abstractas.
 * - El crecimiento exponencial del riesgo se advierte de forma explícita.
 * - Los escalones que la banca o la mesa no soportan se marcan en la tabla:
 *   son el punto donde la progresión deja de poder recuperarse.
 * - El disclaimer de banca viaja con la sugerencia y se muestra siempre.
 *
 * Nada de lo que se muestra aquí sugiere a qué apostar ni anticipa el
 * resultado de un giro: solo traduce la progresión elegida a un monto.
 */

import { Badge, Card, CardHeader } from "@/components/ui";
import type { BankrollStrategy } from "@/lib/types/sessions";
import type {
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
  dalembert: "D'Alembert",
  fibonacci: "Fibonacci",
  two_sector_recovery: "Recuperación de dos sectores",
};

/** Las progresiones que multiplican el dinero expuesto en cada escalón. */
const EXPONENTIAL: ReadonlySet<BankrollStrategy> = new Set<BankrollStrategy>([
  "martingale",
  "two_sector_recovery",
]);

export function BankrollPanel({
  suggestion,
  progression,
  eligibleBets,
  selectedBetId,
  onSelectBet,
}: {
  suggestion: BankrollSuggestionResponse | null;
  progression: ProgressionTableResponse | null;
  eligibleBets: EligibleBetResponse[];
  selectedBetId: string | null;
  onSelectBet: (betId: string | null) => void;
}) {
  return (
    <Card>
      <CardHeader
        title="Gestión de banca"
        subtitle="Tamaño de apuesta que exige el escalón actual de la progresión que elegiste. No sugiere a qué apostar."
      />

      {!suggestion ? (
        <p className="rounded-lg border border-dashed border-edge py-6 text-center text-xs text-muted">
          Sin datos de banca para esta sesión.
        </p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Badge>{STRATEGY_LABEL[suggestion.strategy] ?? suggestion.strategy}</Badge>
            <Badge>Escalón {suggestion.stage + 1}</Badge>
            {suggestion.sectors > 1 ? (
              <Badge>{suggestion.sectors} sectores</Badge>
            ) : null}
          </div>

          <dl className="grid grid-cols-2 gap-2">
            <Amount
              label="Apuesta del giro"
              value={MONEY(suggestion.suggested_bet)}
              emphasis
            />
            {suggestion.sectors > 1 ? (
              <Amount
                label="Por sector"
                value={MONEY(suggestion.bet_per_sector)}
              />
            ) : null}
            <Amount
              label="Arriesgado en la serie"
              value={MONEY(suggestion.cumulative_risked)}
            />
            {suggestion.ruin_probability_estimate !== null ? (
              <Amount
                label="Riesgo de agotar la banca"
                value={`${(suggestion.ruin_probability_estimate * 100).toFixed(2)} %`}
              />
            ) : null}
          </dl>

          {/*
            El riesgo de agotar la banca depende de sobre qué apuesta se juega,
            y el motor no lo decide: lo elige el usuario. Sin elección, el campo
            viaja en null y no se muestra un número inventado.
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
            La diferencia de fondo entre las dos familias de progresión, que las
            tablas de montos no dejan ver: ganar no siempre deja ganancia.
          */}
          <p className="mt-3 rounded-lg border border-edge bg-ink px-3.5 py-3 text-xs leading-relaxed text-muted">
            {suggestion.recovers_only_to_break_even ? (
              <>
                Si ganas en este escalón,{" "}
                <span className="font-bold text-white">
                  la serie vuelve a cero: recupera lo perdido y no deja ganancia.
                </span>{" "}
                La apuesta de cada escalón es justo lo que llevas perdido en el
                anterior.
              </>
            ) : suggestion.net_result_if_won > 0 ? (
              <>
                Si ganas en este escalón, la serie cierra con{" "}
                <span className="font-bold text-white">
                  {MONEY(suggestion.net_result_if_won)}
                </span>{" "}
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

          {suggestion.exceeds_bankroll || suggestion.exceeds_table_limit ? (
            <p
              role="alert"
              className="mt-3 rounded-lg border border-table-red/40 bg-table-red/10 px-3.5 py-3 text-xs leading-relaxed text-white"
            >
              {suggestion.exceeds_bankroll
                ? "Este escalón supera la banca disponible. "
                : ""}
              {suggestion.exceeds_table_limit
                ? "Este escalón supera el límite de la mesa. "
                : ""}
              La progresión no se puede sostener: es exactamente donde toda
              progresión se rompe.
            </p>
          ) : null}

          {suggestion.risk_warning ? (
            <p className="mt-3 rounded-lg border border-signal-medium/40 bg-signal-medium/10 px-3.5 py-3 text-xs leading-relaxed text-white">
              {suggestion.risk_warning}
            </p>
          ) : (
            <p className="mt-3 text-xs leading-relaxed text-muted">
              {suggestion.disclaimer}
            </p>
          )}

          {progression ? (
            <ProgressionDetails progression={progression} currentStage={suggestion.stage} />
          ) : null}
        </>
      )}
    </Card>
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

/**
 * Tabla de progresión con montos reales. Se muestra plegada pero disponible en
 * todo momento: §2.8 exige que el usuario pueda ver el costo de cada escalón
 * antes de comprometerse con la estrategia.
 */
export function ProgressionDetails({
  progression,
  currentStage = null,
  open = false,
}: {
  progression: ProgressionTableResponse;
  currentStage?: number | null;
  open?: boolean;
}) {
  const esExponencial = EXPONENTIAL.has(progression.strategy);

  return (
    <details className="mt-4" open={open}>
      <summary className="cursor-pointer text-xs font-bold text-muted hover:text-white">
        Ver la tabla de progresión con montos reales
      </summary>

      {esExponencial ? (
        <p className="mt-3 rounded-lg border border-signal-medium/40 bg-signal-medium/10 px-3.5 py-3 text-xs leading-relaxed text-white">
          Esta progresión crece de forma exponencial: cada escalón multiplica el
          dinero expuesto. Con esta banca soporta{" "}
          <span className="font-bold">{progression.max_affordable_stages}</span>{" "}
          {progression.max_affordable_stages === 1 ? "escalón" : "escalones"}{" "}
          antes de agotarse.
        </p>
      ) : (
        <p className="mt-3 text-xs leading-relaxed text-muted">
          Con esta banca la progresión soporta{" "}
          <span className="font-bold text-white">{progression.max_affordable_stages}</span>{" "}
          {progression.max_affordable_stages === 1 ? "escalón" : "escalones"}{" "}
          antes de agotarse.
        </p>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[22rem] border-collapse text-xs">
          <caption className="sr-only">
            Progresión de {STRATEGY_LABEL[progression.strategy] ?? progression.strategy}{" "}
            con apuesta base de {MONEY(progression.base_bet)}
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
    </details>
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
        <td className="py-1.5 pr-2 text-right tabular-nums">
          {MONEY(row.bet_per_sector)}
        </td>
      ) : null}
      <td className="py-1.5 pr-2 text-right tabular-nums">{MONEY(row.total_bet)}</td>
      <td className="py-1.5 text-right font-bold tabular-nums">
        {MONEY(row.cumulative_loss)}
      </td>
    </tr>
  );
}
