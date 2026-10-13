"use client";

/**
 * Pantalla previa al pago de un plan (§3.4 y §3.10 de la Fase 4).
 *
 * Muestra lo que se va a cobrar y manda a la página de la pasarela. Aquí no se
 * calcula ningún precio: el total viene de `POST /billing/quote`, y el que de
 * verdad se cobra lo vuelve a calcular el servidor al abrir el pago. Solo
 * viajan el plan y el código del cupón.
 *
 * Aquí tampoco se escribe ningún dato de pago: eso ocurre en la página de la
 * pasarela.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { VerifyEmailNotice } from "@/components/VerifyEmailNotice";
import { BrandMark, Button, Card, ErrorBox, Field } from "@/components/ui";
import { ApiError, billingApi } from "@/lib/api-client";
import { formatLegalDate } from "@/lib/legal";
import { CURRENCY_NOTE, formatMoney, intervalLabel } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { PlanResponse, QuoteResponse, SubscriptionResponse } from "@/lib/types/billing";

const LINK = "font-bold text-gold hover:text-gold-soft";

function messageOf(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function Checkout() {
  const planId = useSearchParams().get("plan") ?? "";
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  const userId = user?.id ?? null;

  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [code, setCode] = useState("");
  // El código con el que se pidió la última cotización: es el que viaja al pagar.
  const [appliedCode, setAppliedCode] = useState<string | null>(null);
  const [couponError, setCouponError] = useState<string | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [paying, setPaying] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!userId) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    Promise.all([
      billingApi.plans(),
      withToken((t) => billingApi.subscription(t)),
      withToken((t) => billingApi.quote(t, { plan_id: planId })),
    ])
      .then(([plans, current, first]) => {
        if (cancelled) return;
        setPlan(plans.find((p) => p.id === planId) ?? null);
        setSubscription(current);
        setQuote(first);
        setReady(true);
      })
      .catch((e) => {
        if (!cancelled) setError(messageOf(e, "No se pudo cargar el plan"));
      });
    return () => {
      cancelled = true;
    };
  }, [loading, userId, planId, router, withToken]);

  if (loading || !user) return null;
  if (error) {
    return (
      <div className="space-y-4">
        <ErrorBox message={error} />
        <Link href="/planes" className={LINK}>
          Volver a los planes
        </Link>
      </div>
    );
  }
  if (!ready) return <p className="text-sm text-muted">Cargando…</p>;
  if (!plan || !quote) {
    return (
      <div className="space-y-4">
        <ErrorBox message="Ese plan no está disponible." />
        <Link href="/planes" className={LINK}>
          Volver a los planes
        </Link>
      </div>
    );
  }

  // Con un período pagado y vigente, lo que se paga es el siguiente del mismo
  // plan, por el precio congelado de la suscripción y sin cupón.
  const renewing =
    subscription !== null && subscription.in_force && subscription.plan.id === plan.id;
  const subtotal = renewing ? subscription.price_cents : quote.subtotal_cents;
  const discount = renewing ? 0 : quote.discount_cents;
  const total = renewing ? subscription.price_cents : quote.total_cents;
  const currency = renewing ? subscription.currency : quote.currency;

  async function applyCoupon(event: FormEvent) {
    event.preventDefault();
    const typed = code.trim();
    setCouponError(null);
    setQuoting(true);
    try {
      const next = await withToken((t) =>
        billingApi.quote(t, { plan_id: planId, coupon_code: typed || null }),
      );
      setQuote(next);
      if (next.coupon && !next.coupon.applied) {
        setAppliedCode(null);
        setCouponError(next.coupon.message ?? "Ese cupón no aplica.");
      } else {
        setAppliedCode(next.coupon ? next.coupon.code : null);
      }
    } catch (e) {
      setCouponError(messageOf(e, "No se pudo revisar el cupón"));
    } finally {
      setQuoting(false);
    }
  }

  async function pay() {
    setError(null);
    setCouponError(null);
    setPaying(true);
    try {
      const started = await withToken((t) =>
        billingApi.subscribe(t, {
          plan_id: planId,
          coupon_code: renewing ? null : appliedCode,
        }),
      );
      // A la página de la pasarela. De allá vuelve a /pago/:id.
      window.location.assign(started.checkout_url);
    } catch (e) {
      setPaying(false);
      if (e instanceof ApiError && e.code === "coupon_rejected") {
        setAppliedCode(null);
        setCouponError(e.message);
        // El total que se mostraba ya no vale: se vuelve a pedir sin cupón.
        withToken((t) => billingApi.quote(t, { plan_id: planId }))
          .then(setQuote)
          .catch(() => undefined);
        return;
      }
      setError(messageOf(e, "No se pudo abrir el pago"));
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <h2 className="font-display text-2xl font-semibold leading-tight text-white">
          {plan.name}
        </h2>
        <p className="mt-1 text-sm text-muted">
          {renewing ? "Siguiente período: " : "Un pago por "}
          {intervalLabel(plan.interval, plan.interval_count)} de acceso. No se renueva solo ni
          guarda tu medio de pago.
        </p>
        {renewing && subscription.current_period_end ? (
          <p className="mt-3 text-sm text-white">
            Tu acceso actual va hasta el {formatLegalDate(subscription.current_period_end)}. El
            período nuevo empieza ese día: no pierdes los días que te quedan.
          </p>
        ) : null}

        <dl className="mt-5 space-y-2 text-sm" data-testid="resumen-pago">
          {discount > 0 ? (
            <>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Precio del plan</dt>
                <dd className="text-white">{formatMoney(subtotal, currency)}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Descuento ({appliedCode})</dt>
                <dd className="text-white">− {formatMoney(discount, currency)}</dd>
              </div>
            </>
          ) : null}
          <div className="flex items-baseline justify-between gap-4 border-t border-edge pt-3">
            <dt className="font-bold text-white">Total a pagar</dt>
            <dd
              className="font-display text-3xl font-semibold leading-none text-white"
              data-testid="total-a-pagar"
            >
              {formatMoney(total, currency)}
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs leading-relaxed text-muted">{CURRENCY_NOTE}</p>
      </Card>

      {renewing ? null : (
        <Card>
          <form onSubmit={applyCoupon} className="flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1">
              <Field
                label="Cupón (opcional)"
                name="coupon"
                autoComplete="off"
                value={code}
                maxLength={40}
                onChange={(e) => setCode(e.target.value)}
              />
            </div>
            <Button type="submit" variant="ghost" disabled={quoting || paying}>
              {quoting ? "Revisando…" : "Aplicar"}
            </Button>
          </form>
          {couponError ? (
            <p role="alert" className="mt-3 text-sm font-bold text-table-red">
              {couponError}
            </p>
          ) : appliedCode ? (
            <p role="status" className="mt-3 text-sm text-white">
              Cupón {appliedCode} aplicado.
            </p>
          ) : null}
        </Card>
      )}

      {user.email_verified ? null : <VerifyEmailNotice />}

      <div className="space-y-3">
        <Button onClick={pay} disabled={paying || quoting || !user.email_verified}>
          {paying ? "Abriendo el pago…" : `Ir a pagar ${formatMoney(total, currency)}`}
        </Button>
        {user.email_verified ? null : (
          <p className="text-sm text-muted">Confirma tu correo para poder pagar.</p>
        )}
        <p className="max-w-prose text-xs leading-relaxed text-muted">
          Al continuar vas a la página de pagos de Wompi, donde eliges el medio de pago.
          Sebasanálisis no recibe ni guarda los datos de tu tarjeta ni de tu cuenta bancaria. La
          suscripción da acceso a la plataforma: no cambia el resultado de ningún juego ni la
          ventaja de la casa. Consulta los{" "}
          <Link href="/legal/terminos" className={LINK}>
            términos
          </Link>{" "}
          y la{" "}
          <Link href="/legal/reembolsos" className={LINK}>
            política de reembolsos
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

export default function CheckoutPage() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col px-4 pb-12 pt-10 sm:px-6">
      <div className="flex items-center justify-between gap-3">
        <Link href="/" aria-label="Sebasanálisis, ir al inicio">
          <BrandMark size={38} />
        </Link>
        <Link href="/planes" className={`text-sm ${LINK}`}>
          Volver a los planes
        </Link>
      </div>
      <h1 className="mt-8 font-display text-4xl font-semibold leading-none tracking-tight">
        Confirma tu pago
      </h1>
      <div className="mt-6">
        {/* useSearchParams necesita un límite de Suspense para el build estático. */}
        <Suspense fallback={null}>
          <Checkout />
        </Suspense>
      </div>
    </main>
  );
}
