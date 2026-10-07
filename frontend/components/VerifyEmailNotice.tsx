"use client";

/**
 * Aviso para la cuenta que todavía no confirmó su correo. No bloquea nada: la
 * confirmación es requisito para pagar, no para entrar (§5.2 de la Fase 4).
 */

import { useSession } from "@/lib/session";
import { useResendVerification } from "@/lib/useResendVerification";

import { Button } from "./ui";

export function VerifyEmailNotice() {
  const { user } = useSession();
  const { resend, pending, secondsLeft, outcome } = useResendVerification();

  if (!user || user.email_verified) return null;

  return (
    <div
      role="status"
      className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gold/40 bg-gold/10 px-4 py-3"
    >
      <p className="min-w-0 flex-1 break-words text-sm leading-relaxed text-white">
        <span className="font-bold">Confirma tu correo.</span>{" "}
        {outcome && !outcome.ok
          ? outcome.message
          : `${outcome?.message ?? `Te enviamos un enlace a ${user.email}`}. Si no lo ves en tu bandeja de entrada, revisa la carpeta de correo no deseado.`}
      </p>
      <Button variant="ghost" onClick={resend} disabled={pending || secondsLeft > 0}>
        {pending ? "Enviando…" : secondsLeft > 0 ? `Reenviar en ${secondsLeft} s` : "Reenviar correo"}
      </Button>
    </div>
  );
}
