"use client";

/**
 * Formulario estructurado para crear/editar una variante de juego.
 *
 * Deliberadamente NO es un builder visual de categorías (CLAUDE.md lo pospone
 * fuera del MVP): es un formulario de campos, con la lista de resultados y las
 * categorías como texto separado por comas. La validación real vive en el
 * backend (`core/game_config_validation.py`); aquí solo se muestran sus errores.
 */

import { useState } from "react";

import type {
  AllowedCombination,
  CategoryGroup,
  GameCategory,
  GameVariantConfig,
  GameVariantResponse,
} from "@/lib/types/games";

import { Button, ErrorBox, Field } from "../ui";

interface Props {
  initial?: GameVariantResponse;
  pending: boolean;
  error?: { message: string; details?: string[] } | null;
  onCancel: () => void;
  onSubmit: (body: {
    name: string;
    house_edge: number;
    config: GameVariantConfig;
    active: boolean;
  }) => void;
}

interface GroupDraft {
  key: string;
  label: string;
  outcomes: string;
  payout: string;
  /** Si el grupo entra al catálogo de mercados del motor (§2.10). */
  market: boolean;
}

interface CategoryDraft {
  id: string;
  label: string;
  shrinkageAlpha: string;
  groups: GroupDraft[];
}

const splitList = (raw: string): string[] =>
  raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

function toDrafts(config?: GameVariantConfig): CategoryDraft[] {
  if (!config) return [emptyCategory()];
  return config.categories.map((cat) => ({
    id: cat.id,
    label: cat.label,
    shrinkageAlpha: String(cat.shrinkage_alpha),
    groups: Object.entries(cat.groups).map(([key, g]) => ({
      key,
      label: g.label ?? "",
      outcomes: g.outcomes.join(", "),
      payout: String(g.payout),
      market: g.market,
    })),
  }));
}

const emptyGroup = (): GroupDraft => ({
  key: "",
  label: "",
  outcomes: "",
  payout: "1",
  market: true,
});
const emptyCategory = (): CategoryDraft => ({
  id: "",
  label: "",
  shrinkageAlpha: "8",
  groups: [emptyGroup(), emptyGroup()],
});

