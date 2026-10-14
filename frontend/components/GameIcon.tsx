/**
 * Íconos del menú de juegos (§7.2 de la Fase 4). Es un set fijo: el juego
 * guarda el identificador y aquí se dibuja. No hay subida de imágenes.
 */

import type { GameIcon as GameIconId } from "@/lib/types/games";

const PATHS: Record<GameIconId, React.ReactNode> = {
  ruleta: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v5M12 16v5M3 12h5M16 12h5M5.6 5.6l3.6 3.6M14.8 14.8l3.6 3.6M18.4 5.6l-3.6 3.6M9.2 14.8l-3.6 3.6" />
    </>
  ),
  dados: (
    <>
      <rect x="3.5" y="3.5" width="17" height="17" rx="3.5" />
      <circle cx="8.5" cy="8.5" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="15.5" cy="15.5" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
    </>
  ),
  cartas: (
    <>
      <rect x="4" y="5" width="11" height="15" rx="2" />
      <path d="M9 4.2l9.4 2.5a2 2 0 0 1 1.4 2.4l-3 11.1" />
      <path d="M9.5 10.5c1-1.4 2.6-.4 0 2.2-2.6-2.6-1-3.6 0-2.2z" />
    </>
  ),
  deportes: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5l4 2.9-1.5 4.7h-5L8 10.4z" />
      <path d="M12 3v4.5M21 10.4l-5 0M17.5 20l-3-4.9M6.5 20l3-4.9M3 10.4h5" />
    </>
  ),
  generico: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="4" />
      <path d="M9 9h6M9 12h6M9 15h3" />
    </>
  ),
};

export function GameIcon({ icon, className = "h-7 w-7" }: { icon: GameIconId; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {PATHS[icon] ?? PATHS.generico}
    </svg>
  );
}
