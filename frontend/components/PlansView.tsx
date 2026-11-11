"use client";

/**
 * Los planes que se ofrecen, con su precio (§3.10 de la Fase 4).
 *
 * Regla de esta pantalla: se muestra un solo precio, el que se cobra, con su
 * moneda. No hay precio de referencia en otra moneda (descartado el
 * 2026-10-09): mostrar una cifra que no se cobra presta a confusión.
 *
 * Diseño de las tarjetas (2026-11-11, imagen del usuario): nombre, precio,
 * descripción y un botón de ancho completo. El plan de varios meses que sale
 * más barato que pagar el mensual cada mes va destacado, con su promoción, lo
 * que se ahorra y lo que equivale al mes. Esas cifras son una comparación en
 * la misma moneda, no otro precio: se derivan de los precios que manda el
 * servidor (`planSavings`), y lo que se cobra lo sigue calculando él.
 *
 * Qué botón lleva cada plan (decidido el 2026-10-13) depende de la cuenta, y
 * es solo presentación: quien acepta o rechaza el pago es el servidor.
 *
 * - Sin sesión: enlace para crear la cuenta.
 * - Administrador o acceso manual: ninguno. Ya entra a la mesa sin pagar.
 * - Cuenta suspendida o con documentos legales por aceptar: ninguno. No puede
 *   pagar hasta resolverlo, y la página le dice por qué.
 *   Si además tiene una suscripción vigente, su plan va marcado igual, sin botón.
 * - Con una suscripción pagada y vigente: su plan va marcado "Tu plan actual",
 *   con hasta cuándo tiene acceso y el botón de pagar el período siguiente.
 *   Los demás planes no llevan botón.
 *   Si esa suscripción se renueva sola, no hay botón: se gestiona en la cuenta.
 * - Sin acceso: "Suscribirme" si la pasarela ofrece la renovación automática;
 *   si no (Tipster Page, o sin pasarela), "Elegir plan mensual" (o el período
 *   del plan): es un pago único por período.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError, billingApi } from "@/lib/api-client";
import { formatLegalDate } from "@/lib/legal";
import { CURRENCY_NOTE, formatMoney } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { PlanInterval, PlanResponse, SubscriptionResponse } from "@/lib/types/billing";

import { InlineSkeleton } from "./PageSkeleton";
import { Badge, ErrorBox } from "./ui";

const BUTTON =
  "block w-full rounded-xl px-4 py-3.5 text-center text-lg font-bold transition-colors";
const BUTTON_FEATURED = `${BUTTON} bg-gold text-gold-ink hover:bg-gold-soft`;
const BUTTON_PLAIN = `${BUTTON} bg-gold-deep text-white hover:bg-gold hover:text-gold-ink`;

/** `/ 1 mes`, `/ 2 meses`, `/ 1 año`: el período que compra un pago. */
function perPeriod(interval: PlanInterval, count: number): string {
  if (interval === "month") return `/ ${count} ${count === 1 ? "mes" : "meses"}`;
  return `/ ${count} ${count === 1 ? "año" : "años"}`;
}

/** `mensual`, `bimestral`… o null si el período no tiene nombre corriente. */
function periodAdjective(interval: PlanInterval, count: number): string | null {
  if (interval === "year") return count === 1 ? "anual" : null;
  return { 1: "mensual", 2: "bimestral", 3: "trimestral", 6: "semestral" }[count] ?? null;
}

type Savings = {
  /** Lo que se ahorra frente a pagar el plan mensual cada mes. */
  cents: number;
  /** El ahorro en porcentaje, redondeado hacia abajo: nunca se exagera. */
  percent: number;
  /** El precio del plan repartido entre sus meses. */
  perMonthCents: number;
};

/**
 * Lo que ahorra un plan de varios meses frente al plan mensual de la misma
 * moneda, pagado cada mes. Null si no hay mensual con qué comparar o si no se
 * ahorra nada.
 */
export function planSavings(plan: PlanResponse, plans: PlanResponse[]): Savings | null {
  if (plan.interval !== "month" || plan.interval_count < 2) return null;
  const monthly = plans.find(
    (p) => p.interval === "month" && p.interval_count === 1 && p.currency === plan.currency,
  );
  if (!monthly) return null;
  const full = monthly.price_cents * plan.interval_count;
  const cents = full - plan.price_cents;
  if (cents <= 0) return null;
  return {
    cents,
    percent: Math.floor((cents * 100) / full),
    perMonthCents: Math.round(plan.price_cents / plan.interval_count),
  };
}

