"use client";

/**
 * A donde la pasarela devuelve al cliente después de pagar (§3.4 de la Fase 4).
 *
 * Esta pantalla no da por hecho nada: ni que volver aquí signifique que pagó,
 * ni lo que diga la URL. Le pregunta al servidor (`GET /billing/payments/:id`)
 * hasta que el pago salga de `pending`, y muestra lo que el servidor responda.
 * El `?id=` que agrega la pasarela se le pasa al servidor solo para que sepa
 * qué transacción reconsultar.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { InlineSkeleton } from "@/components/PageSkeleton";
import { BrandMark, Button, Card, ErrorBox } from "@/components/ui";
import { ApiError, billingApi } from "@/lib/api-client";
import { formatLegalDate } from "@/lib/legal";
import { CURRENCY_NOTE, formatMoney } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { PaymentResponse } from "@/lib/types/billing";

const LINK = "font-bold text-gold hover:text-gold-soft";
const BUTTON_LINK =
  "inline-block rounded-lg bg-gold px-4 py-2.5 text-sm font-bold text-gold-ink transition-colors hover:bg-gold-soft";

const POLL_MS = 3_000;
// Unos dos minutos. Después se deja de consultar sola: hay medios de pago que
// tardan más, y el resultado llega igual por correo.
const MAX_POLLS = 40;

export function PaymentResult({ paymentId }: { paymentId: string }) {
  const transactionId = useSearchParams().get("id") ?? undefined;
  const { user, loading, withToken, refreshUser } = useSession();
  const userId = user?.id ?? null;

  const [payment, setPayment] = useState<PaymentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(true);
  const polls = useRef(0);
  const [round, setRound] = useState(0);

  const check = useCallback(
    () => withToken((t) => billingApi.payment(t, paymentId, transactionId)),
    [withToken, paymentId, transactionId],
  );

  useEffect(() => {
    if (loading || !userId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      try {
        const next = await check();
        if (cancelled) return;
        setPayment(next);
        setError(null);
        if (next.status !== "pending") {
          setWaiting(false);
          // Que el resto de la app vea ya la decisión de acceso nueva.
          if (next.status === "approved") await refreshUser().catch(() => undefined);
          return;
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          setError("No encontramos ese pago en tu cuenta.");
          setWaiting(false);
          return;
        }
        // Un fallo de red no es un pago fallido: se sigue consultando.
      }
      polls.current += 1;
      if (polls.current >= MAX_POLLS) {
        setWaiting(false);
        return;
      }
      timer = setTimeout(tick, POLL_MS);
    }

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [loading, userId, check, refreshUser, round]);

  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col px-4 pb-12 pt-10 sm:px-6">
      <Link href="/" aria-label="Sebasanálisis, ir al inicio" className="self-start">
        <BrandMark size={38} />
      </Link>
      <h1 className="mt-8 font-display text-4xl font-semibold leading-none tracking-tight">
        Tu pago
      </h1>
      <div className="mt-6">
        {loading ? (
          <InlineSkeleton />
        ) : !user ? (
          <Card>
            <p className="text-sm leading-relaxed text-white">
              Inicia sesión para ver el resultado de tu pago.
            </p>
            <p className="mt-4">
              <Link href="/login" className={BUTTON_LINK}>
                Entrar
              </Link>
            </p>
          </Card>
        ) : error ? (
          <div className="space-y-4">
            <ErrorBox message={error} />
            <Link href="/planes" className={LINK}>
              Volver a los planes
            </Link>
          </div>
        ) : (
          <Outcome
            payment={payment}
            waiting={waiting}
            onRetry={() => {
              polls.current = 0;
              setWaiting(true);
              setRound((r) => r + 1);
            }}
          />
        )}
      </div>
    </main>
  );
}

function Outcome({
  payment,
  waiting,
  onRetry,
}: {
  payment: PaymentResponse | null;
  waiting: boolean;
  onRetry: () => void;
}) {
  if (!payment || payment.status === "pending") {
    return (
      <Card>
        <div role="status" aria-live="polite">
          {waiting ? (
            <>
              <p className="text-base font-bold text-white">Estamos confirmando tu pago…</p>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                No cierres esta página. Puede tardar unos segundos.
              </p>
            </>
          ) : (
            <>
              <p className="text-base font-bold text-white">Tu pago sigue en proceso.</p>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                Algunos medios de pago tardan unos minutos en confirmarse. Cuando se confirme, tu
                acceso se activa solo y te llega un correo con el recibo. Si no terminaste el
                pago, puedes empezar de nuevo desde los planes.
              </p>
            </>
          )}
        </div>
        {waiting ? null : (
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <Button variant="ghost" onClick={onRetry}>
              Volver a consultar
            </Button>
            <Link href="/planes" className={`text-sm ${LINK}`}>
              Ir a los planes
            </Link>
          </div>
        )}
      </Card>
    );
  }

  if (payment.status === "approved") {
    return (
      <Card>
        <p role="status" className="text-base font-bold text-white">
          Pago aprobado
        </p>
        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Plan</dt>
            <dd className="text-white">{payment.plan_name}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Total pagado</dt>
            <dd className="text-white">{formatMoney(payment.amount_cents, payment.currency)}</dd>
          </div>
          {payment.period_end ? (
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Acceso hasta</dt>
              <dd className="text-white">{formatLegalDate(payment.period_end)}</dd>
            </div>
          ) : null}
        </dl>
        <p className="mt-4 text-xs leading-relaxed text-muted">
          {CURRENCY_NOTE} Te enviamos el recibo por correo.
        </p>
        <p className="mt-5">
          <Link href="/dashboard" className={BUTTON_LINK}>
            Ir a la mesa
          </Link>
        </p>
      </Card>
    );
  }

  const text =
    payment.status === "declined"
      ? "El pago fue rechazado y tu suscripción no se activó. Puedes intentarlo de nuevo, con el mismo medio de pago o con otro."
      : payment.status === "voided"
        ? "El pago fue anulado y tu suscripción no se activó."
        : "Hubo un problema al procesar el pago y tu suscripción no se activó.";
  return (
    <Card>
      <p role="alert" className="text-base font-bold text-white">
        El pago no se completó
      </p>
      <p className="mt-2 text-sm leading-relaxed text-muted">{text}</p>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        Si ves un cobro en tu extracto por este pago, escríbenos al correo de contacto que aparece
        en los{" "}
        <Link href="/legal/terminos" className={LINK}>
          términos y condiciones
        </Link>
        .
      </p>
      <p className="mt-5">
        <Link href="/planes" className={BUTTON_LINK}>
          Volver a los planes
        </Link>
      </p>
    </Card>
  );
}
