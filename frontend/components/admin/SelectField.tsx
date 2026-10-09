"use client";

/** Lista desplegable con su etiqueta, par de `Field`. */

export function SelectField<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
  hint,
}: {
  label: string;
  value: T;
  options: readonly (readonly [T, string])[];
  onChange: (value: T) => void;
  disabled?: boolean;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-bold text-white">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as T)}
        className="w-full rounded-lg border border-edge bg-ink-sunken px-3 py-2.5 text-sm text-white outline-none focus:border-gold/60 disabled:opacity-60"
      >
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}
