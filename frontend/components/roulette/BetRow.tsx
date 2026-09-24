"use client";

/**
 * Las apuestas reales del giro en curso (§4).
 *
 * Seguir la recomendación se anota con un toque desde su tarjeta ("Aposté
 * esto"), con el mercado y el monto de la gestión elegida. Aquí queda lo demás:
 * lo que ya está en juego y, plegado, el registro de cualquier otra apuesta —
 * la que se hace por fuera de la recomendación, o igual cuando el motor pidió
 * no apostar.
 *
 * Se admiten varias apuestas por giro, como en una mesa real. Cubrir más
 * opciones reparte el riesgo pero no lo reduce: la ventaja de la casa se aplica
 * a cada apuesta por separado, y el copy tiene que decirlo cuando el usuario
 * empieza a acumular.
 */

import { useState } from "react";

import { STRATEGY_LABEL } from "@/components/roulette/BankrollPanel";
import { Button, ErrorBox } from "@/components/ui";
import type { GameVariantConfig } from "@/lib/types/games";
import type { BetResponse, CreateBetRequest } from "@/lib/types/bets";

const MONEY = (n: number) =>
  new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency: "COP",
    maximumFractionDigits: 0,
  }).format(n);

const SELECT =
  "w-full rounded-lg border border-edge bg-ink-sunken px-3 py-2 text-sm text-white outline-none focus:border-gold/60";

