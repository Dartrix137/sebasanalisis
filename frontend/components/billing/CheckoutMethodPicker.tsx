"use client";

/**
 * El país, el medio de pago y los datos que pide ese medio (Fase 5, paso 5.3).
 *
 * Tipster Page ofrece medios distintos según el país del comprador (manual V2
 * §5). El país lo elige el cliente (decidido el 2026-11-03): no se adivina por
 * la IP. El catálogo lo pide la API, que es la que tiene las llaves.
 *
 * Los datos del comprador que pide un medio (nombre, apellidos, documento,
 * teléfono) viajan a la pasarela al abrir el pago y no se guardan en
 * Sebasanálisis. Aquí solo viven mientras se llena el formulario.
 *
 * El monto no se valida aquí como regla: lo vuelve a revisar el servidor. Solo
 * se marca el medio que no admite el total, para que el cliente no lo elija.
 */

import { useEffect, useRef, useState } from "react";

import { ErrorBox, Field } from "@/components/ui";
import { ApiError, billingApi } from "@/lib/api-client";
import { formatMoney } from "@/lib/money";
import { useSession } from "@/lib/session";
import type { BuyerData, BuyerFieldName, CheckoutMethodResponse } from "@/lib/types/billing";

/** Lo que el cliente eligió, listo para abrir el pago. */
export interface CheckoutChoice {
  method: string;
  /** Null con "Otro país": solo se ofrecen los medios que no dependen del país. */
  country: string | null;
  buyer: BuyerData;
}

/**
 * Los países con medios propios en el catálogo de Tipster Page (manual V2
 * §5.1). Con cualquier otro, "Otro país": tarjeta.
 */
const COUNTRIES: [string, string][] = [
  ["DE", "Alemania"],
  ["AR", "Argentina"],
  ["AT", "Austria"],
  ["BE", "Bélgica"],
  ["BO", "Bolivia"],
  ["BR", "Brasil"],
  ["CA", "Canadá"],
  ["CL", "Chile"],
  ["CO", "Colombia"],
  ["EC", "Ecuador"],
  ["SK", "Eslovaquia"],
  ["ES", "España"],
  ["US", "Estados Unidos"],
  ["FR", "Francia"],
  ["GR", "Grecia"],
  ["IE", "Irlanda"],
  ["IT", "Italia"],
  ["MX", "México"],
  ["NL", "Países Bajos"],
  ["PY", "Paraguay"],
  ["PE", "Perú"],
  ["PL", "Polonia"],
  ["PT", "Portugal"],
  ["GB", "Reino Unido"],
  ["CH", "Suiza"],
  ["UY", "Uruguay"],
  ["VE", "Venezuela"],
];
const OTHER = "otro";

const FIELD_LABELS: Record<BuyerFieldName, { label: string; autoComplete: string; max: number }> = {
  first_name: { label: "Nombre", autoComplete: "given-name", max: 80 },
  last_name: { label: "Apellidos", autoComplete: "family-name", max: 80 },
  personal_id: { label: "Documento de identidad", autoComplete: "off", max: 40 },
  phone: { label: "Teléfono", autoComplete: "tel", max: 30 },
};

const SELECT =
  "w-full rounded-lg border border-edge bg-ink-sunken px-3 py-2.5 text-sm text-white outline-none focus:border-gold/60";

