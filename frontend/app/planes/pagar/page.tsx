"use client";

/**
 * Pantalla previa al pago de un plan (§3.4 y §3.10 de la Fase 4).
 *
 * Muestra lo que se va a cobrar y deja elegir cómo pagar:
 *
 * - **Pago manual**: un pago por período, en la página de la pasarela, con
 *   cualquier medio. No se guarda nada.
 * - **Renovación automática**: el cliente guarda un medio de pago con
 *   `PaymentSourceForm`, y se le cobra cada período, con un aviso por correo
 *   antes. Solo se ofrece si la pasarela tokeniza (`availability.tokenizer`).
 *
 * Ningún modo entra marcado (decidido el 2026-10-13): nadie queda con cobros
 * automáticos sin haberlo escogido.
 *
 * Aquí no se calcula ningún precio: el total viene del servidor, que lo vuelve
 * a calcular al abrir el pago. Y a nuestro servidor no llega ningún dato de
 * pago: se paga en la página de la pasarela, o la pasarela tokeniza el medio, y
 * aquí solo vuelve un token.
 *
 * Sin pasarela configurada (paso 5.1 de la Fase 5),
 * `/planes` no deja llegar aquí con el pago encendido.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { VerifyEmailNotice } from "@/components/VerifyEmailNotice";
import { PaymentSourceForm } from "@/components/billing/PaymentSourceForm";
import { InlineSkeleton } from "@/components/PageSkeleton";
import { AppHeader } from "@/components/AppHeader";
import { Button, Card, ErrorBox, Field } from "@/components/ui";
import { ApiError, billingApi } from "@/lib/api-client";
import { formatLegalDate } from "@/lib/legal";
import { CURRENCY_NOTE, formatMoney, intervalLabel, periodLabel } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { TokenizedSource } from "@/components/billing/PaymentSourceForm";
import type {
  AcceptanceResponse,
  BillingAvailabilityResponse,
  PlanResponse,
  QuoteResponse,
  RenewalMode,
  SubscriptionResponse,
} from "@/lib/types/billing";

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
  const [availability, setAvailability] = useState<BillingAvailabilityResponse | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [code, setCode] = useState("");
  // El código con el que se pidió la última cotización: es el que viaja al pagar.
  const [appliedCode, setAppliedCode] = useState<string | null>(null);
  const [couponError, setCouponError] = useState<string | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [paying, setPaying] = useState(false);

  // Ningún modo entra marcado.
  const [mode, setMode] = useState<RenewalMode | null>(null);

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
      billingApi.availability(),
    ])
      .then(([plans, current, first, available]) => {
        if (cancelled) return;
        setPlan(plans.find((p) => p.id === planId) ?? null);
        setSubscription(current);
        setQuote(first);
        setAvailability(available);
        setReady(true);
      })
      .catch((e) => {
        if (!cancelled) setError(messageOf(e, "No se pudo cargar el plan"));
      });
    return () => {
      cancelled = true;
    };
  }, [loading, userId, planId, router, withToken]);

  if (loading || !user) return <InlineSkeleton cards={2} />;
  if (error && !ready) {
    return (
      <div className="space-y-4">
        <ErrorBox message={error} />
        <Link href="/planes" className={LINK}>
          Volver a los planes
        </Link>
      </div>
    );
  }
  if (!ready) return <InlineSkeleton cards={2} />;
  if (!plan || !quote || !availability) {
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
  const current = subscription?.in_force ? subscription : null;
  const renewing = current !== null && current.plan.id === plan.id;

  if (current && current.renewal_mode === "automatic" && current.status !== "canceled") {
    // Se renueva sola: no hay nada que pagar a mano.
    return (
      <Card>
        <p role="status" className="text-base font-bold text-white">
          Tu suscripción se renueva sola
        </p>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          No tienes que pagar el siguiente período: se cobra a tu medio de pago guardado, y antes
          te avisamos por correo. Puedes verla o cancelar la renovación desde tu cuenta.
        </p>
        <p className="mt-4">
          <Link href="/cuenta" className={LINK}>
            Ir a mi cuenta
          </Link>
        </p>
      </Card>
    );
  }

  const subtotal = renewing ? current.price_cents : quote.subtotal_cents;
  const total = renewing ? (current.next_charge_cents ?? current.price_cents) : quote.total_cents;
  const discount = subtotal - total;
  const currency = renewing ? current.currency : quote.currency;
  const totalText = formatMoney(total, currency);
  const interval = intervalLabel(plan.interval, plan.interval_count);
  // "un mes de acceso", no "mes de acceso".
  const period = periodLabel(plan.interval, plan.interval_count);

  // La renovación automática solo se ofrece en el alta, y si la pasarela la permite.
  const automaticOffered = !renewing && availability.tokenizer !== null;
  const chosen: RenewalMode | null = automaticOffered ? mode : "manual";

  function chooseMode(next: RenewalMode) {
    setMode(next);
    setError(null);
  }

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

  function handleFailure(e: unknown) {
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

  async function payManually() {
    setError(null);
    setCouponError(null);
    setPaying(true);
    try {
      const started = await withToken((t) =>
        billingApi.subscribe(t, {
          plan_id: planId,
          coupon_code: renewing ? null : appliedCode,
          renewal_mode: "manual",
        }),
      );
      if (!started.checkout_url) throw new Error("sin página de pago");
      // A la página de la pasarela. De allá vuelve a /pago/:id.
      window.location.assign(started.checkout_url);
    } catch (e) {
      handleFailure(e);
    }
  }

  /** Con el token que devolvió la pasarela: guarda el medio y hace el primer cobro. */
  async function subscribeWith(source: TokenizedSource, acceptance: AcceptanceResponse) {
    setError(null);
    setCouponError(null);
    setPaying(true);
    try {
      const started = await withToken((t) =>
        billingApi.subscribe(t, {
          plan_id: planId,
          coupon_code: appliedCode,
          renewal_mode: "automatic",
          payment_source_token: source.token,
          payment_source_type: source.type,
          acceptance_token: acceptance.acceptance_token,
          personal_data_token: acceptance.personal_data_token,
        }),
      );
      // El cobro ya se envió: la pantalla de resultado espera la respuesta.
      router.push(`/pago/${started.payment_id}`);
    } catch (e) {
      handleFailure(e);
    }
  }

  const blocked = paying || quoting || !user.email_verified;

  return (
    <div className="space-y-5">
      <Card>
        <h2 className="font-display text-2xl font-semibold leading-tight text-white">
          {plan.name}
        </h2>
        <p className="mt-1 text-sm text-muted">
          {renewing
            ? `Siguiente período: ${period} de acceso.`
            : `${period.charAt(0).toUpperCase()}${period.slice(1)} de acceso.`}
        </p>
        {renewing && current.current_period_end ? (
          <p className="mt-3 text-sm text-white">
            Tu acceso actual va hasta el {formatLegalDate(current.current_period_end)}. El período
            nuevo empieza ese día: no pierdes los días que te quedan.
          </p>
        ) : null}
        {renewing && availability.tokenizer !== null ? (
          <p className="mt-3 text-sm text-muted">
            Si prefieres que se renueve sola, sin pagar nada hoy,{" "}
            <Link href="/cuenta" className={LINK}>
              activa la renovación automática desde tu cuenta
            </Link>
            .
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
                <dt className="text-muted">Descuento{appliedCode ? ` (${appliedCode})` : ""}</dt>
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
              {totalText}
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

      {automaticOffered ? (
        <Card>
          <fieldset>
            <legend className="text-base font-bold text-white">¿Cómo quieres pagar?</legend>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <ModeOption
                value="manual"
                chosen={mode}
                onChoose={chooseMode}
                title="Pago manual"
                lines={[
                  `Pagas ${period} de acceso ahora.`,
                  "Eliges el medio en la página de la pasarela.",
                  "No se guarda tu medio de pago ni se renueva solo. Antes de que venza te avisamos por correo.",
                ]}
              />
              <ModeOption
                value="automatic"
                chosen={mode}
                onChoose={chooseMode}
                title="Renovación automática"
                lines={[
                  `Se cobra ahora y luego cada ${interval}, hasta que canceles.`,
                  "Guardas un medio de pago; sus datos van directo a la pasarela.",
                  "Antes de cada cobro te avisamos por correo con el monto y la fecha. Cancelas cuando quieras desde tu cuenta.",
                ]}
              />
            </div>
          </fieldset>

          {mode === "automatic" ? (
            <div className="mt-5 border-t border-edge pt-4">
              <PaymentSourceForm
                availability={availability}
                submitLabel={`Guardar medio de pago y pagar ${totalText}`}
                busyLabel="Enviando el cobro…"
                busy={paying}
                disabled={blocked}
                onSource={subscribeWith}
              />
            </div>
          ) : null}
        </Card>
      ) : null}

      {user.email_verified ? null : <VerifyEmailNotice />}
      {error ? <ErrorBox message={error} /> : null}

      <div className="space-y-3">
        {chosen === "automatic" ? null : (
          <Button onClick={payManually} disabled={blocked || chosen === null}>
            {paying ? "Abriendo el pago…" : `Ir a pagar ${totalText}`}
          </Button>
        )}
        {user.email_verified ? null : (
          <p className="text-sm text-muted">Confirma tu correo para poder pagar.</p>
        )}
        {chosen === null ? (
          <p className="text-sm text-muted">Elige cómo quieres pagar para continuar.</p>
        ) : null}
        <p className="max-w-prose text-xs leading-relaxed text-muted">
          {chosen === "automatic"
            ? null
            : "Al continuar vas a la página de la pasarela de pagos, donde eliges el medio de pago. Sebasanálisis no recibe ni guarda los datos de tu tarjeta ni de tu cuenta. "}
          La suscripción da acceso a la plataforma: no cambia el resultado de ningún juego ni la
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

function ModeOption({
  value,
  chosen,
  onChoose,
  title,
  lines,
}: {
  value: RenewalMode;
  chosen: RenewalMode | null;
  onChoose: (mode: RenewalMode) => void;
  title: string;
  lines: string[];
}) {
  const selected = chosen === value;
  return (
    <label
      className={`block cursor-pointer rounded-lg border p-3.5 transition-colors ${
        selected ? "border-gold bg-gold/10" : "border-edge bg-ink hover:border-gold/50"
      }`}
    >
      <span className="flex items-center gap-2.5">
        <input
          type="radio"
          name="renewal-mode"
          value={value}
          checked={selected}
          onChange={() => onChoose(value)}
          className="h-4 w-4 accent-gold"
        />
        <span className="text-sm font-bold text-white">{title}</span>
      </span>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-relaxed text-muted">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </label>
  );
}

export default function CheckoutPage() {
  return (
    <>
      <AppHeader />
      <main className="mx-auto flex w-full max-w-xl flex-1 flex-col px-4 pb-12 pt-6 sm:px-6">
        <Link href="/planes" className={`inline-flex min-h-11 items-center self-start text-sm ${LINK}`}>
          <span aria-hidden className="mr-1.5">←</span>Volver a los planes
        </Link>
        <h1 className="mt-3 font-display text-4xl font-semibold leading-none tracking-tight">
          Confirma tu pago
        </h1>
        <div className="mt-6">
          {/* useSearchParams necesita un límite de Suspense para el build estático. */}
          <Suspense fallback={null}>
            <Checkout />
          </Suspense>
        </div>
      </main>
    </>
  );
}