export function BetRow({
  config,
  bets,
  bankrollCurrent,
  baseBet,
  recommends,
  abierta,
  pending,
  onPlace,
  onCancel,
}: {
  config: GameVariantConfig;
  bets: BetResponse[];
  bankrollCurrent: number;
  baseBet: number;
  /** Si hay una recomendación vigente: cambia el copy del registro manual. */
  recommends: boolean;
  abierta: boolean;
  pending: boolean;
  onPlace: (body: CreateBetRequest) => void;
  onCancel: (betId: string) => void;
}) {
  const [formOpen, setFormOpen] = useState(false);
  const [categoryId, setCategoryId] = useState(config.categories[0]?.id ?? "");
  const [optionLabel, setOptionLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [followed, setFollowed] = useState(false);

  const pendientes = bets.filter((b) => b.status === "pending");
  const comprometido = pendientes.reduce((acc, b) => acc + b.amount, 0);
  const disponible = bankrollCurrent - comprometido;

  const categoria = config.categories.find((c) => c.id === categoryId);
  const opciones = categoria ? Object.values(categoria.groups) : [];

  const monto = Number(amount);
  const excedeDisponible = monto > disponible;
  const listo = optionLabel !== "" && monto > 0 && !excedeDisponible;

  if (!abierta) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-bold text-white">Tus apuestas en este giro</h3>
        {formOpen ? null : (
          <button
            type="button"
            onClick={() => setFormOpen(true)}
            className="text-xs font-bold text-muted transition-colors hover:text-white"
          >
            {recommends ? "+ Registrar otra apuesta" : "+ Registrar una apuesta igual"}
          </button>
        )}
      </div>

      {pendientes.length === 0 && !formOpen ? (
        <p className="text-xs leading-relaxed text-muted">
          {recommends
            ? "Ninguna todavía. Si seguiste la recomendación, anótala con “Aposté esto” en su tarjeta."
            : "Ninguna. Con el motor pidiendo no apostar, lo normal es dejar pasar el giro."}
        </p>
      ) : null}

      {pendientes.length > 0 ? (
        <div className="rounded-lg border border-gold/40 bg-gold/10 px-3 py-2.5">
          <ul className="space-y-1">
            {pendientes.map((b) => (
              <li key={b.id} className="flex items-center justify-between gap-2 text-sm">
                <span className="text-white">
                  <span className="font-bold">{b.option_label}</span>
                  <span className="ml-2 text-muted">{MONEY(b.amount)}</span>
                  {b.strategy ? (
                    <span className="ml-2 text-xs text-gold">{STRATEGY_LABEL[b.strategy]}</span>
                  ) : null}
                </span>
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => onCancel(b.id)}
                  className="text-xs text-muted transition-colors hover:text-white disabled:opacity-40"
                >
                  Quitar
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2 border-t border-gold/20 pt-2 text-xs text-muted">
            {MONEY(comprometido)} en juego, se resuelve con el próximo número.
            {pendientes.length > 1 ? (
              <>
                {" "}
                Cubrir varias opciones reparte el riesgo, no lo reduce: la ventaja de
                la casa se aplica a cada apuesta por separado.
              </>
            ) : null}
          </p>
        </div>
      ) : null}

      {formOpen ? (
      <form
        className="space-y-2 rounded-lg border border-edge bg-ink px-3 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!listo) return;
          onPlace({
            category: categoryId,
            option_label: optionLabel,
            amount: monto,
            followed_suggestion: followed,
          });
          setOptionLabel("");
          setAmount("");
          setFollowed(false);
          setFormOpen(false);
        }}
      >
      {/* Dos filas: los selectores necesitan ancho para no truncar la etiqueta. */}
      <div className="grid gap-2 sm:grid-cols-2">
        <select
          aria-label="Categoría"
          value={categoryId}
          onChange={(e) => {
            setCategoryId(e.target.value);
            setOptionLabel("");
          }}
          className={SELECT}
        >
          {config.categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>

        <select
          aria-label="A qué apostaste"
          value={optionLabel}
          onChange={(e) => setOptionLabel(e.target.value)}
          className={SELECT}
        >
          <option value="">A qué apostaste</option>
          {opciones.map((g) => (
            <option key={g.label ?? ""} value={g.label ?? ""}>
              {g.label} · paga {g.payout} a 1
            </option>
          ))}
        </select>

      </div>

      <div className="flex gap-2">
        <input
          aria-label="Monto apostado"
          type="number"
          min={1}
          placeholder="Monto apostado"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="flex-1 rounded-lg border border-edge bg-ink-sunken px-3 py-2 text-sm tabular-nums text-white outline-none placeholder:text-muted/70 focus:border-gold/60"
        />

        <Button type="submit" disabled={pending || !listo}>
          Registrar
        </Button>
        <Button type="button" variant="ghost" onClick={() => setFormOpen(false)}>
          Cancelar
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <button
          type="button"
          onClick={() => setAmount(String(baseBet))}
          className="rounded-md border border-edge px-2 py-1 text-xs text-muted transition-colors hover:border-gold/50 hover:text-white"
        >
          Apuesta base {MONEY(baseBet)}
        </button>

        <label className="flex items-center gap-1.5 text-xs text-muted">
          <input
            type="checkbox"
            className="accent-gold"
            checked={followed}
            onChange={(e) => setFollowed(e.target.checked)}
          />
          Elegí esto tras ver una señal
        </label>
      </div>

        {excedeDisponible ? (
          <ErrorBox
            message={
              comprometido > 0
                ? `Te quedan ${MONEY(disponible)} disponibles: ya tienes ${MONEY(
                    comprometido,
                  )} en juego.`
                : "La apuesta supera tu banca disponible."
            }
          />
        ) : null}
      </form>
      ) : null}

      <p className="text-[11px] leading-relaxed text-muted/80">
        Tu banca se mueve con todas las apuestas que anotes. El escalón de una
        progresión solo avanza si apostaste con esa gestión (“Aposté esto”); una
        apuesta registrada a mano no mueve ninguna progresión.
      </p>
    </div>
  );
}


const SIGNED = (n: number) => `${n >= 0 ? "+" : "−"}${MONEY(Math.abs(n))}`;

/** Apuestas ya resueltas de la sesión. Se consulta, no se usa a cada giro. */
export function BetHistory({ bets }: { bets: BetResponse[] }) {
  const resueltas = bets.filter((b) => b.status === "resolved");

  if (resueltas.length === 0) {
    return (
      <div className="px-3 py-6 text-center text-sm text-muted">
        Todavía no has registrado ninguna apuesta.
      </div>
    );
  }

  const neto = resueltas.reduce((acc, b) => acc + (b.net_change ?? 0), 0);
  const ganadas = resueltas.filter((b) => b.won).length;

  return (
    <div className="px-3 py-3">
      <p className="mb-3 text-sm text-muted">
        {resueltas.length} {resueltas.length === 1 ? "apuesta" : "apuestas"} ·{" "}
        {ganadas} {ganadas === 1 ? "ganada" : "ganadas"} · neto{" "}
        <span
          className={`font-bold ${
            neto > 0 ? "text-signal-strong" : neto < 0 ? "text-table-red" : "text-white"
          }`}
        >
          {SIGNED(neto)}
        </span>
      </p>

      <ul className="space-y-1.5">
        {[...resueltas].reverse().map((b) => (
          <li
            key={b.id}
            className="flex items-center justify-between rounded-lg border border-edge bg-ink px-3 py-2 text-xs"
          >
            <span className="text-white">
              {b.option_label}
              <span className="ml-2 text-muted">{MONEY(b.amount)}</span>
              {b.followed_suggestion ? (
                <span className="ml-2 text-muted">tras ver una señal</span>
              ) : null}
            </span>
            <span
              className={`font-bold tabular-nums ${
                b.won ? "text-signal-strong" : "text-table-red"
              }`}
            >
              {SIGNED(b.net_change ?? 0)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
