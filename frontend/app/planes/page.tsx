"use client";

/**
 * Página de planes (§3.10 de la Fase 4). Pública: se ve sin sesión. Es también
 * a donde `AccessGate` manda a la cuenta que no tiene acceso a la mesa.
 *
 * No decide nada: el estado de la cuenta que muestra es la decisión de acceso
 * del servidor (`access`), y el precio viene de `GET /plans`.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { PlansView } from "@/components/PlansView";
import { BrandMark } from "@/components/ui";
import { VerifyEmailNotice } from "@/components/VerifyEmailNotice";
import { formatLegalDate } from "@/lib/legal";
import { useSession } from "@/lib/session";
import type { UserResponse } from "@/lib/types/auth";

const LINK = "font-bold text-gold hover:text-gold-soft";

export default function PlansPage() {
  const { user, loading, signOut, refreshUser } = useSession();
  const router = useRouter();
  const userId = user?.id ?? null;

  // La decisión guardada en la sesión puede ser vieja: un administrador pudo
  // dar o quitar el acceso.
  useEffect(() => {
    if (loading || !userId) return;
    refreshUser().catch(() => undefined);
  }, [loading, userId, refreshUser]);

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 pb-12 pt-10 sm:px-6">
      <div className="flex items-center justify-between gap-3">
        <BrandMark size={38} />
        {loading ? null : user ? (
          <div className="flex items-center gap-4 text-sm">
            <Link href="/cuenta" className={LINK}>
              Mi cuenta
            </Link>
            <button
              type="button"
              className="font-bold text-muted hover:text-white"
              onClick={() => {
                signOut();
                router.replace("/login");
              }}
            >
              Salir
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-4 text-sm">
            <Link href="/login" className={LINK}>
              Entrar
            </Link>
            <Link href="/register" className={LINK}>
              Crear cuenta
            </Link>
          </div>
        )}
      </div>

      <h1 className="mt-8 font-display text-4xl font-semibold leading-none tracking-tight">
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
    </p>
  );
}