export function PlansView() {
  const { user, loading, withToken } = useSession();
  const [plans, setPlans] = useState<PlanResponse[] | null>(null);
  const [paymentsEnabled, setPaymentsEnabled] = useState(false);
  const [automaticOffered, setAutomaticOffered] = useState(false);
  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const userId = user?.id ?? null;

  useEffect(() => {
    billingApi
      .plans()
      .then(setPlans)
      .catch((e) => setError(e instanceof ApiError ? e.message : "No se pudieron cargar los planes"));
    // Si no se sabe, el botón queda apagado: es el estado conservador.
    billingApi
      .availability()
      .then((a) => {
        setPaymentsEnabled(a.enabled);
        setAutomaticOffered(a.enabled && a.tokenizer !== null);
      })
      .catch(() => setPaymentsEnabled(false));
  }, []);

  useEffect(() => {
    if (loading || !userId) return;
    withToken((token) => billingApi.subscription(token))
      .then(setSubscription)
      .catch(() => setSubscription(null));
  }, [loading, userId, withToken]);

  if (error) return <ErrorBox message={error} />;
  if (!plans || loading) return <InlineSkeleton cards={2} />;
  if (plans.length === 0) {
    return <p className="text-sm text-muted">Por ahora no hay planes disponibles.</p>;
  }

  // La suscripción con un período pagado que todavía no vence (lo dice el servidor).
  const current = userId && subscription?.in_force ? subscription : null;
  // Se destaca un solo plan: el que más ahorra frente al mensual.
  const savings = new Map(plans.map((p) => [p.id, planSavings(p, plans)]));
  const featuredId =
    plans
      .filter((p) => savings.get(p.id))
      .sort((a, b) => savings.get(b.id)!.percent - savings.get(a.id)!.percent)[0]?.id ?? null;

  // Una al lado de la otra; en pantallas angostas, una debajo de la otra.
  return (
    <>
      <div className={`grid gap-5 ${plans.length > 1 ? "md:grid-cols-2" : ""}`}>
        {plans.map((plan) => (
          <PlanCard
            key={plan.id}
            plan={plan}
            savings={savings.get(plan.id) ?? null}
            featured={plan.id === featuredId}
            paymentsEnabled={paymentsEnabled}
            automaticOffered={automaticOffered}
            current={current}
          />
        ))}
      </div>
      <p className="mt-5 max-w-prose text-xs leading-relaxed text-muted">{CURRENCY_NOTE}</p>
    </>
  );
}

function CheckIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-5 w-5 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="9.5" />
      <path d="m8 12.5 2.7 2.7L16.2 9.5" />
    </svg>
  );
}

function PlanCard({
  plan,
  savings,
  featured,
  paymentsEnabled,
  automaticOffered,
  current,
}: {
  plan: PlanResponse;
  savings: Savings | null;
  featured: boolean;
  paymentsEnabled: boolean;
  automaticOffered: boolean;
  current: SubscriptionResponse | null;
}) {
  const price = formatMoney(plan.price_cents, plan.currency);
  const isCurrent = current?.plan.id === plan.id;
  const adjective = periodAdjective(plan.interval, plan.interval_count);

  return (
    <section
      className={`h-full rounded-2xl bg-ink-raised p-5 shadow-card sm:p-6 ${
        featured ? "border-2 border-gold" : "border border-edge"
      }`}
    >
      {/* Columna de alto completo: el botón queda alineado entre tarjetas. */}
      <article
        aria-label={plan.name}
        data-testid={`plan-${plan.code}`}
        className="flex h-full flex-col"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-2xl font-semibold leading-tight text-white">
            {plan.name}
          </h2>
          {featured ? (
            <span className="rounded-lg bg-gold px-2.5 py-1 text-xs font-bold uppercase tracking-wide text-gold-ink">
              {adjective ? `Promoción ${adjective}` : "Promoción"}
            </span>
          ) : null}
          {isCurrent ? <Badge tone="ok">Tu plan actual</Badge> : null}
        </div>

        <p className="mt-4 flex flex-wrap items-baseline gap-x-2">
          <span className="font-display text-5xl font-semibold leading-none text-white">
            {price}
          </span>
          <span className="text-lg text-muted">
            {perPeriod(plan.interval, plan.interval_count)}
          </span>
        </p>

        {featured && savings ? (
          <p className="mt-4 flex items-center gap-2 text-lg font-bold text-gold">
            <CheckIcon />
            Ahorras {formatMoney(savings.cents, plan.currency)} ({savings.percent} %)
          </p>
        ) : null}

        <p className="mt-4 max-w-prose text-sm leading-relaxed text-muted">
          {plan.description}
          {savings
            ? ` Equivale a solo ${formatMoney(savings.perMonthCents, plan.currency)} al mes.`
            : ""}
        </p>
        {/*
          Un plan con lista de juegos dice cuáles incluye: quien paga tiene que
          saberlo antes (§7.4). Sin lista, el plan incluye todos y no se dice nada.
        */}
        {!plan.all_games && plan.games.length > 0 ? (
          <p className="mt-2 text-sm text-white">
            Incluye: {plan.games.map((g) => g.name).join(", ")}
          </p>
        ) : null}

        {isCurrent && current?.current_period_end ? (
          <p className="mt-4 text-sm text-white">
            Tienes acceso hasta el {formatLegalDate(current.current_period_end)}.
            {current.price_cents !== plan.price_cents
              ? ` Tu precio es ${formatMoney(current.price_cents, current.currency)}, el que tenía el plan cuando te suscribiste.`
              : ""}
          </p>
        ) : null}

        <PlanAction
          plan={plan}
          buttonClass={featured ? BUTTON_FEATURED : BUTTON_PLAIN}
          choiceLabel={adjective ? `Elegir plan ${adjective}` : "Elegir este plan"}
          paymentsEnabled={paymentsEnabled}
          automaticOffered={automaticOffered}
          current={current}
          isCurrent={isCurrent}
        />
      </article>
    </section>
  );
}

