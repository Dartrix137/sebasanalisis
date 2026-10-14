"use client";

/**
 * La mesa en `/juegos/<slug>/mesa/<id>` (§7.3 de la Fase 4).
 *
 * Pide la sesión, monta la pantalla del módulo de su juego (`lib/game-modules`)
 * y, si el slug de la URL no es el de su juego, la lleva al correcto. Si el
 * plan de la cuenta no incluye el juego de la mesa, el servidor responde
 * `403 game_not_in_plan` y aquí se dice eso, con el enlace a los planes.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { Button, Card, ErrorBox } from "@/components/ui";
import { ApiError, sessionsApi } from "@/lib/api-client";
import { SESSION_SCREENS } from "@/lib/game-modules";
import { useSession } from "@/lib/session";
import type { SessionResponse } from "@/lib/types/sessions";

type Estado =
  | { kind: "cargando" }
  | { kind: "lista"; session: SessionResponse }
  | { kind: "fuera_del_plan"; message: string }
  | { kind: "error"; message: string };

export function MesaScreen({ slug, sessionId }: { slug: string; sessionId: string }) {
  const { withToken } = useSession();
  const router = useRouter();
  const [estado, setEstado] = useState<Estado>({ kind: "cargando" });

  useEffect(() => {
    let vigente = true;
    withToken((t) => sessionsApi.get(t, sessionId))
      .then((session) => {
        if (!vigente) return;
        if (session.game_slug !== slug) {
          router.replace(`/juegos/${session.game_slug}/mesa/${session.id}`);
          return;
        }
        setEstado({ kind: "lista", session });
      })
      .catch((e: unknown) => {
        if (!vigente) return;
        if (e instanceof ApiError && e.code === "game_not_in_plan") {
          setEstado({ kind: "fuera_del_plan", message: e.message });
        } else {
          setEstado({
            kind: "error",
            message: e instanceof Error ? e.message : "Error inesperado",
          });
        }
      });
    return () => {
      vigente = false;
    };
  }, [withToken, sessionId, slug, router]);

  if (estado.kind === "cargando") return null;
  if (estado.kind === "lista") {
    const Screen = SESSION_SCREENS[estado.session.game_module];
    if (Screen) return <Screen sessionId={sessionId} />;
    return <Aviso titulo="Esta mesa no se puede abrir aquí" texto="Su juego todavía no tiene pantalla." />;
  }
  if (estado.kind === "fuera_del_plan") {
    return (
      <Aviso titulo="Este juego no está incluido en tu plan" texto="Está disponible en otro plan.">
        <Link
          href="/planes"
          className="inline-flex rounded-lg bg-gold px-4 py-2.5 text-sm font-bold text-gold-ink hover:bg-gold-soft"
        >
          Ver planes
        </Link>
      </Aviso>
    );
  }
  return (
    <div className="flex-1">
      <AppHeader />
      <main className="mx-auto max-w-3xl p-6">
        <ErrorBox message={estado.message} />
        <Button className="mt-4" onClick={() => router.push("/dashboard")}>
          Volver al menú
        </Button>
      </main>
    </div>
  );
}

function Aviso({
  titulo,
  texto,
  children,
}: {
  titulo: string;
  texto: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex-1">
      <AppHeader />
      <main className="mx-auto max-w-3xl p-4 sm:p-6">
        <Card>
          <h1 className="font-display text-3xl font-semibold leading-tight">{titulo}</h1>
          <p className="mt-2 text-sm text-muted">{texto}</p>
          <div className="mt-5 flex flex-wrap gap-3">
            {children}
            <Link
              href="/dashboard"
              className="inline-flex rounded-lg border border-edge px-4 py-2.5 text-sm font-bold text-muted hover:text-white"
            >
              Volver al menú
            </Link>
          </div>
        </Card>
      </main>
    </div>
  );
}
