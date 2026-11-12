"use client";

/**
 * El apartado "Guías" de un juego, `/juegos/<slug>/guias` (2026-11-12): los
 * videos de uso, en orden, y el PDF para descargar. Es lo mismo que la ventana
 * que sale una vez en el inicio, para volver a verlo cuando se quiera.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { PageSkeleton } from "@/components/PageSkeleton";
import { Card, ErrorBox } from "@/components/ui";
import { gamesApi } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import type { GameGuidesResponse } from "@/lib/types/games";

import { GuidePdfLink, GuideVideo } from "./GuideVideo";

export function GuidesPage({ slug }: { slug: string }) {
  const { withToken } = useSession();
  const [guides, setGuides] = useState<GameGuidesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    withToken((t) => gamesApi.guides(t, slug))
      .then(setGuides)
      .catch((e) => setError(e instanceof Error ? e.message : "Error inesperado"));
  }, [withToken, slug]);

  if (!guides && !error) return <PageSkeleton />;

  const vacia = guides !== null && guides.videos.length === 0 && guides.pdf === null;

  return (
    <div className="flex-1">
      <AppHeader />
      <main className="mx-auto max-w-5xl px-4 pb-12 pt-6 sm:px-6">
        <Link
          href={`/juegos/${slug}`}
          className="mb-6 inline-flex items-center gap-1.5 rounded-lg border border-edge bg-ink-sunken px-3 py-2 text-sm font-bold text-muted transition-colors hover:border-gold/50 hover:text-white"
        >
          <span aria-hidden>←</span> Volver al juego
        </Link>
        <h1 className="font-display text-4xl font-semibold leading-none tracking-tight sm:text-5xl">
          Guías
        </h1>
        <p className="mt-2 max-w-prose text-sm text-muted">
          Cómo usar la mesa paso a paso. Los videos van en orden: el segundo continúa el
          primero.
        </p>

        {error ? (
          <div className="mt-6">
            <ErrorBox message={error} />
          </div>
        ) : null}

        {vacia ? (
          <Card className="mt-6">
            <p className="text-sm text-muted">Este juego todavía no tiene guías.</p>
          </Card>
        ) : null}

        {guides ? (
          <div className="mt-8 space-y-10">
            {guides.videos.map((video, i) => (
              <section key={video.youtube_id} aria-labelledby={`guia-video-${i}`}>
                <h2
                  id={`guia-video-${i}`}
                  className="mb-3 font-display text-2xl font-semibold leading-tight"
                >
                  {video.title}
                </h2>
                <GuideVideo video={video} />
              </section>
            ))}
            {guides.pdf ? (
              <section aria-labelledby="guia-pdf-titulo">
                <h2
                  id="guia-pdf-titulo"
                  className="mb-3 font-display text-2xl font-semibold leading-tight"
                >
                  La guía en PDF
                </h2>
                <GuidePdfLink pdf={guides.pdf} />
              </section>
            ) : null}
          </div>
        ) : null}
      </main>
    </div>
  );
}