export function VariantForm({ initial, pending, error, onCancel, onSubmit }: Props) {
  const [name, setName] = useState(initial?.name ?? "");
  const [houseEdge, setHouseEdge] = useState(String(initial?.house_edge ?? "0.027"));
  const [active, setActive] = useState(initial?.active ?? true);
  const [outcomes, setOutcomes] = useState(
    initial?.config.possible_outcomes.join(", ") ?? "",
  );
  const [categories, setCategories] = useState<CategoryDraft[]>(toDrafts(initial?.config));
  const [threshold, setThreshold] = useState(
    String(initial?.config.recommendation_threshold ?? 50),
  );
  const [weakThreshold, setWeakThreshold] = useState(
    String(initial?.config.weak_threshold ?? 35),
  );
  /*
    Las combinaciones permitidas (dos docenas, dos columnas) se conservan tal
    como están: editarlas pediría el builder visual que CLAUDE.md deja fuera del
    MVP. Lo que no se puede hacer es perderlas al guardar — sin ellas el motor
    se queda sin los mercados combinados de §2.10.
  */
  const combinations: AllowedCombination[] = initial?.config.allowed_combinations ?? [];

  function patchCategory(index: number, patch: Partial<CategoryDraft>) {
    setCategories((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }

  function patchGroup(catIndex: number, groupIndex: number, patch: Partial<GroupDraft>) {
    setCategories((prev) =>
      prev.map((c, i) =>
        i === catIndex
          ? {
              ...c,
              groups: c.groups.map((g, j) => (j === groupIndex ? { ...g, ...patch } : g)),
            }
          : c,
      ),
    );
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const config: GameVariantConfig = {
      possible_outcomes: splitList(outcomes),
      categories: categories.map<GameCategory>((cat) => ({
        id: cat.id.trim(),
        label: cat.label.trim(),
        shrinkage_alpha: Number(cat.shrinkageAlpha),
        groups: Object.fromEntries(
          cat.groups
            .filter((g) => g.key.trim())
            .map<[string, CategoryGroup]>((g) => [
              g.key.trim(),
              {
                label: g.label.trim() || null,
                outcomes: splitList(g.outcomes),
                payout: Number(g.payout),
                market: g.market,
              },
            ]),
        ),
      })),
      allowed_combinations: combinations,
      recommendation_threshold: Number(threshold),
      weak_threshold: Number(weakThreshold),
    };
    onSubmit({ name: name.trim(), house_edge: Number(houseEdge), config, active });
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Nombre de la variante"
          required
          placeholder="european"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Field
          label="Ventaja de la casa"
          required
          type="number"
          step="0.00001"
          min={0}
          max={1}
          hint="Como fracción: 0.027 es 2.70 %"
          value={houseEdge}
          onChange={(e) => setHouseEdge(e.target.value)}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Umbral de señal débil"
          required
          type="number"
          step="1"
          min={0}
          max={Number(threshold) || 100}
          hint="Desde aquí el motor recomienda, con la apuesta base y sin progresiones (§2.10). Por debajo, NO APOSTAR. Por defecto 35; igualarlo al de señal media apaga la señal débil."
          value={weakThreshold}
          onChange={(e) => setWeakThreshold(e.target.value)}
        />
        <Field
          label="Umbral de señal media"
          required
          type="number"
          step="1"
          min={0}
          max={100}
          hint="Desde aquí la señal es MEDIA y se ofrecen las progresiones. FUERTE empieza en 80. Por defecto 50."
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
        />
      </div>

      <label className="block">
        <span className="mb-1.5 block text-sm font-bold text-white">Resultados posibles</span>
        <textarea
          required
          rows={3}
          placeholder="0, 1, 2, 3, …, 36"
          value={outcomes}
          onChange={(e) => setOutcomes(e.target.value)}
          className="w-full rounded-lg border border-edge bg-ink-sunken px-3.5 py-2.5 font-mono text-xs text-white outline-none placeholder:text-muted/70 focus:border-gold/60"
        />
        <span className="mt-1 block text-xs text-muted">
          Separados por coma. Se admite cualquier etiqueta de texto, como &quot;00&quot;.
        </span>
      </label>

      <div className="space-y-4">
        {categories.map((cat, ci) => (
          <fieldset key={ci} className="rounded-card border border-edge bg-ink p-4">
            <legend className="px-2 text-xs font-bold uppercase tracking-wide text-muted">
              Categoría {ci + 1}
            </legend>

            <div className="grid gap-3 sm:grid-cols-3">
              <Field
                label="id"
                required
                placeholder="dozen"
                value={cat.id}
                onChange={(e) => patchCategory(ci, { id: e.target.value })}
              />
              <Field
                label="Etiqueta"
                required
                placeholder="Docena"
                value={cat.label}
                onChange={(e) => patchCategory(ci, { label: e.target.value })}
              />
              <Field
                label="shrinkage_alpha"
                required
                type="number"
                step="1"
                min={1}
                hint="8 binarias · 12 de tres grupos"
                value={cat.shrinkageAlpha}
                onChange={(e) => patchCategory(ci, { shrinkageAlpha: e.target.value })}
              />
            </div>

            <div className="mt-4 space-y-3">
              {cat.groups.map((g, gi) => (
                <div key={gi} className="grid gap-3 sm:grid-cols-4">
                  <Field
                    label="Grupo"
                    placeholder="first"
                    value={g.key}
                    onChange={(e) => patchGroup(ci, gi, { key: e.target.value })}
                  />
                  <Field
                    label="Etiqueta"
                    placeholder="1ª docena"
                    value={g.label}
                    onChange={(e) => patchGroup(ci, gi, { label: e.target.value })}
                  />
                  <Field
                    label="Resultados"
                    placeholder="1, 2, 3…"
                    value={g.outcomes}
                    onChange={(e) => patchGroup(ci, gi, { outcomes: e.target.value })}
                  />
                  <Field
                    label="Pago"
                    type="number"
                    step="0.5"
                    min={0.5}
                    value={g.payout}
                    onChange={(e) => patchGroup(ci, gi, { payout: e.target.value })}
                  />
                  <label className="flex items-end gap-2 pb-2.5 text-xs text-muted">
                    <input
                      type="checkbox"
                      checked={g.market}
                      onChange={(e) => patchGroup(ci, gi, { market: e.target.checked })}
                      className="h-4 w-4 accent-gold"
                    />
                    <span>
                      Recomendable
                      <span className="block text-muted/80">
                        Desmárcalo para grupos que no son una zona de apuesta, como
                        el verde del 0.
                      </span>
                    </span>
                  </label>
                </div>
              ))}
            </div>

            <div className="mt-3 flex gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() =>
                  patchCategory(ci, { groups: [...cat.groups, emptyGroup()] })
                }
              >
                + Grupo
              </Button>
              {categories.length > 1 ? (
                <Button
                  type="button"
                  variant="danger"
                  onClick={() => setCategories((prev) => prev.filter((_, i) => i !== ci))}
                >
                  Quitar categoría
                </Button>
              ) : null}
            </div>
          </fieldset>
        ))}

        <Button
          type="button"
          variant="ghost"
          onClick={() => setCategories((prev) => [...prev, emptyCategory()])}
        >
          + Categoría
        </Button>
      </div>

      <label className="flex items-center gap-2 text-sm text-white">
        <input
          type="checkbox"
          checked={active}
          onChange={(e) => setActive(e.target.checked)}
          className="h-4 w-4 accent-gold"
        />
        Variante activa
      </label>

      {error ? <ErrorBox message={error.message} details={error.details} /> : null}

      <div className="flex gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Guardando…" : initial ? "Guardar cambios" : "Crear variante"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancelar
        </Button>
      </div>
    </form>
  );
}
