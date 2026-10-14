"use client";

/**
 * Los planes que se ofrecen, con su precio (§3.10 de la Fase 4).
 *
 * Regla de esta pantalla: se muestra un solo precio, el que se cobra, con su
 * moneda. No hay precio de referencia en otra moneda (descartado el
 * 2026-10-09): mostrar una cifra que no se cobra presta a confusión.
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
 * - Sin acceso: "Suscribirme".
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError, billingApi } from "@/lib/api-client";
import { formatLegalDate } from "@/lib/legal";
import { CURRENCY_NOTE, formatMoney, intervalLabel } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { PlanResponse, SubscriptionResponse } from "@/lib/types/billing";

import { Badge, Card, ErrorBox } from "./ui";

const PAY_LINK =
  "rounded-lg bg-gold px-4 py-2.5 text-sm font-bold text-gold-ink transition-colors hover:bg-gold-soft";

export function PlansView() {
  const { user, loading, withToken } = useSession();
  const [plans, setPlans] = useState<PlanResponse[] | null>(null);
  const [paymentsEnabled, setPaymentsEnabled] = useState(false);
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
      .then((a) => setPaymentsEnabled(a.enabled))
      .catch(() => setPaymentsEnabled(false));
  }, []);

  useEffect(() => {
    if (loading || !userId) return;
    withToken((token) => billingApi.subscription(token))
      .then(setSubscription)
      .catch(() => setSubscription(null));
  }, [loading, userId, withToken]);

  if (error) return <ErrorBox message={error} />;
  if (!plans || loading) return null;
  if (plans.length === 0) {
    return <p className="text-sm text-muted">Por ahora no hay planes disponibles.</p>;
  }

  // La suscripción con un período pagado que todavía no vence (lo dice el servidor).
  const current = userId && subscription?.in_force ? subscription : null;
  // Una al lado de la otra; en pantallas angostas, una debajo de la otra.
  return (
    <div className={`grid gap-5 ${plans.length > 1 ? "md:grid-cols-2" : ""}`}>
      {plans.map((plan) => (
        <PlanCard
          key={plan.id}
          plan={plan}
          paymentsEnabled={paymentsEnabled}
          current={current}
        />
      ))}
    </div>
  );
}

function PlanCard({
  plan,
  paymentsEnabled,
  current,
}: {
  plan: PlanResponse;
  paymentsEnabled: boolean;
  current: SubscriptionResponse | null;
}) {
  const price = formatMoney(plan.price_cents, plan.currency);
  const isCurrent = current?.plan.id === plan.id;

  return (
    <Card className="h-full">
      {/* Columna de alto completo: el botón queda alineado entre tarjetas. */}
      <article
        aria-label={plan.name}
        data-testid={`plan-${plan.code}`}
        className="flex h-full flex-col"
      >
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-display text-2xl font-semibold leading-tight text-white">
            {plan.name}
          </h2>
          {isCurrent ? <Badge tone="ok">Tu plan actual</Badge> : null}
        </div>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted">{plan.description}</p>
        {/*
          Un plan con lista de juegos dice cuáles incluye: quien paga tiene que
          saberlo antes (§7.4). Sin lista, el plan incluye todos y no se dice nada.
        */}
        {!plan.all_games && plan.games.length > 0 ? (
          <p className="mt-2 text-sm text-white">
            Incluye: {plan.games.map((g) => g.name).join(", ")}
          </p>
        ) : null}

        <p className="mt-5 flex flex-wrap items-baseline gap-x-2">
          <span className="font-display text-4xl font-semibold leading-none text-white">
            {price}
          </span>
          <span className="text-sm text-muted">
            / {intervalLabel(plan.interval, plan.interval_count)}
          </span>
        </p>

        <p className="mt-4 max-w-prose text-xs leading-relaxed text-muted">{CURRENCY_NOTE}</p>

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
          paymentsEnabled={paymentsEnabled}
          current={current}
          isCurrent={isCurrent}
        />
      </article>
    </Card>
  );
}

function PlanAction({
  plan,
  paymentsEnabled,
  current,
  isCurrent,
}: {
  plan: PlanResponse;
  paymentsEnabled: boolean;
  current: SubscriptionResponse | null;
  isCurrent: boolean;
}) {
  const { user } = useSession();
  const row = "mt-auto flex flex-wrap items-center gap-3 pt-5";
  const note = "text-xs text-muted";

  if (!paymentsEnabled) {
    return (
      <div className={row}>
        <button
          type="button"
          disabled
          aria-describedby={`pago-${plan.id}`}
          className={`${PAY_LINK} cursor-not-allowed opacity-60`}
        >
          Suscribirme
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
        <Link href="/register" className={PAY_LINK}>
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
        <Link href={`/planes/pagar?plan=${plan.id}`} className={PAY_LINK}>
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
      <Link href={`/planes/pagar?plan=${plan.id}`} className={PAY_LINK}>
        Suscribirme
      </Link>
    </div>
  );
}
