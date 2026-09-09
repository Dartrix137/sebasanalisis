"use client";

/**
 * Primitivas visuales compartidas, derivadas de los mockups de `docs/design/`:
 * tarjeta elevada sobre fondo azul-noche, borde sutil, acento dorado para la
 * acción primaria.
 */

import { useEffect, useRef, useState } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-card border border-edge bg-ink-raised p-4 shadow-card sm:p-5 ${className}`}
    >
      {children}
    </section>
  );
}

export function CardHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header className="mb-4">
      <h2 className="text-base font-bold text-white">{title}</h2>
      {subtitle ? <p className="mt-1 text-sm text-muted">{subtitle}</p> : null}
    </header>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";
};

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  const styles = {
    primary: "bg-gold text-gold-ink hover:bg-gold-soft disabled:bg-gold/40",
    ghost: "border border-edge bg-ink-sunken text-white hover:border-gold/50",
    danger: "border border-table-red/40 bg-transparent text-table-red hover:bg-table-red/10",
  }[variant];
  return (
    <button
      {...props}
      className={`rounded-lg px-4 py-2.5 text-sm font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${styles} ${className}`}
    />
  );
}

export function Field({
  label,
  hint,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-bold text-white">{label}</span>
      <input
        {...props}
        className="w-full rounded-lg border border-edge bg-ink-sunken px-3.5 py-2.5 text-sm text-white outline-none placeholder:text-muted/70 focus:border-gold/60"
      />
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "off";
}) {
  const styles = {
    neutral: "border-edge text-muted",
    ok: "border-signal-strong/50 text-signal-strong",
    off: "border-muted/30 text-muted",
  }[tone];
  return (
    <span className={`rounded-md border px-2 py-0.5 text-xs font-bold ${styles}`}>
      {children}
    </span>
  );
}

export function ErrorBox({ message, details }: { message: string; details?: string[] }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-table-red/40 bg-table-red/10 px-3.5 py-3 text-sm text-white"
    >
      <p className="font-bold">{message}</p>
      {details?.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted">
          {details.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function BrandMark({ size = 56 }: { size?: number }) {
  return (
    <div
      style={{ width: size, height: size }}
      className="flex items-center justify-center rounded-full bg-gold text-gold-ink shadow-[0_0_40px_-6px_rgba(221,165,32,0.7)]"
    >
      <svg viewBox="0 0 24 24" width={size * 0.5} height={size * 0.5} aria-hidden="true">
        <rect
          x="3"
          y="3"
          width="13"
          height="13"
          rx="3"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        />
        <circle cx="9.5" cy="9.5" r="1.6" fill="currentColor" />
        <path
          d="M17 12h3l-2 2 2 2h-3"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}


/**
 * Explicación breve de un término, anclada a su etiqueta.
 *
 * Se abre con clic (no solo con hover) para que funcione en pantallas táctiles,
 * y se cierra con Escape o al hacer clic fuera. El texto va en el DOM siempre,
 * así que un lector de pantalla lo alcanza aunque el panel esté plegado.
 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    function fuera(e: MouseEvent) {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    }
    function escape(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", fuera);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", fuera);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <span ref={box} className="relative inline-block">
      <button
        type="button"
        aria-label={`Qué significa ${label}`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="ml-1 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full border border-muted/50 text-[9px] font-bold leading-none text-muted transition-colors hover:border-gold hover:text-gold"
      >
        ?
      </button>
      <span
        role="tooltip"
        hidden={!open}
        className="absolute left-0 top-5 z-20 w-60 rounded-lg border border-edge bg-ink-raised px-3 py-2.5 text-xs font-normal leading-relaxed text-muted shadow-lg"
      >
        {children}
      </span>
    </span>
  );
}
