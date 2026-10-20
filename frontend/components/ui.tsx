"use client";

/**
 * Primitivas visuales compartidas, derivadas de los mockups de `docs/design/`:
 * tarjeta elevada sobre fondo azul-noche, borde sutil, acento dorado para la
 * acción primaria.
 */

import Image from "next/image";
import { useEffect, useId, useRef, useState } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

import logoMark from "./brand/logo-mark.png";

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
      className={`inline-flex min-h-11 items-center justify-center rounded-lg px-4 py-2.5 text-sm font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${styles} ${className}`}
    />
  );
}

export function Field({
  label,
  hint,
  info,
  infoAlign,
  error,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: string;
  /** Explicación del campo, en un tooltip junto a la etiqueta. */
  info?: ReactNode;
  infoAlign?: "left" | "right";
  /** Qué está mal en lo escrito. Reemplaza a `hint` mientras exista. */
  error?: string;
}) {
  const messageId = useId();
  const autoId = useId();
  const inputId = props.id ?? autoId;
  const message = error ?? hint;
  // La etiqueta apunta al campo por `htmlFor` en vez de envolverlo: si envolviera
  // también el botón de ayuda, nombraría al botón y el campo quedaría sin nombre.
  return (
    <div>
      <span className="mb-1.5 block text-sm font-bold text-white">
        <label htmlFor={inputId}>{label}</label>
        {info ? (
          <InfoTip label={label} align={infoAlign}>
            {info}
          </InfoTip>
        ) : null}
      </span>
      <input
        {...props}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={message ? messageId : undefined}
        className={`min-h-12 w-full rounded-lg border bg-ink-sunken px-3.5 py-2.5 text-base text-white outline-none placeholder:text-muted/70 sm:text-sm ${
          error ? "border-table-red/70 focus:border-table-red" : "border-edge focus:border-gold/60"
        }`}
      />
      {message ? (
        <span
          id={messageId}
          className={`mt-1 block text-xs ${error ? "font-bold text-table-red" : "text-muted"}`}
        >
          {message}
        </span>
      ) : null}
    </div>
  );
}

/** Casilla con su texto al lado; el texto puede llevar enlaces. */
export function Checkbox({
  children,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { children: ReactNode }) {
  return (
    <label className="flex min-h-11 items-start gap-3 py-1 text-sm leading-relaxed text-white">
      <input
        {...props}
        type="checkbox"
        className="mt-0.5 h-5 w-5 shrink-0 rounded border-edge bg-ink-sunken accent-gold"
      />
      <span>{children}</span>
    </label>
  );
}

/**
 * Campo de contraseña con botón para verla. Escribir a ciegas en el celular es
 * la causa más común de "contraseña incorrecta" en un registro recién hecho.
 */
export function PasswordField({
  label,
  hint,
  id,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label: string;
  hint?: string;
  id: string;
}) {
  const [visible, setVisible] = useState(false);
  const hintId = hint ? `${id}-hint` : undefined;

  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-bold text-white">
        {label}
      </label>
      <div className="relative">
        <input
          {...props}
          id={id}
          type={visible ? "text" : "password"}
          aria-describedby={hintId}
          className="min-h-12 w-full rounded-lg border border-edge bg-ink-sunken py-2.5 pl-3.5 pr-24 text-base text-white outline-none placeholder:text-muted/70 focus:border-gold/60 sm:text-sm"
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-controls={id}
          aria-pressed={visible}
          className="absolute inset-y-0.5 right-0.5 flex min-w-[5.5rem] items-center justify-center gap-1.5 rounded-md px-2.5 text-xs font-bold text-muted transition-colors hover:bg-ink hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-gold"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path
              d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
            <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
            {visible ? (
              <path d="M4 4l16 16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            ) : null}
          </svg>
          {visible ? "Ocultar" : "Mostrar"}
        </button>
      </div>
      {hint ? (
        <span id={hintId} className="mt-1 block text-xs text-muted">
          {hint}
        </span>
      ) : null}
    </div>
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

/** Confirmación de que algo se guardó: la pareja de `ErrorBox`. */
export function SuccessBox({ message }: { message: string }) {
  return (
    <div
      role="status"
      className="flex items-start gap-2.5 rounded-lg border border-signal-strong/50 bg-signal-strong/10 px-3.5 py-3 text-sm text-white"
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 20 20"
        className="mt-0.5 h-4 w-4 shrink-0 text-signal-strong"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M4 10.5l4 4 8-9" />
      </svg>
      <p className="font-bold">{message}</p>
    </div>
  );
}

/**
 * El logo: el hexágono dorado, sin fondo. `size` es el alto en píxeles.
 *
 * Es decorativo: donde aparece, el nombre va escrito al lado o lo dice el
 * enlace que lo envuelve. La imagen sale de `scripts/make-logo.mjs`.
 */
export function BrandMark({ size = 88 }: { size?: number }) {
  return (
    <Image
      src={logoMark}
      alt=""
      height={size}
      width={Math.round((size * logoMark.width) / logoMark.height)}
      // Ya viene en el tamaño que se usa: no hace falta el optimizador.
      unoptimized
      priority
    />
  );
}


/**
 * Explicación breve de un término, anclada a su etiqueta.
 *
 * Se abre con clic (no solo con hover) para que funcione en pantallas táctiles,
 * y se cierra con Escape o al hacer clic fuera. El texto va en el DOM siempre,
 * así que un lector de pantalla lo alcanza aunque el panel esté plegado.
 */
export function InfoTip({
  label,
  buttonLabel,
  align = "left",
  children,
}: {
  label: string;
  /** Nombre del botón cuando no es "Qué significa <label>". */
  buttonLabel?: string;
  /** Hacia qué lado se abre; "right" para etiquetas pegadas al borde derecho. */
  align?: "left" | "right";
  children: ReactNode;
}) {
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
        aria-label={buttonLabel ?? `Qué significa ${label}`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="relative ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full border border-muted/50 text-[10px] font-bold leading-none text-muted transition-colors before:absolute before:-inset-3.5 before:content-[''] hover:border-gold hover:text-gold"
      >
        ?
      </button>
      <span
        role="tooltip"
        hidden={!open}
        className={`absolute ${
          align === "right" ? "right-0" : "left-0"
        } top-5 z-20 w-60 rounded-lg border border-edge bg-ink-raised px-3 py-2.5 text-xs font-normal leading-relaxed text-muted shadow-lg`}
      >
        {children}
      </span>
    </span>
  );
}
