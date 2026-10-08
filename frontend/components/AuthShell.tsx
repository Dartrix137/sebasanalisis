"use client";

/**
 * Marco de las pantallas de cuenta que se abren sin sesión o desde un enlace de
 * correo: verificar el correo, olvidé mi contraseña, restablecerla. Misma
 * composición que el login (`docs/design/login.jpeg`): marca centrada y una
 * tarjeta.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { useSession } from "@/lib/session";

import { BrandMark, Card } from "./ui";

/** La misma regla que aplica el servidor (`core/password_policy.py`). */
export const PASSWORD_MIN_LENGTH = 10;
export const PASSWORD_HINT = `Mínimo ${PASSWORD_MIN_LENGTH} caracteres. Evita las contraseñas comunes.`;

export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  // El contenido se pinta cuando la sesión ya se leyó, es decir, con la página
  // ya interactiva. Un formulario que viene en el HTML del servidor se puede
  // llenar y enviar antes de que React lo tome: lo escrito se pierde y el envío
  // recarga la página sin hacer nada.
  const { loading } = useSession();

  return (
    <main className="flex flex-1 flex-col items-center justify-center px-4 py-12">
      <Link href="/" aria-label="Sebasanálisis, ir al inicio">
        <BrandMark />
      </Link>
      <h1 className="mt-5 text-center font-display text-4xl font-semibold leading-none tracking-tight">
        {title}
      </h1>
      {subtitle ? (
        <p className="mt-3 max-w-sm text-center text-sm leading-relaxed text-muted">{subtitle}</p>
      ) : null}
      <Card className="mt-7 w-full max-w-md">{loading ? null : children}</Card>
    </main>
  );
}

/** Mensaje de resultado correcto, par de `ErrorBox`. */
export function SuccessBox({ message }: { message: string }) {
  return (
    <div
      role="status"
      className="rounded-lg border border-signal-strong/40 bg-signal-strong/10 px-3.5 py-3 text-sm font-bold text-white"
    >
      {message}
    </div>
  );
}

export function TextLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="font-bold text-gold hover:text-gold-soft">
      {children}
    </Link>
  );
}
