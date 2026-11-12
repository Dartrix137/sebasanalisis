/**
 * Un video de las guías, incrustado desde YouTube en modo de privacidad
 * mejorada (`www.youtube-nocookie.com`, decidido el 2026-11-12). El origen está
 * en `frame-src` de la CSP (`lib/csp.ts`) y YouTube figura en las políticas de
 * cookies y de datos: cambiarlo pide tocar las dos cosas.
 */

import { YOUTUBE_EMBED_ORIGIN } from "@/lib/csp";
import type { GuidePdfResponse, GuideVideoResponse } from "@/lib/types/games";

export function GuideVideo({ video }: { video: GuideVideoResponse }) {
  // `rel=0`: al terminar, solo sugiere videos del mismo canal.
  const src = `${YOUTUBE_EMBED_ORIGIN}/embed/${encodeURIComponent(video.youtube_id)}?rel=0`;
  return (
    <div className="aspect-video w-full overflow-hidden rounded-card border border-edge bg-ink-sunken">
      <iframe
        src={src}
        title={video.title}
        loading="lazy"
        allow="encrypted-media; picture-in-picture; fullscreen"
        allowFullScreen
        referrerPolicy="strict-origin-when-cross-origin"
        className="h-full w-full"
      />
    </div>
  );
}

/** El enlace para descargar el PDF de la guía, que está en Cloudinary. */
export function GuidePdfLink({ pdf }: { pdf: GuidePdfResponse }) {
  return (
    <a
      href={pdf.url}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="guia-pdf"
      className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-edge bg-ink-sunken px-4 py-2.5 text-sm font-bold text-white transition-colors hover:border-gold/50"
    >
      <span aria-hidden>↓</span> Descargar {pdf.title}
    </a>
  );
}
