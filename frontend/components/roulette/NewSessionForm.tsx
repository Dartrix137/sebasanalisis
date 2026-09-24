"use client";

/**
 * Formulario de creación de una sesión de mesa.
 *
 * El modo dos-sectores y la progresión de recuperación van juntos o no van
 * (§2.8): la UI los ata para que no se pueda mandar una combinación que el
 * backend rechazaría con un 422.
 */

import { useEffect, useState } from "react";

import { ProgressionPreviewTabs, STRATEGY_ORDER } from "@/components/roulette/BankrollPanel";
import { Button, ErrorBox, Field, InfoTip } from "@/components/ui";
import { bankrollApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type { ProgressionTableResponse } from "@/lib/types/suggestions";
import type { BankrollStrategy, CreateSessionRequest } from "@/lib/types/sessions";
import type { GameVariantResponse } from "@/lib/types/games";
import type { BulkSpinsRequest, EntryOrder } from "@/lib/types/spins";

/** Separadores aceptados, iguales a los del backend (§3.5). */
const SEPARATORS = /[\s,;]+/;

/**
 * Cuántos de los giros más recientes mira el motor al calcular. Es un tope por
 * rendimiento, no una ventana con peso plano: dentro de ella cada giro pesa
 * según su antigüedad (§2.3).
 *
 * Va fijo y no se expone en el formulario: es un detalle interno que no se puede
 * decidir bien sin conocer el motor, y el default cubre el uso normal.
 */
const WINDOW_SIZE = 50;

function parseValues(raw: string): string[] {
  return raw.trim().split(SEPARATORS).filter(Boolean);
}

/** Qué es cada dato de la mesa. Se reusa en los ajustes de la sesión abierta. */
export const AYUDA = {
  nombre: "Solo sirve para distinguir tus mesas en el menú. No afecta ningún cálculo.",
  banca:
    "El dinero total que traes a esta sesión. Se actualiza sola con las apuestas que registres, y las gestiones la usan para calcular hasta qué escalón te alcanza.",
  apuestaBase:
    "Tu unidad de apuesta. Es lo que pide siempre la gestión plana, y el primer escalón de la martingala y de la recuperación de 2 sectores (en esa, por cada sector).",
  limiteMesa:
    "La apuesta máxima que la mesa acepta en una sola casilla (un color, una docena…). Lo fija el casino y aparece en la información de la mesa dentro del juego. Los escalones que lo superan se marcan en rojo: ahí la mesa no te dejaría apostar el monto y la progresión se rompe.",
  limitePerdida:
    "Cuánto estás dispuesto a perder en esta sesión, contado desde la banca inicial. La mesa te avisa al acercarte. Con la sesión abierta se puede bajar, pero no subir ni quitar.",
  numerosObservados:
    "Los resultados que ya muestra el historial de la mesa antes de que empieces a registrar. Le dan al motor datos desde el primer giro, en vez de empezar de cero.",
} as const;

export const ESTRATEGIAS: {
  value: BankrollStrategy;
  label: string;
  nota: string;
  /** Explicación completa para el panel expandible — no solo el resumen de una línea. */
  detalle: string;
}[] = [
  {
    value: "flat",
    label: "Plana",
    nota: "Siempre la misma apuesta base.",
    detalle:
      "Apuesta siempre el mismo monto, gane o pierda. No intenta recuperar lo perdido en el giro anterior, así que es la opción con el crecimiento de apuesta más predecible y el riesgo de agotar la banca más bajo de las que ofrece esta app.",
  },
  {
    value: "martingale",
    label: "Martingala",
    nota: "Dobla tras perder. Solo pagos 1:1.",
    detalle:
      "Duplica la apuesta después de cada pérdida y vuelve a la apuesta base tras ganar. Solo tiene sentido en apuestas que pagan 1:1 (color, par/impar, alto/bajo): ahí, ganar en cualquier escalón recupera toda la serie y deja como ganancia neta exactamente la apuesta base. El riesgo crece de forma exponencial — pocas pérdidas seguidas ya exigen apuestas muy altas, y el límite de la mesa o la banca disponible pueden cortar la serie antes de que llegue la recuperación.",
  },
  {
    value: "two_sector_recovery",
    label: "Recuperación de 2 sectores",
    nota: "Para dos docenas o dos columnas. El riesgo crece muy rápido.",
    detalle:
      "Pensada para apostar a la vez a dos docenas o dos columnas (pago 2:1). Como la ganancia neta al acertar es solo una fracción de lo apostado, la progresión de recuperación es distinta a la martingala clásica: duplicar no alcanza. El riesgo crece de forma extremadamente rápida — pocos escalones ya representan montos muy altos frente a la apuesta base.",
  },
];

export function NewSessionForm({
  variant,
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  variant: GameVariantResponse;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (body: CreateSessionRequest, initial: BulkSpinsRequest | null) => void;
}) {
  const [name, setName] = useState("");
  const [bankroll, setBankroll] = useState("100000");
  const [baseBet, setBaseBet] = useState("1000");
  const [tableLimit, setTableLimit] = useState("500000");
  const [lossLimit, setLossLimit] = useState("");
  const [initialRaw, setInitialRaw] = useState("");
  const [initialOrder, setInitialOrder] = useState<EntryOrder | null>(null);

  const initialValues = parseValues(initialRaw);
  // Se valida aquí solo para avisar antes de enviar; el backend es la autoridad
  // y rechaza la carga entera si algún valor no pertenece a la variante.
  const posibles = new Set(variant.config.possible_outcomes);
  const invalidos = [...new Set(initialValues.filter((v) => !posibles.has(v)))];
  const faltaOrden = initialValues.length > 0 && initialOrder === null;

  const apuestaExcedeBanca = Number(baseBet) > Number(bankroll);
  const limiteExcedeBanca = lossLimit !== "" && Number(lossLimit) > Number(bankroll);

  const { withToken } = useSession();
  const [progressions, setProgressions] = useState<
    Partial<Record<BankrollStrategy, ProgressionTableResponse>> | null
  >(null);

  // §2.8: la tabla de progresión con montos reales debe poder verse ANTES de
  // abrir la mesa, una por gestión. Se calcula en el backend para no duplicar
  // aquí las fórmulas del motor.
  useEffect(() => {
    const baseBetNum = Number(baseBet);
    const bankrollNum = Number(bankroll);
    const tableLimitNum = Number(tableLimit);
    if (!(baseBetNum > 0) || !(bankrollNum > 0)) {
      setProgressions(null);
      return;
    }

    let cancelado = false;
    const t = setTimeout(() => {
      Promise.all(
        STRATEGY_ORDER.map((strategy) =>
          withToken((token) =>
            bankrollApi.progressionPreview(token, {
              strategy,
              baseBet: baseBetNum,
              bankroll: bankrollNum,
              tableLimit: tableLimitNum > 0 ? tableLimitNum : undefined,
              stages: 10,
            }),
          ),
        ),
      )
        .then((tablas) => {
          if (!cancelado) {
            setProgressions(Object.fromEntries(tablas.map((tb) => [tb.strategy, tb])));
          }
        })
        // La vista previa es informativa: si falla, el formulario sigue usable.
        .catch(() => {
          if (!cancelado) setProgressions(null);
        });
    }, 300);

    return () => {
      cancelado = true;
      clearTimeout(t);
    };
  }, [withToken, baseBet, bankroll, tableLimit]);

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(
          {
          game_variant_id: variant.id,
          name: name.trim() || null,
          window_size: WINDOW_SIZE,
          bankroll_start: Number(bankroll),
          base_bet: Number(baseBet),
          table_limit: Number(tableLimit),
          loss_limit: lossLimit === "" ? null : Number(lossLimit),
          },
          initialValues.length > 0 && initialOrder !== null
            ? { values: initialValues, order: initialOrder }
            : null,
        );
      }}
    >
      <Field
        label="Nombre de la sesión"
        placeholder="Mesa 1"
        maxLength={100}
        value={name}
        onChange={(e) => setName(e.target.value)}
        hint="Opcional."
        info={AYUDA.nombre}
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <Field
          label="Banca inicial"
          required
          type="number"
          min={1}
          value={bankroll}
          onChange={(e) => setBankroll(e.target.value)}
          info={AYUDA.banca}
        />
        <Field
          label="Apuesta base"
          required
          type="number"
          min={1}
          value={baseBet}
          onChange={(e) => setBaseBet(e.target.value)}
          info={AYUDA.apuestaBase}
        />
        <Field
          label="Límite de mesa"
          required
          type="number"
          min={1}
          value={tableLimit}
          onChange={(e) => setTableLimit(e.target.value)}
          hint="Apuesta máxima por casilla."
          info={AYUDA.limiteMesa}
          infoAlign="right"
        />
      </div>

      <Field
        label="Límite de pérdida"
        type="number"
        min={1}
        placeholder="Por ejemplo 30000"
        value={lossLimit}
        onChange={(e) => setLossLimit(e.target.value)}
        hint="Opcional, pero recomendado."
        info={AYUDA.limitePerdida}
      />

      <details className="rounded-lg border border-edge bg-ink px-3.5 py-3">
        <summary className="cursor-pointer text-xs font-bold text-muted hover:text-white">
          ¿Qué gestiones de banca vas a ver en la mesa?
        </summary>
        <div className="mt-3 space-y-3">
          {ESTRATEGIAS.map((s) => (
            <div key={s.value}>
              <p className="text-xs font-bold text-white">{s.label}</p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted">{s.detalle}</p>
            </div>
          ))}
          <p className="text-xs leading-relaxed text-muted">
            No hace falta elegir una ahora: la mesa muestra las tres a la vez con lo
            que pediría cada una, y sigues la que quieras.
          </p>
          <p className="text-xs leading-relaxed text-muted">
            Ninguna de estas progresiones cambia la probabilidad del giro ni la ventaja
            matemática de la casa: solo cambian el tamaño y la distribución de las apuestas.
          </p>
        </div>
      </details>

      {progressions ? <ProgressionPreviewTabs tables={progressions} /> : null}

      {/*
        Carga inicial (§3.5). Los números los escribe el usuario: el proyecto no
        lee pantallazos ni llama a ninguna IA.
      */}
      <label className="block">
        <span className="mb-1.5 block text-sm font-bold text-white">
          Números ya observados en la mesa
          <InfoTip label="Números ya observados en la mesa">{AYUDA.numerosObservados}</InfoTip>
        </span>
        <textarea
          value={initialRaw}
          onChange={(e) => setInitialRaw(e.target.value)}
          rows={3}
          placeholder="17, 32, 0, 15, 4"
          className="w-full rounded-lg border border-edge bg-ink-sunken px-3.5 py-2.5 text-sm text-white outline-none placeholder:text-muted/70 focus:border-gold/60"
        />
        <span className="mt-1 block text-xs text-muted">
          Opcional. Sepáralos con comas, espacios o saltos de línea. Escribe cada
          número tal como salió, repeticiones incluidas.
        </span>
      </label>

      {initialValues.length > 0 ? (
        <fieldset className="rounded-lg border border-edge bg-ink px-3.5 py-3">
          <legend className="px-1 text-xs font-bold text-white">
            ¿En qué orden los escribiste?
          </legend>
          {/*
            Se pregunta y no se adivina: el motor pondera por recencia (§2.3), y
            un orden invertido daría un análisis equivocado sin fallar visiblemente.
          */}
          <div className="space-y-1.5">
            {(
              [
                ["most_recent_last", "Del más antiguo al más reciente (el último que escribí fue el último que salió)"],
                ["most_recent_first", "Del más reciente al más antiguo (como los muestra la pantalla de la mesa)"],
              ] as const
            ).map(([valor, etiqueta]) => (
              <label key={valor} className="flex items-start gap-2 text-xs text-muted">
                <input
                  type="radio"
                  name="entry-order"
                  className="mt-0.5 accent-gold"
                  checked={initialOrder === valor}
                  onChange={() => setInitialOrder(valor)}
                />
                <span>{etiqueta}</span>
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">
            {initialValues.length}{" "}
            {initialValues.length === 1 ? "número" : "números"} detectados.
          </p>

          {/*
            El motor solo mira los últimos WINDOW_SIZE giros. Cargar más no falla
            ni se pierde nada — quedan guardados y visibles en la secuencia — pero
            los más antiguos no entran en el análisis, y sin decirlo eso pasaría
            en silencio.
          */}
          {initialValues.length > WINDOW_SIZE ? (
            <p className="mt-2 rounded-lg border border-signal-medium/40 bg-signal-medium/10 px-3 py-2 text-xs leading-relaxed text-white">
              El análisis usa los <span className="font-bold">{WINDOW_SIZE}</span> giros
              más recientes. Los {initialValues.length - WINDOW_SIZE} más antiguos
              quedarán guardados y visibles en la secuencia, pero no entrarán en las
              señales estadísticas.
            </p>
          ) : null}
        </fieldset>
      ) : null}

      {invalidos.length > 0 ? (
        <ErrorBox
          message="Hay números que no pertenecen a esta variante."
          details={invalidos}
        />
      ) : null}

      <p className="rounded-lg border border-edge bg-ink px-3.5 py-3 text-xs leading-relaxed text-muted">
        Ninguna progresión cambia la ventaja matemática de la casa. Solo modifica el tamaño y
        la distribución de las pérdidas y ganancias. Define tu límite antes de empezar y no lo
        subas para recuperar.
      </p>

      {apuestaExcedeBanca ? (
        <ErrorBox message="La apuesta base no puede superar la banca inicial." />
      ) : null}
      {limiteExcedeBanca ? (
        <ErrorBox message="El límite de pérdida no puede superar la banca inicial." />
      ) : null}
      {faltaOrden ? (
        <ErrorBox message="Indica en qué orden escribiste los números antes de empezar." />
      ) : null}
      {error ? <ErrorBox message={error} /> : null}

      <div className="flex gap-2">
        <Button
          type="submit"
          disabled={
            pending ||
            apuestaExcedeBanca ||
            limiteExcedeBanca ||
            faltaOrden ||
            invalidos.length > 0
          }
        >
          {pending ? "Creando…" : "Empezar sesión"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancelar
        </Button>
      </div>
    </form>
  );
}