export function CheckoutMethodPicker({
  totalCents,
  currency,
  disabled = false,
  onChange,
}: {
  totalCents: number;
  currency: string;
  disabled?: boolean;
  /** Null mientras falte el país, el medio o un dato que pide el medio. */
  onChange: (choice: CheckoutChoice | null) => void;
}) {
  const { withToken } = useSession();
  // Ningún país entra elegido: lo dice el cliente.
  const [country, setCountry] = useState("");
  const [methods, setMethods] = useState<CheckoutMethodResponse[] | null>(null);
  const [loadingMethods, setLoadingMethods] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [methodKey, setMethodKey] = useState<string | null>(null);
  const [buyer, setBuyer] = useState<Partial<Record<BuyerFieldName, string>>>({});
  // La última consulta del catálogo: una respuesta de un país anterior no pisa la del actual.
  const request = useRef(0);

  const method = methods?.find((m) => m.key === methodKey) ?? null;
  const fits = (m: CheckoutMethodResponse) =>
    m.currency === currency && m.min_cents <= totalCents && totalCents <= m.max_cents;
  const methodFits = method !== null && fits(method);

  useEffect(() => {
    if (!method || !methodFits) {
      onChange(null);
      return;
    }
    const values: BuyerData = {};
    for (const field of method.fields) {
      const value = (buyer[field] ?? "").trim();
      if (!value) {
        onChange(null);
        return;
      }
      values[field] = value;
    }
    onChange({ method: method.key, country: country === OTHER ? null : country, buyer: values });
  }, [method, methodFits, buyer, country, onChange]);

  function chooseCountry(next: string) {
    setCountry(next);
    setMethods(null);
    setMethodKey(null);
    setError(null);
    setLoadingMethods(true);
    const mine = ++request.current;
    withToken((t) => billingApi.paymentMethods(t, next === OTHER ? null : next))
      .then((found) => {
        if (mine === request.current) setMethods(found);
      })
      .catch((e) => {
        if (mine === request.current) {
          setError(e instanceof ApiError ? e.message : "No se pudieron cargar los medios de pago");
        }
      })
      .finally(() => {
        if (mine === request.current) setLoadingMethods(false);
      });
  }

  return (
    <div className="space-y-4">
      <label className="block">
        <span className="mb-1.5 block text-sm font-bold text-white">País desde el que pagas</span>
        <select
          value={country}
          onChange={(e) => chooseCountry(e.target.value)}
          disabled={disabled}
          className={SELECT}
          data-testid="pais-de-pago"
        >
          <option value="" disabled>
            Elige tu país
          </option>
          {COUNTRIES.map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
          <option value={OTHER}>Otro país</option>
        </select>
      </label>

      {error ? <ErrorBox message={error} /> : null}
      {loadingMethods ? <p className="text-sm text-muted">Cargando los medios de pago…</p> : null}

      {methods && !loadingMethods ? (
        methods.length === 0 ? (
          <p className="text-sm text-muted">
            No hay medios de pago disponibles para ese país. Prueba con &quot;Otro país&quot;.
          </p>
        ) : (
          <fieldset>
            <legend className="mb-2 text-sm font-bold text-white">Medio de pago</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {methods.map((m) => {
                const available = fits(m);
                const selected = m.key === methodKey;
                return (
                  <label
                    key={m.key}
                    className={`flex items-center gap-3 rounded-lg border p-3 transition-colors ${
                      !available
                        ? "cursor-not-allowed border-edge opacity-50"
                        : selected
                          ? "cursor-pointer border-gold bg-gold/10"
                          : "cursor-pointer border-edge bg-ink hover:border-gold/50"
                    }`}
                  >
                    <input
                      type="radio"
                      name="payment-method"
                      value={m.key}
                      checked={selected}
                      disabled={disabled || !available}
                      onChange={() => setMethodKey(m.key)}
                      className="h-4 w-4 shrink-0 accent-gold"
                    />
                    {m.logo_url ? (
                      // Logo del CDN de la pasarela (va en la CSP, `lib/csp.ts`).
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={m.logo_url}
                        alt=""
                        className="h-7 w-12 shrink-0 rounded bg-white object-contain p-0.5"
                        loading="lazy"
                      />
                    ) : null}
                    <span className="min-w-0 text-sm">
                      <span className="block font-bold text-white">{m.name}</span>
                      {available ? null : (
                        <span className="block text-xs text-muted">
                          Admite de {formatMoney(m.min_cents, m.currency)} a{" "}
                          {formatMoney(m.max_cents, m.currency)}
                        </span>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        )
      ) : null}

      {method && method.fields.length > 0 ? (
        <div className="space-y-3">
          <p className="text-xs leading-relaxed text-muted">
            {method.name} pide estos datos. Se envían a la pasarela de pagos para crear el pago y
            Sebasanálisis no los guarda.
          </p>
          {method.fields.map((field) => (
            <Field
              key={field}
              label={FIELD_LABELS[field].label}
              name={field}
              autoComplete={FIELD_LABELS[field].autoComplete}
              maxLength={FIELD_LABELS[field].max}
              value={buyer[field] ?? ""}
              disabled={disabled}
              onChange={(e) => setBuyer((prev) => ({ ...prev, [field]: e.target.value }))}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
