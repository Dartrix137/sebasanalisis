"use client";

/**
 * Aviso para la cuenta que todavía no confirmó su correo. No bloquea nada: la
 * confirmación es requisito para pagar, no para entrar (§5.2 de la Fase 4).
 */

import { useState } from "react";

import { ApiError, authApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";

import { Button } from "./ui";

export function VerifyEmailNotice() {
  const { user, withToken } = useSession();
  const [status, setStatus] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (!user || user.email_verified) return null;

  async function resend() {
    setPending(true);
    try {
      const { message } = await withToken((t) => authApi.resendVerification(t));
      setStatus(message);
    } catch (err) {
      setStatus(err instanceof ApiError ? err.message : "No se pudo reenviar el correo");
    } finally {
      setPending(false);
    }
  }

  return (
    <div
      role="status"
      className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gold/40 bg-gold/10 px-4 py-3"
    >
      <p className="min-w-0 flex-1 break-words text-sm leading-relaxed text-white">
        <span className="font-bold">Confirma tu correo.</span>{" "}
        {status ?? `Te enviamos un enlace a ${user.email}.`}
      </p>
      <Button variant="ghost" onClick={resend} disabled={pending}>
        {pending ? "Enviando…" : "Reenviar correo"}
      </Button>
    </div>
  );
}