function PlanAction({
  plan,
  buttonClass,
  choiceLabel,
  paymentsEnabled,
  automaticOffered,
  current,
  isCurrent,
}: {
  plan: PlanResponse;
  buttonClass: string;
  choiceLabel: string;
  paymentsEnabled: boolean;
  automaticOffered: boolean;
  current: SubscriptionResponse | null;
  isCurrent: boolean;
}) {
  const { user } = useSession();
  // Sin renovación automática no hay suscripción que se renueve: es un pago por período.
  const payLabel = automaticOffered ? "Suscribirme" : choiceLabel;
  const row = "mt-auto flex flex-col gap-2 pt-5";
  const note = "text-xs text-muted";

  if (!paymentsEnabled) {
    return (
      <div className={row}>
        <button
          type="button"
          disabled
          aria-describedby={`pago-${plan.id}`}
          className={`${buttonClass} cursor-not-allowed opacity-60`}
        >
          {payLabel}
        </button>
        <p id={`pago-${plan.id}`} className={note}>
          El pago estará disponible pronto.
        </p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className={row}>
        <Link href="/register" className={buttonClass}>
          Crear cuenta para suscribirme
        </Link>
      </div>
    );
  }

  // Lo que el servidor rechazaría al pagar, tenga o no una suscripción: un
  // administrador o una cuenta con acceso manual ya entra sin pagar; una
  // suspendida o con documentos legales por aceptar no puede pagar, y el aviso
  // de arriba de la página ya le dice por qué.
  const { granted, reason } = user.access;
  const manualAccess = granted && reason !== "subscription";
  if (manualAccess || reason === "suspended" || reason === "consent_required") {
    return manualAccess && isCurrent ? (
      <div className={row}>
        <p className={note}>
          Tu cuenta tiene acceso sin pagar: mientras lo tenga no necesitas pagar otro período.
        </p>
      </div>
    ) : (
      <div className="mt-auto" />
    );
  }

  if (current) {
    if (!isCurrent) {
      return (
        <div className={row}>
          <p className={note}>
            Para cambiar de plan, espera a que termine el período que ya pagaste.
          </p>
        </div>
      );
    }
    if (current.renewal_mode === "automatic") {
      // Se cobra sola, o está cancelada: en los dos casos se gestiona en la cuenta.
      return (
        <div className={row}>
          <p className={note}>
            {current.status === "canceled"
              ? "Cancelaste la renovación: no se hace ningún cobro más."
              : "Se renueva sola; antes de cada cobro te avisamos por correo."}{" "}
            <Link href="/cuenta" className="font-bold text-gold hover:text-gold-soft">
              Ver mi suscripción
            </Link>
          </p>
        </div>
      );
    }
    return (
      <div className={row}>
        <Link href={`/planes/pagar?plan=${plan.id}`} className={buttonClass}>
          Pagar el siguiente período
        </Link>
        <p className={note}>
          No se renueva solo. El período nuevo empieza cuando termine el actual.
        </p>
      </div>
    );
  }

  return (
    <div className={row}>
      <Link href={`/planes/pagar?plan=${plan.id}`} className={buttonClass}>
        {payLabel}
      </Link>
      {automaticOffered ? null : (
        <p className={note}>Pago único: no se renueva solo.</p>
      )}
    </div>
  );
}
