"use client";

/**
 * Página de planes (§3.10 de la Fase 4). Pública: se ve sin sesión. Es también
 * a donde `AccessGate` manda a la cuenta que no tiene acceso a la mesa.
 *
 * No decide nada: el estado de la cuenta que muestra es la decisión de acceso
 * del servidor (`access`), y el precio viene de `GET /plans`. Qué botón lleva
 * cada plan lo explica `PlansView`.
 */

import Link from "next/link";
import { useEffect } from "react";

import { PlansView } from "@/components/PlansView";
import { AppHeader } from "@/components/AppHeader";
import { VerifyEmailNotice } from "@/components/VerifyEmailNotice";
import { formatLegalDate } from "@/lib/legal";
import { useSession } from "@/lib/session";
import type { UserResponse } from "@/lib/types/auth";

const LINK = "font-bold text-gold hover:text-gold-soft";

export default function PlansPage() {
  const { user, loading, refreshUser } = useSession();
  const userId = user?.id ?? null;

  // La decisión guardada en la sesión puede ser vieja: un administrador pudo
  // dar o quitar el acceso.
  useEffect(() => {
    if (loading || !userId) return;
    refreshUser().catch(() => undefined);
  }, [loading, userId, refreshUser]);

  return (
    <>
      <AppHeader />
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-4 pb-12 pt-8 sm:px-6">
        <h1 className="font-display text-4xl font-semibold leading-none tracking-tight">
          Planes
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-muted">
          La suscripción da acceso a la plataforma. No cambia el resultado de ningún juego ni la
          ventaja de la casa.
        </p>

        {user ? <AccountStatus user={user} /> : null}
        {user && !user.access.granted ? <VerifyEmailNotice /> : null}

        <div className="mt-6">
          <PlansView />
        </div>
      </main>
    </>
  );
}

/** Lo que el servidor decidió sobre el acceso de esta cuenta, en una línea. */
function AccountStatus({ user }: { user: UserResponse }) {
  const { granted, reason, until } = user.access;
  if (granted) {
    return (
      <p role="status" className="mt-5 text-sm text-white">
        Tu cuenta ya tiene acceso.{" "}
        <Link href="/dashboard" className={LINK}>
          Ir a la mesa
        </Link>
      </p>
    );
  }
  const text =
    reason === "suspended"
      ? "Tu cuenta está suspendida: no puede usar la mesa."
      : reason === "consent_required"
        ? "Antes de usar la mesa debes aceptar la versión vigente de los documentos legales."
        : reason === "expired"
          ? `Tu acceso venció${until ? ` el ${formatLegalDate(until)}` : ""}.`
          : "Tu cuenta no tiene acceso activo.";
  return (
    <p role="status" className="mt-5 text-sm font-bold text-white">
      {text}
      {reason === "consent_required" ? (
        <>
          {" "}
          <Link href="/dashboard" className={LINK}>
            Revisar y aceptar
          </Link>
        </>
      ) : null}
    </p>
  );
}
