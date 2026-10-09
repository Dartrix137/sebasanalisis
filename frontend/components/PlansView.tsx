"use client";

/**
 * Los planes que se ofrecen, con su precio (§3.10 de la Fase 4).
 *
 * Regla de esta pantalla: el monto que se cobra es el protagonista y va con su
 * moneda. El precio de presentación (`display_price_cents`) es una referencia
 * fija, no una conversión, y nunca se muestra solo ni como "equivalente".
 *
 * El botón no hace nada todavía: el pago llega con el paso 5.
 */

import { useEffect, useState } from "react";

import { ApiError, billingApi } from "@/lib/api-client";
import { formatMoney, intervalLabel } from "@/lib/money";
import type { PlanResponse } from "@/lib/types/billing";

import { Button, Card, ErrorBox } from "./ui";

const CURRENCY_NAME: Record<string, string> = {
  COP: "pesos colombianos (COP)",
};

export function PlansView() {
  const [plans, setPlans] = useState<PlanResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    billingApi
      .plans()
      .then(setPlans)
      .catch((e) => setError(e instanceof ApiError ? e.message : "No se pudieron cargar los planes"));
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!plans) return null;
  if (plans.length === 0) {
    return <p className="text-sm text-muted">Por ahora no hay planes disponibles.</p>;
  }
  return (
    <div className="space-y-5">
      {plans.map((plan) => (
        <PlanCard key={plan.id} plan={plan} />
      ))}
    </div>
  );
}

function PlanCard({ plan }: { plan: PlanResponse }) {
  const price = formatMoney(plan.price_cents, plan.currency);
  const reference =
    plan.display_price_cents !== null && plan.display_currency !== null
      ? formatMoney(plan.display_price_cents, plan.display_currency)
      : null;
  const currencyName = CURRENCY_NAME[plan.currency] ?? plan.currency;

  return (
    <Card>
      <article aria-label={plan.name} data-testid={`plan-${plan.code}`}>
        <h2 className="font-display text-2xl font-semibold leading-tight text-white">
          {plan.name}
        </h2>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted">{plan.description}</p>

        <p className="mt-5 flex flex-wrap items-baseline gap-x-2">
          <span className="font-display text-4xl font-semibold leading-none text-white">
            {price}
          </span>
          <span className="text-sm text-muted">
            / {intervalLabel(plan.interval, plan.interval_count)}
          </span>
        </p>
        {reference ? (
          <p className="mt-1.5 text-sm text-muted">Precio de referencia: {reference}</p>
        ) : null}

        <p className="mt-4 max-w-prose text-xs leading-relaxed text-muted">
          El cobro se hace siempre en {currencyName}.
          {reference
            ? ` Los ${reference} son una referencia fija y no una conversión.`
            : ""}{" "}
          Si pagas con una tarjeta de otro país, tu banco convierte los {price} a tu moneda con su
          propia tasa y puede cobrar comisiones, así que el valor en tu extracto puede ser
          distinto.
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Button disabled aria-describedby={`pago-${plan.id}`}>
            Suscribirme
          </Button>
          <p id={`pago-${plan.id}`} className="text-xs text-muted">
            El pago estará disponible pronto.
          </p>
        </div>
      </article>
    </Card>
  );
}
