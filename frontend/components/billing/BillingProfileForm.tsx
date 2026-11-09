"use client";

/**
 * Los datos de facturación del comprador (§3.17 de la Fase 4, "Paso 5.4",
 * punto 8): la factura electrónica va a su nombre, con su documento, su
 * dirección y su ciudad.
 *
 * Los países, los departamentos y las ciudades salen de la lista de Siigo
 * (`GET /billing/places/*`): Siigo rechaza un código que no está en ella, así
 * que la ciudad se elige, no se escribe. El tipo de documento depende del país:
 * cédula (o cédula de extranjería) en Colombia; NIT de otro país, pasaporte o
 * documento extranjero fuera. Quien valida es el servidor; aquí solo se
 * muestran sus errores campo por campo.
 *
 * Son datos personales: van a la API y de ahí a Siigo. No se guardan en el
 * navegador.
 */

import { useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { Button, ErrorBox, Field } from "@/components/ui";
import { ApiError, billingApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type {
  BillingProfileResponse,
  CityResponse,
  CountryResponse,
} from "@/lib/types/billing-profile";

const SELECT =
  "min-h-12 w-full rounded-lg border bg-ink-sunken px-3 py-2.5 text-base text-white outline-none sm:text-sm";
const COLOMBIA = "Co";

type Values = {
  first_names: string;
  last_names: string;
  country_code: string;
  id_type: string;
  id_number: string;
  address: string;
  state_code: string;
  city_code: string;
};

function initialValues(profile: BillingProfileResponse | null): Values {
  return {
    first_names: profile?.first_names ?? "",
    last_names: profile?.last_names ?? "",
    country_code: profile?.country_code ?? COLOMBIA,
    id_type: profile?.id_type ?? "13",
    id_number: profile?.id_number ?? "",
    address: profile?.address ?? "",
    state_code: profile?.state_code ?? "",
    city_code: profile?.city_code ?? "",
  };
}

function SelectField({
  label,
  name,
  value,
  onChange,
  disabled,
  error,
  hint,
  children,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  error?: string;
  hint?: string;
  children: ReactNode;
}) {
  const message = error ?? hint;
  const messageId = `${name}-mensaje`;
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-bold text-white">{label}</span>
      <select
        name={name}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={message ? messageId : undefined}
        className={`${SELECT} ${error ? "border-table-red/70" : "border-edge focus:border-gold/60"}`}
      >
        {children}
      </select>
      {message ? (
        <span
          id={messageId}
          className={`mt-1 block text-xs ${error ? "font-bold text-table-red" : "text-muted"}`}
        >
          {message}
        </span>
      ) : null}
    </label>
  );
}

export function BillingProfileForm({
  profile,
  onSaved,
  onCancel,
  submitLabel = "Guardar datos de facturación",
}: {
  profile: BillingProfileResponse | null;
  onSaved: (profile: BillingProfileResponse) => void;
  onCancel?: () => void;
  submitLabel?: string;
}) {
  const { withToken } = useSession();
  const [values, setValues] = useState<Values>(() => initialValues(profile));
  const [countries, setCountries] = useState<CountryResponse[] | null>(null);
  // Las ciudades del último país que se cargó: si no son del elegido, aún no llegan.
  const [loaded, setLoaded] = useState<{ country: string; list: CityResponse[] } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    withToken((t) => billingApi.billingCountries(t))
      .then((list) => {
        if (!cancelled) setCountries(list);
      })
      .catch(() => {
        if (!cancelled) setError("No se pudo cargar la lista de países.");
      });
    return () => {
      cancelled = true;
    };
  }, [withToken]);

  const country = values.country_code;
  useEffect(() => {
    let cancelled = false;
    withToken((t) => billingApi.billingCities(t, country))
      .then((list) => {
        if (!cancelled) setLoaded({ country, list });
      })
      .catch(() => {
        if (!cancelled) setError("No se pudo cargar la lista de ciudades.");
      });
    return () => {
      cancelled = true;
    };
  }, [withToken, country]);

  const current = countries?.find((c) => c.code === country) ?? null;
  const cities = loaded?.country === country ? loaded.list : null;
  const states = useMemo(() => {
    const seen = new Map<string, string>();
    for (const c of cities ?? []) if (!seen.has(c.state_code)) seen.set(c.state_code, c.state);
    return [...seen.entries()];
  }, [cities]);
  const citiesOfState = (cities ?? []).filter((c) => c.state_code === values.state_code);
  const colombia = country === COLOMBIA;

  function set<K extends keyof Values>(key: K, value: Values[K]) {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors((e) => {
      const next = { ...e };
      delete next[key];
      if (key === "city_code") delete next.city;
      return next;
    });
  }

  function chooseCountry(code: string) {
    const next = countries?.find((c) => c.code === code);
    setValues((v) => ({
      ...v,
      country_code: code,
      id_type: next?.default_id_type ?? v.id_type,
      state_code: "",
      city_code: "",
    }));
    setErrors({});
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setErrors({});
    setSaving(true);
    try {
      const saved = await withToken((t) => billingApi.saveBillingProfile(t, values));
      onSaved(saved);
    } catch (e) {
      if (e instanceof ApiError && e.fieldErrors) setErrors(e.fieldErrors);
      setError(e instanceof ApiError ? e.message : "No se pudieron guardar los datos.");
    } finally {
      setSaving(false);
    }
  }

  if (!countries) return error ? <ErrorBox message={error} /> : <p className="text-sm text-muted">Cargando…</p>;

  return (
    <form onSubmit={submit} className="space-y-4" data-testid="datos-de-facturacion">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Nombres"
          name="first_names"
          autoComplete="given-name"
          value={values.first_names}
          maxLength={50}
          required
          onChange={(e) => set("first_names", e.target.value)}
          error={errors.first_names}
        />
        <Field
          label="Apellidos"
          name="last_names"
          autoComplete="family-name"
          value={values.last_names}
          maxLength={50}
          required
          onChange={(e) => set("last_names", e.target.value)}
          error={errors.last_names}
        />
      </div>

      <SelectField
        label="País"
        name="country_code"
        value={values.country_code}
        onChange={chooseCountry}
        disabled={saving}
        error={errors.country_code}
      >
        {countries.map((c) => (
          <option key={c.code} value={c.code}>
            {c.name}
          </option>
        ))}
      </SelectField>

      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField
          label="Tipo de documento"
          name="id_type"
          value={values.id_type}
          onChange={(v) => set("id_type", v)}
          disabled={saving}
          error={errors.id_type}
        >
          {(current?.id_types ?? []).map((t) => (
            <option key={t.code} value={t.code}>
              {t.name}
            </option>
          ))}
        </SelectField>
        <Field
          label="Número de documento"
          name="id_number"
          autoComplete="off"
          inputMode={values.id_type === "13" ? "numeric" : undefined}
          value={values.id_number}
          maxLength={30}
          required
          onChange={(e) => set("id_number", e.target.value)}
          error={errors.id_number}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField
          label={colombia ? "Departamento" : "Estado o región"}
          name="state_code"
          value={values.state_code}
          onChange={(v) => setValues((s) => ({ ...s, state_code: v, city_code: "" }))}
          disabled={saving || !cities}
        >
          <option value="" disabled>
            {cities ? "Elige uno" : "Cargando…"}
          </option>
          {states.map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </SelectField>
        <SelectField
          label={colombia ? "Municipio" : "Ciudad"}
          name="city_code"
          value={values.city_code}
          onChange={(v) => set("city_code", v)}
          disabled={saving || !values.state_code}
          error={errors.city}
        >
          <option value="" disabled>
            Elige una
          </option>
          {citiesOfState.map((c) => (
            <option key={c.city_code} value={c.city_code}>
              {c.city}
            </option>
          ))}
        </SelectField>
      </div>
      {colombia ? null : (
        <p className="-mt-2 text-xs leading-relaxed text-muted">
          La lista de ciudades de fuera de Colombia es corta. Si la tuya no está, elige la más
          cercana y escribe tu ciudad en la dirección.
        </p>
      )}

      <Field
        label="Dirección"
        name="address"
        autoComplete="street-address"
        value={values.address}
        maxLength={256}
        required
        onChange={(e) => set("address", e.target.value)}
        error={errors.address}
      />

      <p className="text-xs leading-relaxed text-muted">
        Son los datos de tu factura electrónica: va a tu nombre y te llega al correo de tu cuenta.
        Los usamos solo para facturar.
      </p>

      {error ? <ErrorBox message={error} /> : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={saving || !cities}>
          {saving ? "Guardando…" : submitLabel}
        </Button>
        {onCancel ? (
          <Button type="button" variant="ghost" onClick={onCancel} disabled={saving}>
            Cancelar
          </Button>
        ) : null}
      </div>
    </form>
  );
}

/** Los datos guardados, en pocas líneas. */
export function BillingProfileSummary({ profile }: { profile: BillingProfileResponse }) {
  return (
    <dl className="space-y-1 text-sm" data-testid="resumen-facturacion">
      <div>
        <dt className="sr-only">Nombre</dt>
        <dd className="font-bold text-white">
          {profile.first_names} {profile.last_names}
        </dd>
      </div>
      <div>
        <dt className="sr-only">Documento</dt>
        <dd className="text-muted">
          {profile.id_type_name} {profile.id_number}
        </dd>
      </div>
      <div>
        <dt className="sr-only">Dirección</dt>
        <dd className="text-muted">
          {profile.address}, {profile.city} ({profile.state}), {profile.country}
        </dd>
      </div>
    </dl>
  );
}
