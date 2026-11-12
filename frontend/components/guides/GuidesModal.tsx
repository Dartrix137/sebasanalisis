"use client";

/**
 * La ventana de las guías en el inicio (decidida el 2026-11-12): sale una sola
 * vez a cada cuenta con acceso, con los videos de uso uno tras otro y el PDF.
 *
 * Al cerrarla, con el botón o con Esc, se anota en el servidor
 * (`POST /auth/me/guides-seen`), así que no vuelve a salir tampoco en otro
 * dispositivo. Las guías siguen en el apartado "Guías" del juego.
 *
 * Es un `<dialog>` nativo abierto con `showModal()`: el navegador atrapa el
 * foco, cierra con Esc y deja inerte la página de atrás.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui";
import type { GameGuidesResponse } from "@/lib/types/games";

import { GuidePdfLink, GuideVideo } from "./GuideVideo";

export function GuidesModal({
  gameName,
  guides,
  guidesHref,
  onClose,
}: {
  /** El nombre del juego, como sale en el menú. */
  gameName: string;
  guides: GameGuidesResponse;
  /** La página de las guías del juego, para volver a verlas. */
  guidesHref: string;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [actual, setActual] = useState(0);
  const video = guides.videos[actual];
  const siguiente = guides.videos[actual + 1];

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby="guias-titulo"
      data-testid="guias-ventana"
      onClose={onClose}
      className="m-auto w-[calc(100%-2rem)] max-w-3xl rounded-card border border-edge bg-ink-raised p-0 text-white backdrop:bg-black/70"
    >
      <div className="p-4 sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="guias-titulo" className="font-display text-3xl font-semibold leading-tight">
              Cómo usar la mesa
            </h2>
            <p className="mt-1 text-sm text-muted">
              {guides.videos.length > 1
                ? `Video ${actual + 1} de ${guides.videos.length}: ${video.title}`
                : video.title}
            </p>
          </div>
          <button
            type="button"
            aria-label="Cerrar"
            onClick={() => ref.current?.close()}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-edge text-muted hover:border-gold/50 hover:text-white"
          >
            <span aria-hidden>✕</span>
          </button>
        </div>

        <div className="mt-4">
          {/* La key monta un iframe nuevo al cambiar de video. */}
          <GuideVideo key={video.youtube_id} video={video} />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          {siguiente ? (
            <Button onClick={() => setActual(actual + 1)}>Siguiente: {siguiente.title}</Button>
          ) : null}
          {actual > 0 ? (
            <Button variant="ghost" onClick={() => setActual(actual - 1)}>
              Anterior
            </Button>
          ) : null}
          {guides.pdf ? <GuidePdfLink pdf={guides.pdf} /> : null}
        </div>

        <p className="mt-5 border-t border-edge pt-4 text-sm text-muted">
          Esta ventana sale solo esta vez. Los videos y el PDF quedan en{" "}
          {/* Al navegar, la ventana se desmonta sin su evento `close`: se anota aquí. */}
          <Link href={guidesHref} onClick={onClose} className="font-bold text-gold hover:text-gold-soft">
            Guías
          </Link>
          , en la página de {gameName}.{" "}
          <button
            type="button"
            onClick={() => ref.current?.close()}
            className="font-bold text-gold hover:text-gold-soft"
          >
            Ver después
          </button>
        </p>
      </div>
    </dialog>
  );
}
