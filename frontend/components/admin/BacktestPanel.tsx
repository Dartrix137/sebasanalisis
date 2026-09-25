"use client";

/**
 * Métricas internas del motor de recomendación (§2.10, §9 del comparativo).
 *
 * **Sólo admin: nada de esto se muestra al cliente.** Es el control de
 * honestidad del producto — responde si el motor aporta información útil o si
 * sólo describe el pasado.
 *
 * El ROI es el número que hay que saber leer, y por eso la referencia de la
 * ventaja de la casa se dibuja al lado y no en una nota al pie: en una mesa sin
 * sesgo, el ROI de cualquier apuesta es −1/37 haga lo que haga el motor. Un ROI
 * cercano a esa cifra es el resultado esperado, no un fallo.
 */

import { useCallback, useEffect, useState } from "react";

import { Button, Card, ErrorBox } from "@/components/ui";
import { adminApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type { GameVariantResponse } from "@/lib/types/games";
import type {
  BacktestBandRow,
  BacktestReport,
  BacktestSource,
  BacktestTally,
  SignalBand,
} from "@/lib/types/suggestions";

const PCT = (n: number) => `${(n * 100).toFixed(1)} %`;
const SIGNED = (n: number) => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(3)}`;

const BAND_LABEL: Record<SignalBand, string> = {
  none: "Sin señal",
  weak: "Débil",
  medium: "Media",
  strong: "Fuerte",
};

export function BacktestPanel({ variants }: { variants: GameVariantResponse[] }) {
  const { withToken } = useSession();
  const [variantId, setVariantId] = useState<string>("");
  const [source, setSource] = useState<BacktestSource>("sessions");
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const run = useCallback(async () => {
    setPending(true);
    setError(null);
    try {
      const r = await withToken((t) =>
        adminApi.backtest(t, {
          variantId: variantId || undefined,
          source,
          limit: source === "simulated" ? 100 : 50,
        }),
      );
      setReport(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error inesperado");
      setReport(null);
    } finally {
      setPending(false);
    }
  }, [withToken, variantId, source]);

  useEffect(() => {
    if (variants.length > 0 && variantId === "") setVariantId(variants[0].id);
  }, [variants, variantId]);

  return (
    <Card>
      <header className="mb-4">
        <h2 className="text-base font-bold text-white">
          Backtest del motor de recomendación
        </h2>
        <p className="mt-1 text-sm text-muted">
          Métrica interna. No se muestra al cliente.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="mb-1.5 block text-xs font-bold text-white">Variante</span>
          <select
            value={variantId}
            onChange={(e) => setVariantId(e.target.value)}
            className="rounded-lg border border-edge bg-ink-sunken px-3 py-2 text-sm text-white outline-none focus:border-gold/60"
          >
            {variants.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="mb-1.5 block text-xs font-bold text-white">Historiales</span>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value as BacktestSource)}
            className="rounded-lg border border-edge bg-ink-sunken px-3 py-2 text-sm text-white outline-none focus:border-gold/60"
          >
            <option value="sessions">Sesiones reales</option>
            <option value="simulated">Ruedas justas simuladas</option>
          </select>
        </label>

        <Button type="button" onClick={run} disabled={pending || variantId === ""}>
          {pending ? "Calculando…" : "Correr backtest"}
        </Button>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-muted">
        {source === "sessions"
          ? "Las sesiones reales están fuera de la muestra con la que se calibraron los pesos, que es lo que hace que esta medición valga: los pesos se fijaron sobre simulaciones, antes de que existieran estas sesiones."
          : "Línea base: en ruedas perfectamente justas el ROI tiene que quedarse en la ventaja de la casa. Si aquí saliera una ventaja, sería un error de medición, no un hallazgo."}
      </p>

      {error ? (
        <div className="mt-4">
          <ErrorBox message={error} />
        </div>
      ) : null}

      {report ? <ReportView report={report} /> : null}
    </Card>
  );
}

function ReportView({ report }: { report: BacktestReport }) {
  if (report.sessions === 0) {
    return (
      <p className="mt-4 rounded-lg border border-dashed border-edge py-6 text-center text-sm text-muted">
        No hay historiales con giros suficientes para evaluar.
      </p>
    );
  }

  return (
    <div className="mt-4 space-y-5">
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <Stat label="Historiales" value={String(report.sessions)} />
        <Stat label="Giros evaluados" value={String(report.spins_evaluated)} />
        <Stat label="Recomendaciones" value={String(report.recommendations)} />
        <Stat label="NO APOSTAR" value={PCT(report.no_bet_rate)} />
      </dl>
      <p className="text-xs text-muted">{report.source}</p>

      <div>
        <h3 className="text-xs font-bold uppercase tracking-wider text-muted">Total</h3>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[40rem] text-xs">
            <BandHead />
            <tbody className="tabular-nums">
              <Row label="Todas" t={report.overall} noBets={report.no_bets} />
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h3 className="text-xs font-bold uppercase tracking-wider text-muted">
          Por banda de señal
        </h3>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[40rem] text-xs">
            <BandHead />
            <tbody className="tabular-nums">
              {report.by_band.map((b: BacktestBandRow) => (
                <Row key={b.band} label={BAND_LABEL[b.band]} t={b} noBets={b.no_bets} />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="rounded-lg border border-edge bg-ink px-3.5 py-3 text-xs leading-relaxed text-muted">
        <span className="font-bold text-white">
          Cómo leer el ROI: en una mesa sin sesgo, el de cualquier apuesta es{" "}
          {SIGNED(report.house_edge_reference)}.
        </span>{" "}
        Un ROI cercano a esa cifra es el resultado esperado — significa que el motor
        no encontró estructura donde no la hay. Ninguna progresión ni ningún umbral
        cambia esa ventaja. Umbrales aplicados: débil {Math.round(report.weak_threshold)},
        medio {Math.round(report.threshold)}.
      </p>
    </div>
  );
}

function BandHead() {
  return (
    <thead>
      <tr className="text-left text-muted">
        <th className="py-1 font-normal">Banda</th>
        <th className="py-1 font-normal">Recom.</th>
        <th className="py-1 font-normal">Aciertos</th>
        <th className="py-1 font-normal">Fallos</th>
        <th className="py-1 font-normal">Coincidencia</th>
        <th className="py-1 font-normal">ROI</th>
        <th className="py-1 font-normal">Unidades</th>
        <th className="py-1 font-normal">Caída máx.</th>
        <th className="py-1 font-normal">NO APOSTAR</th>
      </tr>
    </thead>
  );
}

function Row({
  label,
  t,
  noBets,
}: {
  label: string;
  t: BacktestTally;
  noBets: number;
}) {
  const vacia = t.recommendations === 0;
  return (
    <tr className="border-t border-edge/60">
      <td className="py-1.5 font-bold text-white">{label}</td>
      <td className="py-1.5 text-muted">{t.recommendations}</td>
      <td className="py-1.5 text-muted">{vacia ? "—" : t.hits}</td>
      <td className="py-1.5 text-muted">{vacia ? "—" : t.misses}</td>
      <td className="py-1.5 text-muted">{vacia ? "—" : PCT(t.hit_rate)}</td>
      <td
        className={`py-1.5 ${vacia ? "text-muted" : t.roi >= 0 ? "text-signal-strong" : "text-table-red"}`}
      >
        {vacia ? "—" : SIGNED(t.roi)}
      </td>
      <td className="py-1.5 text-muted">{vacia ? "—" : t.units.toFixed(1)}</td>
      <td className="py-1.5 text-muted">{vacia ? "—" : t.max_drawdown.toFixed(1)}</td>
      <td className="py-1.5 text-muted">{noBets}</td>
    </tr>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-edge bg-ink px-3 py-2.5">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm font-bold tabular-nums text-white">{value}</dd>
    </div>
  );
}
