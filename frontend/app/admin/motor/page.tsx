"use client";

/**
 * Admin: métricas internas del motor (§2.10 y §4.1 de la Fase 4). Es la
 * excepción de lenguaje del producto: el cliente no ve nada de esto, y aquí
 * "aciertos" y "fallos" se llaman así.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { BacktestPanel } from "@/components/admin/BacktestPanel";
import { PageSkeleton } from "@/components/PageSkeleton";
import { ErrorBox } from "@/components/ui";
import { adminApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type { GameResponse } from "@/lib/types/games";

export default function AdminEnginePage() {
  const { user, loading, withToken } = useSession();
  const router = useRouter();
  const [games, setGames] = useState<GameResponse[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setGames((await withToken((t) => adminApi.listGames(t))).items);
  }, [withToken]);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (user.role !== "admin") {
      router.replace("/dashboard");
      return;
    }
    load().catch((e) => setError(e instanceof Error ? e.message : "Error inesperado"));
  }, [loading, user, router, load]);

  if (loading || !user || user.role !== "admin") return <PageSkeleton shape="list" />;

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:p-6">
      <header>
        <h1 className="font-display text-3xl font-semibold leading-none">Motor</h1>
        <p className="mt-1 text-sm text-muted">
          Backtest de las recomendaciones: aciertos, fallos y ROI por banda. Métricas internas que
          el cliente no ve.
        </p>
      </header>
      {error ? <ErrorBox message={error} /> : null}
      <BacktestPanel variants={games.flatMap((g) => g.variants)} />
    </main>
  );
}
