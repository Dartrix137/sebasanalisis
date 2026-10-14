"use client";

/**
 * Menú de juegos (§7.2 y §7.4 de la Fase 4), en el inicio.
 *
 * Cada juego sale como lo decide el servidor en `GET /games`:
 *
 * - activo y con acceso: lleva a su página (`/juegos/<slug>`), donde se abre
 *   la mesa;
 * - "próximamente": se ve, sin enlace (un administrador sí entra, para probarlo);
 * - fuera del plan de la cuenta (`game_not_in_plan`): "Disponible en otro
 *   plan", con enlace a los planes;
 * - oculto: solo lo recibe un administrador, marcado como tal.
 */

import Link from "next/link";

import { GameIcon } from "@/components/GameIcon";
import type { GameMenuItem } from "@/lib/types/games";

export function GameMenu({ games, isAdmin }: { games: GameMenuItem[]; isAdmin: boolean }) {
  return (
    <ul className="mt-4 grid gap-3 sm:grid-cols-2">
      {games.map((game) => (
        <GameCard key={game.id} game={game} isAdmin={isAdmin} />
      ))}
    </ul>
  );
}

function GameCard({ game, isAdmin }: { game: GameMenuItem; isAdmin: boolean }) {
  const proximamente = game.status === "coming_soon";
  const fueraDelPlan = !proximamente && game.access.reason === "game_not_in_plan";
  // Un administrador abre mesa también en un juego "próximamente", para
  // probarlo antes de publicarlo; el servidor se lo permite solo a él.
  const jugable =
    (!proximamente || isAdmin) && game.access.granted && game.variants.length > 0;

  const contenido = (
    <>
      <div className="flex items-start gap-4">
        <span
          className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border ${
            jugable ? "border-gold/40 text-gold" : "border-edge text-muted"
          }`}
        >
          <GameIcon icon={game.icon} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-2xl font-semibold leading-none">{game.name}</h3>
            {proximamente ? <Tag>Próximamente</Tag> : null}
            {game.status === "hidden" ? <Tag>Oculto</Tag> : null}
          </div>
          {game.description ? (
            <p className="mt-2 text-sm leading-relaxed text-muted">{game.description}</p>
          ) : null}
        </div>
      </div>
      {fueraDelPlan ? (
        <p className="mt-4 text-sm">
          <span className="text-muted">Disponible en otro plan.</span>{" "}
          <Link href="/planes" className="font-bold text-gold hover:text-gold-soft">
            Ver planes
          </Link>
        </p>
      ) : null}
    </>
  );

  const base = "block h-full rounded-card border bg-ink-raised p-5 transition-colors";
  return (
    <li data-testid={`juego-${game.slug}`}>
      {jugable ? (
        <Link
          href={`/juegos/${game.slug}`}
          className={`${base} border-edge hover:border-gold/60`}
          aria-label={`Jugar ${game.name}`}
        >
          {contenido}
        </Link>
      ) : (
        <div className={`${base} border-edge opacity-80`}>{contenido}</div>
      )}
    </li>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-edge px-2 py-0.5 text-xs font-bold text-muted">
      {children}
    </span>
  );
}
