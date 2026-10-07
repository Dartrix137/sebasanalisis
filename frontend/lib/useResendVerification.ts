"use client";

/**
 * Reenvío del correo de confirmación, con la espera entre un envío y el
 * siguiente. El límite de verdad lo pone la API (uno por minuto, 3 cada 15
 * minutos y 10 al día por cuenta); esto solo evita que el botón invite a
 * pulsarlo de nuevo antes de que el correo haya tenido tiempo de llegar.
 */

import { useEffect, useState } from "react";

import { ApiError, authApi } from "./api-client";
import { useSession } from "./session";

/** La misma espera que exige la API entre dos reenvíos. */
export const RESEND_COOLDOWN_SECONDS = 60;

const TOO_MANY_REQUESTS = 429;

// Fuera del componente: el aviso del menú y la tarjeta de "Mi cuenta" comparten
// la espera, y cambiar de página no la reinicia.
let cooldownUntil = 0;

function secondsUntilCooldownEnds(): number {
  return Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
}

export interface ResendOutcome {
  ok: boolean;
  message: string;
}

export function useResendVerification() {
  const { withToken } = useSession();
  const [outcome, setOutcome] = useState<ResendOutcome | null>(null);
  const [pending, setPending] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(secondsUntilCooldownEnds);

  const waiting = secondsLeft > 0;
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => setSecondsLeft(secondsUntilCooldownEnds()), 1000);
    return () => clearInterval(timer);
  }, [waiting]);

  function startCooldown() {
    cooldownUntil = Date.now() + RESEND_COOLDOWN_SECONDS * 1000;
    setSecondsLeft(RESEND_COOLDOWN_SECONDS);
  }

  async function resend() {
    if (pending || waiting) return;
    setOutcome(null);
    setPending(true);
    try {
      const { message } = await withToken((t) => authApi.resendVerification(t));
      setOutcome({ ok: true, message });
      startCooldown();
    } catch (err) {
      const limited = err instanceof ApiError && err.status === TOO_MANY_REQUESTS;
      setOutcome({
        ok: false,
        message: limited
          ? "Ya te enviamos el correo hace poco. Revisa la carpeta de correo no deseado y espera unos minutos antes de pedir otro"
          : err instanceof ApiError
            ? err.message
            : "No se pudo reenviar el correo",
      });
      if (limited) startCooldown();
    } finally {
      setPending(false);
    }
  }

  return { resend, pending, secondsLeft, outcome };
}
