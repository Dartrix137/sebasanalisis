"use client";

/**
 * Juegos que incluye un plan (§4.4 y §7.4 de la Fase 4). Va en `/admin/planes`,
 * debajo del formulario del plan.
 *
 * Sin selección, el plan incluye todos los juegos, también los que se creen
 * después. Lo que decide el acceso es `has_access` en el servidor; aquí solo se
 * elige. Quitarle un juego a un plan con suscripciones vigentes lo rechaza el
 * servidor (409), y su mensaje se muestra tal cual.
 */

import { useCallback, useEffect, useState } from "react";

import { SuccessBox } from "@/components/AuthShell";
import { Button, CardHeader, Checkbox, ErrorBox, Field } from "@/components/ui";
import { GAME_STATUS_LABEL } from "@/lib/admin";
import { ApiError, adminApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type { AdminPlanResponse } from "@/lib/types/billing";
import type { GameResponse } from "@/lib/types/games";

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "No se pudo completar la solicitud";
}

export function PlanGamesPanel({
  plan,
  onDone,
}: {
  plan: AdminPlanResponse;
  onDone: () => Promise<void>;
}) {
  const { withToken } = useSession();
  const [games, setGames] = useState<GameResponse[] | null>(null);
  const [all, setAll] = useState(plan.all_games);
  const [chosen, setChosen] = useState<Set<string>>(new Set(plan.game_ids));
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(async () => {
    setGames((await withToken((t) => adminApi.listGames(t, { limit: 100 }))).items);
  }, [withToken]);

  useEffect(() => {
    load().catch((e) => setError(messageOf(e)));
  }, [load]);

  function toggle(id: string, on: boolean) {
    setChosen((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setSaved(null);
    try {
      await withToken((t) =>
        adminApi.updatePlanGames(t, plan.id, {
          game_ids: all ? [] : [...chosen],
          reason: reason.trim(),
        }),
      );
      setReason("");
      setSaved("Juegos del plan guardados.");
      await onDone();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <section
      className="mt-4 space-y-3 rounded-lg border border-edge p-3.5"
      aria-label="Juegos incluidos"
    >
      <CardHeader
        title="Juegos incluidos"
        subtitle="Agregar un juego siempre se puede. Quitarlo no, mientras el plan tenga suscripciones vigentes: lo que ya se pagó no cambia a mitad del período."
      />
      {games === null ? null : (
        <form onSubmit={handleSubmit} className="space-y-3">
          <Checkbox checked={all} onChange={(e) => setAll(e.target.checked)}>
            Todos los juegos, también los que se creen después
          </Checkbox>
          {!all ? (
            <ul className="grid gap-2 sm:grid-cols-2">
              {games.map((g) => (
                <li key={g.id}>
                  <Checkbox
                    checked={chosen.has(g.id)}
                    onChange={(e) => toggle(g.id, e.target.checked)}
                  >
                    {g.name}{" "}
                    <span className="text-muted">({GAME_STATUS_LABEL[g.status].toLowerCase()})</span>
                  </Checkbox>
                </li>
              ))}
            </ul>
          ) : null}
          {!all && chosen.size === 0 ? (
            <p className="text-xs text-muted">
              Sin ningún juego marcado, el plan vuelve a incluirlos todos.
            </p>
          ) : null}
          <Field
            label="Motivo del cambio de juegos"
            required
            minLength={3}
            hint="Queda en la bitácora."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          {error ? <ErrorBox message={error} /> : null}
          {saved ? <SuccessBox message={saved} /> : null}
          <Button type="submit" disabled={pending}>
            {pending ? "Guardando…" : "Guardar juegos"}
          </Button>
        </form>
      )}
    </section>
  );
}
