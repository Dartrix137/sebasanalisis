"use client";

/**
 * Formulario de creación de una sesión de mesa.
 *
 * El modo dos-sectores y la progresión de recuperación van juntos o no van
 * (§2.8): la UI los ata para que no se pueda mandar una combinación que el
 * backend rechazaría con un 422.
 */

import { useEffect, useState } from "react";

import { ProgressionDetails } from "@/components/roulette/BankrollPanel";
import { Button, ErrorBox, Field } from "@/components/ui";
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

const ESTRATEGIAS: { value: BankrollStrategy; label: string; nota: string }[] = [
  { value: "flat", label: "Plana", nota: "Siempre la misma apuesta base." },
  { value: "martingale", label: "Martingala", nota: "Dobla tras perder. Solo pagos 1:1." },
  { value: "dalembert", label: "D'Alembert", nota: "Sube y baja una unidad." },
  { value: "fibonacci", label: "Fibonacci", nota: "Avanza por la secuencia al perder." },
  {
    value: "two_sector_recovery",
    label: "Recuperación dos sectores",
    nota: "Para dos docenas o dos columnas. El riesgo crece muy rápido.",
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
  const [strategy, setStrategy] = useState<BankrollStrategy>("flat");
  const [initialRaw, setInitialRaw] = useState("");
  const [initialOrder, setInitialOrder] = useState<EntryOrder | null>(null);

  const initialValues = parseValues(initialRaw);
  // Se valida aquí solo para avisar antes de enviar; el backend es la autoridad
  // y rechaza la carga entera si algún valor no pertenece a la variante.
  const posibles = new Set(variant.config.possible_outcomes);
  const invalidos = [...new Set(initialValues.filter((v) => !posibles.has(v)))];
  const faltaOrden = initialValues.length > 0 && initialOrder === null;

  const esDosSectores = strategy === "two_sector_recovery";
  const apuestaExcedeBanca = Number(baseBet) > Number(bankroll);

  const { withToken } = useSession();
  const [progression, setProgression] = useState<ProgressionTableResponse | null>(null);

  // §2.8: la tabla de progresión con montos reales debe poder verse ANTES de
  // activar la estrategia, no después de comprometerse con ella. Se recalcula
  // en el backend para no duplicar aquí las fórmulas del motor.
  useEffect(() => {
    const baseBetNum = Number(baseBet);
    const bankrollNum = Number(bankroll);
    const tableLimitNum = Number(tableLimit);
    if (!(baseBetNum > 0) || !(bankrollNum > 0)) {
      setProgression(null);
      return;
    }

    let cancelado = false;
    const t = setTimeout(() => {
      withToken((token) =>
        bankrollApi.progressionPreview(token, {
          strategy,
          baseBet: baseBetNum,
          bankroll: bankrollNum,
          tableLimit: tableLimitNum > 0 ? tableLimitNum : undefined,
          stages: 10,
        }),
      )
        .then((tabla) => {
          if (!cancelado) setProgression(tabla);
        })
        // La vista previa es informativa: si falla, el formulario sigue usable.
        .catch(() => {
          if (!cancelado) setProgression(null);
        });
    }, 300);

    return () => {
      cancelado = true;
      clearTimeout(t);
    };
  }, [withToken, strategy, baseBet, bankroll, tableLimit]);

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
          strategy,
          // §2.8: el modo se deriva de la estrategia, nunca se eligen por separado.
          strategy_mode: esDosSectores ? "two_sector" : "single",
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
        hint="Opcional. Sirve para distinguir varias mesas abiertas."
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <Field
          label="Banca inicial"
          required
          type="number"
          min={1}
          value={bankroll}
          onChange={(e) => setBankroll(e.target.value)}
        />
        <Field
          label="Apuesta base"
          required
          type="number"
          min={1}
          value={baseBet}
          onChange={(e) => setBaseBet(e.target.value)}
        />
        <Field
          label="Límite de mesa"
          required
          type="number"
          min={1}
          value={tableLimit}
          onChange={(e) => setTableLimit(e.target.value)}
          hint="Revísalo dentro del juego antes de usar una progresión."
        />
      </div>

      <label className="block">
        <span className="mb-1.5 block text-sm font-bold text-white">Gestión de banca</span>
        <select
          value={strategy}
          onChange={(e) => setStrategy(e.target.value as BankrollStrategy)}
          className="w-full rounded-lg border border-edge bg-ink-sunken px-3.5 py-2.5 text-sm text-white outline-none focus:border-gold/60"
        >
          {ESTRATEGIAS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-xs text-muted">
          {ESTRATEGIAS.find((s) => s.value === strategy)?.nota}
        </span>
      </label>

      {progression ? (
        <ProgressionDetails progression={progression} open={esDosSectores} />
      ) : null}

      {/*
        Carga inicial (§3.5). Los números los escribe el usuario: el proyecto no
        lee pantallazos ni llama a ninguna IA.
      */}
      <label className="block">
        <span className="mb-1.5 block text-sm font-bold text-white">
          Números ya observados en la mesa
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
      {faltaOrden ? (
        <ErrorBox message="Indica en qué orden escribiste los números antes de empezar." />
      ) : null}
      {error ? <ErrorBox message={error} /> : null}

      <div className="flex gap-2">
        <Button
          type="submit"
          disabled={pending || apuestaExcedeBanca || faltaOrden || invalidos.length > 0}
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
